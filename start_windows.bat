@echo off
rem reaper-monitor 启动脚本（Windows）
cd /d "%~dp0"

if not exist ".venv" (
  echo [reaper-monitor] 首次运行：创建虚拟环境…
  python -m venv .venv
)
if not exist ".venv\Scripts\uvicorn.exe" (
  echo [reaper-monitor] 安装依赖…
  ".venv\Scripts\pip" install --quiet -r requirements.txt
)

if exist ".env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do set "%%a=%%b"
)

if not defined RMP_HTTP_HOST set "RMP_HTTP_HOST=0.0.0.0"
if not defined RMP_HTTP_PORT set "RMP_HTTP_PORT=61390"

echo [reaper-monitor] 启动：http://本机IP:%RMP_HTTP_PORT%
".venv\Scripts\uvicorn" app.main:app --host %RMP_HTTP_HOST% --port %RMP_HTTP_PORT%
