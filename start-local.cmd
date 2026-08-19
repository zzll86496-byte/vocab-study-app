@echo off
setlocal
cd /d "%~dp0"
set "CODEX_PYTHON=C:\Users\翟张墨涵\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "LOCAL_URL=http://127.0.0.1:4173/"

echo.
echo  等价词库本地网页
echo  地址: %LOCAL_URL%
echo  关闭本窗口即可停止网站。
echo.

start "" "%LOCAL_URL%"

if exist "%CODEX_PYTHON%" (
  "%CODEX_PYTHON%" -m http.server 4173 --bind 127.0.0.1 --directory "%~dp0"
) else (
  py -3 -m http.server 4173 --bind 127.0.0.1 --directory "%~dp0"
)

if errorlevel 1 (
  echo.
  echo 启动失败：请确认 4173 端口未被其他程序占用。
  pause
)
