# Step 4: layer-03-ai-stub-channels

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/CLAUDE.md`
- `/docs/ADR.md` (ADR-002 AI 스텁 우선)
- `/d4d_pipeline/schemas.py` (Step 1)
- `/d4d_pipeline/layer_02_sensor/schema.py`, `mock_source.py` (Step 2 — imagery/acoustic 필드에 심어둔 mock 라벨 힌트)
- `/d4d_pipeline/layer_03_abstraction/run.py` 및 채널 모듈 전체 (Step 3 — 이 step은 이 오케스트레이터에 3채널을 추가한다)
- `/examples/raw_t3.json`, `raw_t4.json`, `raw_t7.json`

D4D 원문 문서 (레포 내 `/docs/D4D/`):

- `/docs/D4D/03. Sensor Abstraction Layer.md` — proximity_object(🟡 AI 필수), terrain_class(🔵 GIS 우선 + 🟡 카메라 세그멘테이션 보조), acoustic_event(🟡 YAMNet 2차) 상세
- `/docs/D4D/A-1. 추상 결과 세부 내용.md` — payload 필드

## 작업

03의 AI 사용 채널 3종을 stub으로 추가한다. 실제 모델 로딩은 하지 않고 `d4d_pipeline/ai_stubs/`의 함수가 raw envelope의 mock 라벨 힌트를 읽어 고정 결과를 리턴한다.

### 1) AI stub 모듈 `d4d_pipeline/ai_stubs/`

각 파일에 인터페이스 함수 하나씩:

```python
# yolo_stub.py
def detect_proximity(raw_imagery: dict) -> dict:
    """
    반환:
      {
        "class": "person" | "vehicle" | "drone" | None,
        "weapon_shape": bool,
        "bearing_deg": float | None,
        "closing": bool,
        "closure_rate_mps": float,
        "quality": float,
        "degraded_reason": str | None
      }
    """
```

```python
# segmentation_stub.py
def classify_terrain(raw_imagery: dict) -> dict:
    """
    반환:
      {"dominant_class": "open_field" | "forest" | "urban" | "mountain", "camera_confidence": float}
    """
```

```python
# yamnet_stub.py
def classify_acoustic(raw_acoustic: dict) -> dict:
    """
    반환:
      {"event_type": "gunshot" | "explosion" | "propeller" | "unknown", "yamnet_confidence": float}
    """
```

stub 로직: raw dict에 `mock_label`이나 힌트 필드가 있으면 그걸 그대로 반환. 없으면 안전한 기본값(`class=None`, `dominant_class="open_field"`, `event_type="unknown"`).

이 stub 함수들은 나중에 실제 모델로 교체될 때 시그니처와 반환 dict의 키가 동일해야 한다.

### 2) 새 채널 모듈 3개

`d4d_pipeline/layer_03_abstraction/`에 추가:

- `proximity_object.py`
  - `run(raw, previous_quality) -> ChannelOutput`
  - `yolo_stub.detect_proximity(raw["imagery"])` 호출
  - payload: `{class, weapon_shape, bearing_deg, closing, closure_rate_mps, degraded_reason}`
  - state: `weapon_shape=True` 또는 `closing=True and class ∈ {person, vehicle, drone}` 이면 anomaly, else normal
  - quality: stub이 반환한 quality 그대로

- `terrain_class.py`
  - GIS 조회를 mock (raw environment에 `dem_ref`가 있고 `mock_gis_class` 필드가 심겨 있으면 그걸 사용, 없으면 `"open_field"` 기본)
  - 카메라 결과와 GIS가 다르면 `camera_mismatch=True`
  - payload: `{dominant_class, source, gis_last_updated, camera_mismatch, exposure_score, risk_map_ref}`
  - `exposure_score`는 `dominant_class`별 하드코딩 상수 (`open_field=0.8, forest=0.2, urban=0.5, mountain=0.3`)
  - state: 항상 normal (terrain_class는 위협 신호가 아니라 배경정보). exposure_score는 04의 T6 배경노출도로 쓰인다.

- `acoustic_yamnet_secondary.py` — 별도 모듈로 두지 말고 기존 `acoustic_event.py`를 확장.
  - 기존 `acoustic_event.run`이 `detection_stage="threshold_only"` and `event_type="ambiguous"` 로 반환하면, 그때만 `yamnet_stub.classify_acoustic`을 호출해 결과로 덮어쓴다.
  - `detection_stage`를 `"yamnet_secondary"`로 갱신, `event_type`, `yamnet_confidence`를 payload에 추가.
  - 애매하지 않은 경우엔 stub을 호출하지 않는다 (트리거 기반 게이팅).

### 3) 오케스트레이터 갱신

`d4d_pipeline/layer_03_abstraction/run.py`가 이제 11채널을 모두 호출한다.

### 4) 테스트

`tests/layer_03_abstraction/test_ai_stub_channels.py`:

- `raw_t3.json`을 넣으면 `proximity_object.payload.weapon_shape=True`, `state="anomaly"`
- `raw_t4.json`을 넣으면 `proximity_object.payload.class="person"`, `closing=True`, `state="anomaly"`
- `raw_t7.json`을 넣으면 `terrain_class.payload.dominant_class` 값이 있고 `exposure_score`가 정의됨. `proximity_object.state="normal"` (T7은 지형이 위협)
- `terrain_class.state == "normal"` 항상 (배경 정보)

`tests/layer_03_abstraction/test_acoustic_secondary.py`:

- 명확한 총성 파형 (peak_db=110, rise_time_ms=1)이면 `detection_stage="threshold_only"`, YAMNet stub 미호출
- 애매한 파형 (peak_db=80, rise_time_ms=8)이고 mock_label에 "gunshot" 힌트를 심으면 `detection_stage="yamnet_secondary"`, `event_type="gunshot"`
- YAMNet stub의 호출 여부를 검증할 때 `unittest.mock.patch`로 spy하되, 실제 stub 함수는 결정론적으로 두라

`tests/layer_03_abstraction/test_pipeline_11_channels.py`:

- `run(raw_t3)` 반환의 `channels`가 11개, 모든 채널 이름이 아래와 정확히 일치:
  `["position_consistency", "link_status", "link_integrity", "encryption_status", "rf_spectrum", "mission_phase", "obstacle_proximity", "operational_margin", "proximity_object", "terrain_class", "acoustic_event"]`

## Acceptance Criteria

```bash
python3 -m pytest tests/layer_03_abstraction/ -v
```

- 모든 테스트 PASSED (step 3에서 만든 테스트 포함)
- 11채널 반환

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - `ai_stubs/`의 함수가 시그니처만 정의되고 실제 모델(torch/onnx 등)은 import 안 하는가?
   - `acoustic_event`의 YAMNet 승격이 게이팅(트리거 기반)으로만 작동하는가?
   - `terrain_class.state`가 항상 normal인가? (위협 채널이 아님)
3. 결과에 따라 `phases/0-mvp/index.json`의 step 4를 업데이트한다.

## 금지사항

- `torch`, `onnxruntime`, `tensorflow`, `opencv-python` 등을 pyproject.toml에 추가하지 마라. 이유: ADR-002 (stub 우선).
- YAMNet stub을 항상 호출하지 마라. 이유: 03 문서의 게이팅 원칙 위반 (SWaP 예산). 애매 케이스에만 승격.
- 실제 이미지·오디오 파일을 로드하지 마라. 이유: raw dict의 mock 힌트 필드만 소비.
- 03의 결정론 채널 로직(Step 3)을 수정하지 마라. 이유: 스코프 밖. `acoustic_event.py`만 예외적으로 확장한다.
