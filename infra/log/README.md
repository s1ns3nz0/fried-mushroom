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

## 보안 / 네트워크 노출 (F-08 의도적 트레이드오프)

> **DevSecOps 감사 F-08 결정 기록** (#275). 이 섹션은 공개 포트 노출을 의도적 트레이드오프로 명시하며,
> 운영 환경 전환 시 적용할 최소 하드닝 경로를 문서화한다.

### 현재 설계 (데모/연구 목적)

`infra/terraform/security.tf` 의 `ground` 보안 그룹은 아래 포트를 `0.0.0.0/0` (전 인터넷) 개방한다.

| 포트 | 서비스 | 역할 |
|------|--------|------|
| 8400 | ground app | GCS 지상기지국 대시보드 |
| 8500 | `log_server.py` | 실시간 레이어 로그 스트림 (대시보드 → WebSocket) |
| 8181 | `main.py` | UAV raw_log 수신 (비행 후 일괄 POST) |

두 FastAPI 서비스(`log_server.py`, `main.py`)에는 **API key / 세션 토큰 / mTLS 등 인증 수단이 없다.**
이는 **의도적 트레이드오프** — D4D MVP 는 단독 운용 시연(데모) 환경을 전제하며,
인증 없는 공개 접근이 데모 동작의 단순성을 위해 채택됐다.

**리스크 수용 범위**: 공개된 네트워크에서 8400/8500/8181 에 인증 없이 접근 가능.
raw_log 엔드포인트(8181)는 기체 미션 데이터 수신 창구이므로 스푸핑/주입 가능성이 존재한다.
대시보드/로그 스트림(8400/8500)은 조회 전용이나 내부 운용 정보가 노출된다.

### 운영 환경 전환 시 최소 하드닝 경로

실제 운영 배포 전 아래 중 하나 이상 적용을 권고한다.

1. **SG CIDR 좁히기** (가장 빠른 조치): `infra/terraform/variables.tf` 에
   `allowed_ground_cidr` 변수를 추가해 운영자 IP / VPN CIDR 로 각 포트 ingress 제한.
   ```hcl
   # variables.tf 예시
   variable "allowed_ground_cidr" {
     description = "지상국 서비스 접근 허용 CIDR (기본 0.0.0.0/0은 데모 전용)"
     type        = string
     default     = "0.0.0.0/0"  # 운영 시 반드시 좁힐 것
   }
   ```

2. **API key 헤더 추가** (앱 레이어, 별도 이슈): `log_server.py` / `main.py` FastAPI
   미들웨어에 `X-API-Key` 헤더 검증 추가 — EC2 Secrets Manager 연동 권장.

3. **CloudFront + WAF 뒤 배치** (8500 대시보드 전용): CloudFront 배포를 오리진 그룹에
   추가하고 WAF IP allow-list 로 접근 제한. S3 대시보드(`deploy-dashboard.yml`)와
   같은 방식으로 운영 가능.

4. **mTLS** (8181 raw_log, 장기): UAV↔지상 C2 링크 인증과 통합해 클라이언트 인증서 발급.

### 현재 결정 요약

| 항목 | 값 |
|------|-----|
| 결정 | 의도적 공개 (데모/MVP 스코프) |
| 리스크 수용 | 단독 시연 환경 한정 |
| 운영 전환 조건 | SG CIDR 축소 + 최소 API key 인증 (#F-08 권고) |
| 관련 이슈 | DevSecOps 감사 #232 F-08, 결정 이슈 #275 |
