-- episode_index — 검색 전용 인덱스 (SQLite + sqlite-vec).
-- raw_log(무손실 원본)에서 자동집계한 구조화필드 + narrative(LLM초안+사람승인)
-- + embedding + raw_log_ref(포인터)를 보관한다.
-- 스키마 출처: docs/architecture/ground/02-learning-rag.md (episode_index)
--
-- narrative_status='pending'은 검색 코퍼스에서 완전 제외(감사가능성 원칙) —
-- 검색 쿼리는 반드시 narrative_status='human_confirmed' 필터를 건다.

CREATE TABLE IF NOT EXISTS episode_index (
    mission_id          TEXT PRIMARY KEY,          -- 임무 식별자 (예: "m-0417")
    raw_log_ref         TEXT NOT NULL,             -- raw_log 파일 포인터 (예: "raw/m-0417.json")
    corridor_region     TEXT,                      -- 회랑 지역 코드 (예: "KR-hill-07")
    threat_events       TEXT,                      -- JSON 배열 (예: ["T3","T1"])
    outcome             TEXT,                      -- 임무 결과 (예: "rtb_success")
    terrain_composition TEXT,                      -- JSON 객체 (예: {"ridge":0.4,"valley":0.5,"open":0.1})
    narrative           TEXT,                      -- LLM 초안 서술 (사람 승인 대상)
    narrative_status    TEXT NOT NULL DEFAULT 'pending',  -- 'pending' | 'human_confirmed'
    embedding           BLOB,                      -- 다국어 sentence-transformer 벡터 (승인 후 채움)
    ts                  INTEGER                    -- 집계/편입 시각 (epoch)
);

-- 메타데이터 필터 인덱스 (검색 1단계: threat_events/corridor_region → 후보 축소).
CREATE INDEX IF NOT EXISTS idx_episode_region ON episode_index (corridor_region);
CREATE INDEX IF NOT EXISTS idx_episode_status ON episode_index (narrative_status);

-- sqlite-vec 벡터 검색 (검색 2단계: 벡터 유사도).
-- 로드 후 가상테이블로 embedding 유사도 top-k 조회. embedding 차원은 임베딩 모델에 맞춘다.
--   .load ./vec0
--   CREATE VIRTUAL TABLE IF NOT EXISTS episode_vec USING vec0(
--       mission_id TEXT PRIMARY KEY,
--       embedding  FLOAT[384]     -- 예: multilingual MiniLM 384차원
--   );
-- 검색: 메타필터(위 인덱스) → episode_vec MATCH 벡터유사도 → 임계미달 시 1회 재검색.


-- ─────────────────────────────────────────────────────────────────────────────
-- corpus_record — RAG 코퍼스 학습레코드 (라운드 1).
-- episode(집계) → 위협 판정 하나당 학습레코드 1건으로 펼친 결과. "다음 임무 브리핑 시
-- NLP confidence 참고자료" 회수의 저장소. 스키마 출처: docs/RAG-corpus.md.
CREATE TABLE IF NOT EXISTS corpus_record (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id       TEXT NOT NULL,             -- 임무 식별자 (episode_index.mission_id)
    raw_log_ref      TEXT,                      -- raw_log 파일 포인터 (추적)
    mission_context  TEXT NOT NULL,             -- 임무유형 (예: "정찰") — 회수 키
    posture          TEXT,                      -- 경계태세 표준 JSON (예: {"defcon":3,...}) — 회수 키
    threat_event     TEXT NOT NULL,             -- 위협 이벤트 코드 (예: "T3") — 회수 키
    confidence       REAL,                      -- 판정 confidence (04/NLP 확신도)
    outcome          TEXT,                      -- 실제 outcome (예: "rtb_success")
    corridor_region  TEXT,                      -- 지역 코드 (보조 필터)
    kill_chain_stage TEXT,                      -- 킬체인 단계 (보조)
    ts               INTEGER,                   -- 집계/편입 시각 (epoch)
    UNIQUE (mission_id, threat_event)           -- 재집계 멱등 (ON CONFLICT DO UPDATE)
);

-- 회수 1단계 메타필터 인덱스 (mission_context / threat_event → 후보 축소).
CREATE INDEX IF NOT EXISTS idx_corpus_context ON corpus_record (mission_context);
CREATE INDEX IF NOT EXISTS idx_corpus_threat ON corpus_record (threat_event);
