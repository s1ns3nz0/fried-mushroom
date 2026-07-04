# 로그 수집기(log) — FastAPI + uvicorn, amd64 타겟.
# 빌드 컨텍스트: repo 루트 (docker build -f infra/log/Dockerfile .).
#   log_server.py 가 /gcs/run 으로 온보드 파이프라인(run_cycle)을 직접 실행하므로
#   src/onboard + examples/ 를 이미지에 포함해야 한다. 컨테이너 내 레이아웃은
#   repo 와 동일(/app = repo 루트)하게 유지해 log_server.py 의 parents[2] 경로
#   해석(src/, examples/)이 그대로 동작한다.
#
# 이 컨테이너는 성격이 다른 두 로그 계층을 함께 실행한다(README.md · API.md 참고):
#   - log_server.py : 실시간 로그 스트림 + /gcs/* 파이프라인 실행 — 포트 8500 (운영 관측용, 대시보드 연동)
#   - main.py       : raw_log 수신(POST /raw_log)               — 포트 8181 (비행후 RAG 학습용, 무손실)
FROM --platform=linux/amd64 python:3.11-slim

# WORKDIR 는 infra/log — uvicorn CMD 가 log_server.py / main.py 를 모듈로 찾는다.
WORKDIR /app/infra/log

COPY infra/log/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY infra/log/ .
COPY pyproject.toml /app/
COPY src/ /app/src/
COPY examples/ /app/examples/

# onboard 패키지 import 경로 — pip install -e . 대신 PYTHONPATH 로 단순 유지.
ENV PYTHONPATH=/app/src

EXPOSE 8500 8181

CMD ["bash", "-c", "uvicorn log_server:app --host 0.0.0.0 --port 8500 & uvicorn main:app --host 0.0.0.0 --port 8181 & wait -n"]
