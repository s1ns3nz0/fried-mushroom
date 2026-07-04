# 03 Perception 실모델 데이터경로·계약 (ADR-002 언블록)

> 소스 오브 트루스는 `src/onboard/layer_03_abstraction/perception_input.py` 및 각 채널
> 모듈. 이 문서는 그 해설이다.

[ADR-002](../ADR.md)는 03 AI 채널(proximity_object=YOLO, terrain_class=segmentation,
acoustic=YAMNet 2차)을 **stub 우선**으로 두고 실모델을 후순위로 미뤘다. 이 문서는 그
실모델을 **실 픽셀/파형 없이는 막혀 있던 상태에서 언블록한** 데이터경로와 계약을 정리한다.
핵심 원칙: **opt-in + graceful fallback — 결정론 판정·골든 무변경(SCC-1)**.

## 왜 데이터경로가 먼저였나

`imagery`/`acoustic` 는 mock 힌트(`object_label`, `terrain_label`, `mock_label`,
`eo_frame_ref="buf://..."`)만 담아, 실 perception 모델이 소비할 **실 픽셀/파형이 없었다**.
그래서 (1) 실 프레임 소스를 담는 스키마 확장(하위호환), (2) 그것을 표준 입력으로 정규화하는
해석기, (3) 모델이 소비하는 인터페이스를 먼저 놓아야 했다.

## 데이터경로 (raw 02 → 표준 입력)

| 소스(선택, 하위호환) | 해석기 | 표준 입력 인터페이스 |
|---|---|---|
| `imagery.eo_frame` = `{kind, fmt, width, height, channels, bytes_b64\|path, meta}` | `resolve_frame(imagery)` | `PerceptionFrame` |
| ⏳ `acoustic.waveform` = `{fmt, sample_rate, channels, bytes_b64\|path, meta}` | `resolve_audio(acoustic)` *(후속 #375)* | `AudioClip` *(후속 #375)* |

- 실 소스가 **없으면** 해석기는 `None` 을 반환 → 호출 채널이 **기존 mock 힌트로 폴백**
  (골든·결정론 판정 무변경). `has_real_frame` 로 mock ref 와 구분한다(`has_real_audio` 는 ⏳ 후속 #375).
- decode 는 무거운 의존(cv2/PIL/numpy)이라 **lazy** — 있으면 `array`/`samples` 를 채우고,
  없으면 `None` + `raw_bytes`(치수/포맷 동반)로 넘겨 **모델이 자체 decode** 한다.

### PerceptionFrame / AudioClip (실모델이 소비하는 계약)

```jsonc
PerceptionFrame = { kind, fmt, width, height, channels, raw_bytes, array|null, meta }
AudioClip       = { fmt, sample_rate, channels, raw_bytes, samples|null, meta }
```

## 모델 레이어 (opt-in + fallback)

실모델은 `perception_model.py`(imagery)·`acoustic_model.py`(음향)에 둔다:

- **opt-in**: `ONBOARD_PERCEPTION_MODEL=1` 환경변수(NLP `GCS_NLP_MODEL` 선례). 기본은 stub.
- **lazy import + broad except**: ultralytics YOLO / tensorflow_hub YAMNet 을 필요 시에만
  로딩. 미설치·가중치 부재·`array/samples=None`·추론 실패 등 **어떤 실패든 `None` 반환**
  → 채널이 stub 힌트로 하향(크래시 0).
- **파리티**: 실모델 반환은 대응 stub 과 **동일 키셋**이어야 한다(판정 로직 무변경):
  - proximity: `{class, weapon_shape, bearing_deg, closing, closure_rate_mps, quality, degraded_reason}`
  - terrain: `{dominant_class, camera_confidence, optimal_terrain_bearing_deg, lowest_exposure_bearing_deg}`
  - acoustic: `{event_type, yamnet_confidence}` (event_type ∈ gunshot/explosion/propeller/unknown)
- terrain 은 **씬-segmentation** 필요(COCO instance-seg 은 지형 라벨 없음): `ONBOARD_TERRAIN_SEG_MODEL`
  로 ADE20K 계열 지정. 지형 클래스로 매핑 안 되는 라벨은 `None`(폴백, 오보 방지).

## 채널 배선 패턴 (공통)

```python
det = None
if <model>.enabled() and has_real_frame(imagery):      # opt-in + 실 프레임
    frame = resolve_frame(imagery)
    if frame is not None:
        det = <model>.detect_*(frame)                  # 실패 시 None
det = det or <stub>(imagery)                            # 폴백 — 판정 로직 무변경
```

## SCC-1 / 하위호환

- perception 은 03 **AI 채널(병렬 참고)** — 결정론 채널 판정·`RAC_MATRIX` 와 무관.
- mock 경로·기존 골든 전부 무변경. CI 기본은 모델 미설치 → **폴백 경로**(테스트는 importorskip/env 게이트).

## 구현 PR

| 축 | PR |
|---|---|
| imagery 데이터경로(`PerceptionFrame`/`resolve_frame`) | #357 (#355) |
| YOLO/segmentation 모델 | #368 (#364) |
| acoustic(YAMNet) 데이터경로·모델(`AudioClip`/`resolve_audio`) | (perception 후속) |
