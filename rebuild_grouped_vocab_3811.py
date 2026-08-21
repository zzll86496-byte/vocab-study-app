import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


TOKEN_RE = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)*")
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def read_docx_paragraphs(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    paragraphs = []
    for paragraph in root.findall(".//w:p", NS):
        text = "".join((node.text or "") for node in paragraph.findall(".//w:t", NS)).strip()
        if text:
            paragraphs.append(text)
    return paragraphs


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" ,，;；:：()（）[]")


def category_for(paragraph: str) -> str:
    match = TOKEN_RE.search(paragraph)
    if not match:
        return ""
    prefix = clean(paragraph[: match.start()])
    prefix = re.sub(r"[^\u3400-\u4dbf\u4e00-\u9fff、，；·]+", "", prefix)
    return prefix[-14:]


def matching_parenthetical(text: str, open_at: int) -> str | None:
    opener = text[open_at]
    closer = ")" if opener == "(" else "）"
    depth = 0
    for index in range(open_at, len(text)):
        if text[index] == opener:
            depth += 1
        elif text[index] == closer:
            depth -= 1
            if depth == 0:
                return text[open_at + 1 : index]
    return None


def source_context(paragraph: str, start: int, end: int, category: str) -> str:
    after = re.match(r"\s*([（(])", paragraph[end:])
    if after:
        open_at = end + after.start(1)
        inside = matching_parenthetical(paragraph, open_at)
        if inside:
            context = clean(inside)
            if context:
                return f"{category}｜{context}" if category else context

    delimiters = ",，;；()（）\n"
    left = max(paragraph.rfind(char, 0, start) for char in delimiters)
    right_positions = [paragraph.find(char, end) for char in delimiters]
    right_positions = [position for position in right_positions if position >= 0]
    right = min(right_positions) if right_positions else len(paragraph)
    context = clean(paragraph[left + 1 : right])

    if not CJK_RE.search(context):
        context = clean(paragraph[max(0, start - 75) : min(len(paragraph), end + 105)])
    if len(context) > 220:
        context = context[:217].rstrip() + "…"
    if category and not context.startswith(category):
        context = f"{category}｜{context}"
    return context or category or "原文词条"


def build_entries(paragraphs: list[str]) -> tuple[list[dict], int]:
    entries = []
    group = 0
    for paragraph in paragraphs:
        matches = list(TOKEN_RE.finditer(paragraph))
        if not matches:
            continue
        category = category_for(paragraph)
        group_label = category or f"同义词组 {group + 1}"
        for match in matches:
            entries.append(
                {
                    "group": group,
                    "groupLabel": group_label,
                    "word": match.group(0),
                    "meaning": source_context(paragraph, match.start(), match.end(), category),
                }
            )
        group += 1
    return entries, group


def main() -> None:
    source = Path(sys.argv[1])
    output = Path(sys.argv[2])
    entries, groups = build_entries(read_docx_paragraphs(source))
    if len(entries) != 3811:
        raise SystemExit(f"Expected 3811 entries, extracted {len(entries)}")
    output.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    unique = len({entry["word"].casefold() for entry in entries})
    print(json.dumps({"entries": len(entries), "unique": unique, "duplicates": len(entries) - unique, "groups": groups}, ensure_ascii=True))


if __name__ == "__main__":
    main()
