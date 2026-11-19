#!/bin/bash
# reaper-monitor 启动脚本（macOS）
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "[reaper-monitor] 首次运行：创建虚拟环境…"
  python3 -m venv .venv
fi
if [ ! -x ".venv/bin/uvicorn" ]; then
  echo "[reaper-monitor] 安装依赖…"
  .venv/bin/pip install --quiet -r requirements.txt
fi

# 读取 .env（存在时），让 HTTP 端口与其余 RMP_* 设置同源
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

if [ -z "$RMP_HTTP_HOST" ]; then RMP_HTTP_HOST=0.0.0.0; fi
if [ -z "$RMP_HTTP_PORT" ]; then RMP_HTTP_PORT=61390; fi

echo "[reaper-monitor] 启动：http://$(ipconfig getifaddr en0 2>/dev/null || echo 本机IP):$RMP_HTTP_PORT"
exec .venv/bin/uvicorn app.main:app --host "$RMP_HTTP_HOST" --port "$RMP_HTTP_PORT"
