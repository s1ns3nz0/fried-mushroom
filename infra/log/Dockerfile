# 로그 수집기(log) — FastAPI + uvicorn, amd64 타겟.
# 빌드 컨텍스트: infra/log/ (이 파일이 있는 디렉터리에서 build).
#
# 이 컨테이너는 성격이 다른 두 로그 계층을 함께 실행한다(README.md · API.md 참고):
#   - log_server.py : 실시간 로그 스트림(POST /log, WS /logs) — 포트 8500 (운영 관측용, 대시보드 연동)
#   - main.py       : raw_log 수신(POST /raw_log)             — 포트 8181 (비행후 RAG 학습용, 무손실)
FROM --platform=linux/amd64 python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8500 8181

CMD ["bash", "-c", "uvicorn log_server:app --host 0.0.0.0 --port 8500 & uvicorn main:app --host 0.0.0.0 --port 8181 & wait -n"]
