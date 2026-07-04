#!/usr/bin/env bash
# 로컬 개발용 전체 관측 스택 런처 (#276, #259 재작성).
#
# collector(infra/log/log_server.py, uvicorn) :$COLLECTOR_PORT
#   → /health 폴링
#   → vizsim 피더(infra/vizsim/runner.py --collector http://127.0.0.1:$COLLECTOR_PORT)
#   → dashboard(infra/dashboard/main.py, uvicorn) :$DASH_PORT
#
# COLLECTOR_PORT 정합: 대시보드 프론트(static/app.js)는 /config.json(정적, 커밋된 파일)을
# /config(백엔드, env 기반)보다 먼저 조회하고 log_ws_url 이 있으면 그대로 쓴다. 즉 main.py
# 의 DASHBOARD_LOG_WS_URL/DASHBOARD_COLLECTOR_HTTP_URL env 만으로는 static/config.json 의
# 하드코딩(8500)이 이겨서 COLLECTOR_PORT 오버라이드가 먹지 않는다. 이 스크립트는 실행 중
# static/config.json 을 $COLLECTOR_PORT 기준으로 런타임 재생성하고, 종료 시(trap) 원본으로
# 복원한다 — 커밋된 config.json 의 기본값(8500)은 이 스크립트 실행 후에도 그대로 유지된다.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"

SEED="${SEED:-42}"
BRIEF="${BRIEF:-$REPO_ROOT/examples/mission_brief_t3.json}"
DIRECTIVE="${DIRECTIVE:-}"
COLLECTOR_PORT="${COLLECTOR_PORT:-8500}"
DASH_PORT="${DASH_PORT:-8080}"
RATE="${RATE:-2}"
SPEED="${SPEED:-1}"

DASHBOARD_DIR="$REPO_ROOT/infra/dashboard"
LOG_DIR="$REPO_ROOT/infra/log"
CONFIG_JSON="$DASHBOARD_DIR/static/config.json"

COLLECTOR_URL="http://127.0.0.1:$COLLECTOR_PORT"

CONFIG_JSON_BACKUP=""
PIDS=()

cleanup() {
  local pid
  for pid in "${PIDS[@]:-}"; do
    [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
  done
  # 커밋된 config.json 기본값(8500)을 보존하기 위해 런타임 재생성분을 원복.
  if [[ -n "$CONFIG_JSON_BACKUP" && -f "$CONFIG_JSON_BACKUP" ]]; then
    cp "$CONFIG_JSON_BACKUP" "$CONFIG_JSON"
    rm -f "$CONFIG_JSON_BACKUP"
    CONFIG_JSON_BACKUP=""
  fi
}
trap cleanup EXIT INT TERM

CONFIG_JSON_BACKUP="$(mktemp)"
cp "$CONFIG_JSON" "$CONFIG_JSON_BACKUP"
cat > "$CONFIG_JSON" <<EOF
{
  "_comment": "런타임 재생성(scripts/dev_stack.sh, COLLECTOR_PORT=$COLLECTOR_PORT) — 스크립트 종료 시 원복됨.",
  "log_ws_url": "ws://localhost:$COLLECTOR_PORT/logs",
  "collector_http_url": "http://localhost:$COLLECTOR_PORT"
}
EOF

echo "[dev_stack] collector 기동 :$COLLECTOR_PORT ..."
"$PYTHON" -m uvicorn log_server:app --app-dir "$LOG_DIR" --host 0.0.0.0 --port "$COLLECTOR_PORT" &
PIDS+=("$!")

echo "[dev_stack] collector /health 폴링..."
health_ok=0
for _ in $(seq 1 30); do
  if curl -sf "$COLLECTOR_URL/health" >/dev/null 2>&1; then
    health_ok=1
    break
  fi
  sleep 0.5
done
if [[ "$health_ok" -ne 1 ]]; then
  echo "[dev_stack] ERROR: collector가 $COLLECTOR_URL/health 에 응답하지 않음 (fastapi/uvicorn 설치 확인)" >&2
  exit 1
fi

echo "[dev_stack] vizsim 피더 기동 (seed=$SEED, rate=$RATE, speed=$SPEED)..."
DIRECTIVE_ARGS=()
if [[ -n "$DIRECTIVE" ]]; then
  DIRECTIVE_ARGS=(--directive "$DIRECTIVE")
fi
"$PYTHON" "$REPO_ROOT/infra/vizsim/runner.py" \
  --seed "$SEED" --brief "$BRIEF" --rate "$RATE" --speed "$SPEED" \
  --collector "$COLLECTOR_URL" "${DIRECTIVE_ARGS[@]}" &
PIDS+=("$!")

echo "[dev_stack] dashboard 기동 :$DASH_PORT ..."
DASHBOARD_LOG_WS_URL="ws://localhost:$COLLECTOR_PORT/logs" \
DASHBOARD_COLLECTOR_HTTP_URL="http://localhost:$COLLECTOR_PORT" \
"$PYTHON" -m uvicorn main:app --app-dir "$DASHBOARD_DIR" --host 0.0.0.0 --port "$DASH_PORT" &
PIDS+=("$!")

echo "[dev_stack] 준비 완료 — 대시보드: http://localhost:$DASH_PORT (Ctrl-C 로 전체 종료)"
wait
