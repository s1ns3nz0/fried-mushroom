# log

D4D **로그 수집기** — uav raw_log 수집 → ground/rag 학습 입력 공급.

uav(온보드)가 비행 후 일괄 전송하는 무손실 원본(`raw_log`)을 지상에서 수신·저장하고,
검색용 인덱스(`episode_index`)로 구조화집계한다. 이것이 ground/rag(임무해석 RAG)의
학습 입력을 공급하는 지상 수신단이다.

## raw_log / episode_index — 2계층

docs/architecture/ground/02-learning-rag.md 의 2계층 구조를 그대로 구현한다.

| 계층 | 저장소 | 성격 | 담당 |
|---|---|---|---|
| `raw_log` | 파일시스템(임무당 1개 JSON) | 무손실 원본 — GPS/기체상태/위협모델링/위험평가 시계열 | `collector.py` |
| `episode_index` | SQLite + sqlite-vec | 검색 전용 — 구조화필드(자동집계) + narrative + embedding + raw_log_ref | `aggregate.py` · `store.py` · `schema.sql` |

### 워크플로우

1. **임무종료** → uav가 `raw_log` 일괄 전송 → `collector.py`가 `raw/<mission_id>.json` 저장
   (실시간 아님 — C2 링크 끊김 시 손상 방지).
2. **자동집계** → `aggregate.py`가 구조화필드(terrain_composition/threat_events/outcome)
   즉시 집계 + narrative LLM 초안 → `narrative_status="pending"`.
3. **오퍼레이터 승인** → `store.confirm()` → `"human_confirmed"` + embedding 편입(검색가능).
4. **미승인(pending)은 검색에서 완전 제외** — 감사가능성 원칙, 사람 확인분만 코퍼스 편입.

## 파일

| 파일 | 역할 |
|---|---|
| `collector.py` | raw_log 수신(HTTP POST /raw_log 또는 파일 watch) → 파일시스템 저장 |
| `aggregate.py` | raw_log → episode_index 구조화집계 + narrative 초안(스텁) |
| `schema.sql` | episode_index SQLite 스키마 (+ sqlite-vec 벡터검색 주석) |
| `store.py` | episode_index 저장/승인/검색(메타필터 + 벡터유사도) 인터페이스 |
| `main.py` | FastAPI 엔트리 — `POST /raw_log` → `collector.py` 위임 |

## 현재 상태

스켈레톤 — 클래스/함수 시그니처 + docstring + TODO. 실제 로직 없음.

## Docker

컨테이너 하나에서 raw_log 수신(main.py, 8181)과 실시간 로그 스트림(log_server.py, 8500)을
함께 실행한다 — 후자는 API.md 참고.

```bash
# 로컬 빌드/실행 (컨텍스트: infra/log/)
docker build -t log ./infra/log
docker run --rm -p 8500:8500 -p 8181:8181 -v log-data:/var/log/fried-mushroom-uav log

# 또는 지상기지국 2컨테이너(ground + log) 동시 실행
docker compose up log
```

EC2 배포는 `infra/terraform/templates/docker-compose.yml.tftpl` 참고(ECR 이미지 기반).
