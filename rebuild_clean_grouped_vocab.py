import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’\-]*(?:\s+[A-Za-z][A-Za-z'’\-]*)*")
LATIN_RE = re.compile(r"[A-Za-z]+(?:[-'’][A-Za-z]+)*")
POS_LABELS = re.compile(r"\b(?:SYN|OPP|n|v|vt|vi|adj|adv|prep|conj)\.?\b", re.I)
EXCLUDE_SINGLE = {
    "a", "an", "the", "to", "by", "of", "for", "from", "in", "into", "on", "at",
    "with", "without", "and", "or", "as", "be", "is", "are", "was", "were", "do",
    "does", "did", "can", "must", "it", "you", "your", "yourself", "who", "somebody",
    "someone", "something", "person", "people", "else", "sb", "sth", "xx", "n", "v",
    "vt", "vi", "adj", "adv", "prep", "conj", "syn", "opp",
}


def read_paragraphs(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    paragraphs = []
    for paragraph in root.findall(".//w:body/w:p", NS):
        text = "".join((node.text or "") for node in paragraph.findall(".//w:t", NS))
        text = text.replace("\xa0", " ").strip()
        if text:
            paragraphs.append(text)
    return paragraphs


def split_top_level(text: str) -> list[str]:
    parts = []
    buffer = []
    depth = 0
    for char in text:
        if char in "(（":
            depth += 1
            buffer.append(char)
        elif char in ")）":
            depth = max(0, depth - 1)
            buffer.append(char)
        elif depth == 0 and char in ",，;；=\n–—":
            part = "".join(buffer).strip()
            if part:
                parts.append(part)
            buffer = []
        else:
            buffer.append(char)
    part = "".join(buffer).strip()
    if part:
        parts.append(part)
    return parts


def extract_balanced_meaning(segment: str) -> str:
    starts = [index for index in (segment.find("("), segment.find("（")) if index >= 0]
    if not starts:
        return ""
    start = min(starts)
    depth = 0
    output = []
    for char in segment[start:]:
        if char in "(（":
            depth += 1
            if depth > 1:
                output.append(char)
        elif char in ")）":
            depth -= 1
            if depth <= 0:
                break
            output.append(char)
        elif depth >= 1:
            output.append(char)
    return "".join(output).strip()


def clean_head(segment: str) -> str | None:
    starts = [index for index in (segment.find("("), segment.find("（")) if index >= 0]
    prefix = segment[: min(starts)] if starts else segment
    prefix = POS_LABELS.sub(" | ", prefix)
    candidates = WORD_RE.findall(prefix)
    if not candidates:
        return None
    term = candidates[-1].replace("’", "'").strip(" -'\"")
    term = re.sub(r"\s+", " ", term)
    if not term or len(term) == 1:
        return None
    if " " not in term and term.casefold() in EXCLUDE_SINGLE:
        return None
    return term


def category_for(paragraph: str) -> str:
    first_english = re.search(r"[A-Za-z]", paragraph)
    if not first_english:
        return ""
    category = paragraph[: first_english.start()].strip(" \t:：,，;；")
    category = re.sub(r"[^\u3400-\u4dbf\u4e00-\u9fff、，；·]+", "", category)
    return category[-14:]


def clean_meaning(raw: str, category: str) -> str:
    text = raw.replace("\xa0", " ")
    text = LATIN_RE.sub("", text)
    text = re.sub(r"\d+", "", text)
    text = text.replace("[", "〔").replace("]", "〕")
    text = text.replace("<", "〔").replace(">", "〕")
    text = re.sub(r"[=/|]+", "；", text)
    text = re.sub(r"\(\s*\)|（\s*）|〔\s*〕", "", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*([，；。！？、：])\s*", r"\1", text)
    text = re.sub(r"[，；、：.。\s]+$", "", text)
    text = re.sub(r"^[，；、：.。\s]+", "", text)
    text = re.sub(r"([，；、])\1+", r"\1", text)
    if not CJK_RE.search(text):
        text = category
    if len(text) > 110:
        text = text[:107].rstrip("，；、：.。 ") + "…"
    return text or category or "原文释义"


def build_entries(paragraphs: list[str]) -> tuple[list[dict], int]:
    entries = []
    group = 0
    for paragraph in paragraphs:
        category = category_for(paragraph)
        paragraph_entries = []
        for segment in split_top_level(paragraph):
            word = clean_head(segment)
            if not word:
                continue
            raw_meaning = extract_balanced_meaning(segment)
            paragraph_entries.append(
                {
                    "group": group,
                    "groupLabel": category or f"同义词组 {group + 1}",
                    "word": word,
                    "meaning": clean_meaning(raw_meaning, category),
                }
            )
        if paragraph_entries:
            entries.extend(paragraph_entries)
            group += 1
    return entries, group


def main() -> None:
    source = Path(sys.argv[1])
    output = Path(sys.argv[2])
    entries, groups = build_entries(read_paragraphs(source))
    forbidden = sorted({item["word"].casefold() for item in entries} & EXCLUDE_SINGLE)
    latin_meanings = sum(bool(LATIN_RE.search(item["meaning"])) for item in entries)
    if forbidden:
        raise SystemExit(f"Forbidden standalone tokens remain: {forbidden}")
    if latin_meanings:
        raise SystemExit(f"Meanings containing Latin text remain: {latin_meanings}")
    if any(not item["meaning"] for item in entries):
        raise SystemExit("Empty meaning detected")
    output.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    unique = len({item["word"].casefold() for item in entries})
    print(
        json.dumps(
            {
                "entries": len(entries),
                "unique": unique,
                "duplicates": len(entries) - unique,
                "groups": groups,
                "forbidden_standalone_tokens": forbidden,
                "latin_meanings": latin_meanings,
                "max_meaning_length": max(map(lambda item: len(item["meaning"]), entries)),
            },
            ensure_ascii=True,
        )
    )


if __name__ == "__main__":
    main()
