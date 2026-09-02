#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEB_DIR="$ROOT_DIR/web"
API_PORT="${API_PORT:-8090}"
WEB_PORT="${WEB_PORT:-5173}"
API_PID=""
WEB_PID=""

port_in_use() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

stop_port() {
  local port="$1"
  local pids
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  [[ -z "$pids" ]] && return
  echo "[LOB] 停止占用端口 $port 的旧进程：${pids//$'\n'/ }"
  kill $pids 2>/dev/null || true
  for _ in {1..20}; do
    port_in_use "$port" || return
    sleep 0.1
  done
  echo "[LOB] 端口 $port 的旧进程未能正常停止。" >&2
  exit 1
}

cleanup() {
  trap - EXIT INT TERM
  [[ -n "$WEB_PID" ]] && kill "$WEB_PID" 2>/dev/null || true
  [[ -n "$API_PID" ]] && kill "$API_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

cd "$ROOT_DIR"

stop_port "$API_PORT"
stop_port "$WEB_PORT"

if [[ ! -d "$WEB_DIR/node_modules" ]]; then
  echo "[LOB] 安装 React 前端依赖..."
  (cd "$WEB_DIR" && npm install)
fi

echo "[LOB] 启动 FastAPI: http://127.0.0.1:$API_PORT"
uv run uvicorn lob_browser.web.api:app --reload --port "$API_PORT" &
API_PID=$!

for _ in {1..30}; do
  if ! kill -0 "$API_PID" 2>/dev/null; then
    echo "[LOB] FastAPI 启动失败，请查看上方错误。" >&2
    exit 1
  fi
  if curl --silent --fail "http://127.0.0.1:$API_PORT/api/health" >/dev/null; then
    break
  fi
  sleep 0.5
done
if ! curl --silent --fail "http://127.0.0.1:$API_PORT/api/health" >/dev/null; then
  echo "[LOB] FastAPI 健康检查超时，未启动前端。" >&2
  exit 1
fi

echo "[LOB] 启动 React: http://127.0.0.1:$WEB_PORT"
(cd "$WEB_DIR" && npm run dev -- --port "$WEB_PORT" --strictPort) &
WEB_PID=$!

echo "[LOB] 前端与 API 已启动，按 Ctrl+C 停止"
while kill -0 "$API_PID" 2>/dev/null && kill -0 "$WEB_PID" 2>/dev/null; do
  sleep 1
done

echo "[LOB] 检测到服务退出，正在停止其余进程..."
