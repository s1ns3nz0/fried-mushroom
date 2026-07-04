#!/usr/bin/env bash
# 로컬 개발용 전체 관측 스택 런처 — 수집기 + vizsim 피더 + 대시보드를
# 한 번에 띄운다 (CI/CD 배포 없이 수동으로 검증된 구성을 재현).
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

export PYTHONPATH="$REPO_ROOT/infra:$REPO_ROOT/src:$REPO_ROOT/infra/log"

PIDS=()

cleanup() {
    for pid in "${PIDS[@]:-}"; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
    done
}
trap cleanup EXIT INT TERM

echo "[dev_stack] 수집기 기동 중... (port $COLLECTOR_PORT)"
"$PYTHON" -m uvicorn log_server:app --host 127.0.0.1 --port "$COLLECTOR_PORT" &
COLLECTOR_PID=$!
PIDS+=("$COLLECTOR_PID")

echo "[dev_stack] 수집기 /health 대기 중..."
READY=""
for _ in $(seq 1 20); do
    if curl -s -o /dev/null "http://127.0.0.1:$COLLECTOR_PORT/health"; then
        READY="1"
        break
    fi
    sleep 0.5
done
if [ -z "$READY" ]; then
    echo "[dev_stack] 수집기가 준비되지 않았습니다 (timeout)." >&2
    exit 1
fi
echo "[dev_stack] 수집기 준비 완료."

echo "[dev_stack] vizsim 피더 기동 중..."
FEEDER_ARGS=(
    -m vizsim.runner
    --seed "$SEED"
    --brief "$BRIEF"
    --collector "http://127.0.0.1:$COLLECTOR_PORT"
    --rate "$RATE"
    --speed "$SPEED"
)
if [ -n "$DIRECTIVE" ]; then
    FEEDER_ARGS+=(--directive "$DIRECTIVE")
fi
"$PYTHON" "${FEEDER_ARGS[@]}" &
FEEDER_PID=$!
PIDS+=("$FEEDER_PID")

echo "[dev_stack] 대시보드 기동 중... (port $DASH_PORT)"
"$PYTHON" -m uvicorn main:app --host 127.0.0.1 --port "$DASH_PORT" --app-dir "$REPO_ROOT/infra/dashboard" &
DASH_PID=$!
PIDS+=("$DASH_PID")

echo "[dev_stack] 대시보드: http://localhost:$DASH_PORT"
wait
