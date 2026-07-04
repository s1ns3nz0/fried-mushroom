"""F-08 네트워크 노출 트레이드오프 문서화 회귀 가드 (#275).

DevSecOps 감사 F-08(MEDIUM) — 8400/8500/8181 무인증 공개 노출이
의도적 트레이드오프로 문서화돼 있는지 검증.

문서화 기준:
- infra/log/README.md 에 보안/공개 노출 섹션이 존재
- F-08 키워드 또는 포트 번호(8400/8500/8181) + 인증/트레이드오프 언급
- docs/security/devsecops-audit.md F-08 항목에 결정 참조가 추가됨

src/onboard, src/gcs, infra/sim 무접촉.
"""

import pathlib
import re

_REPO = pathlib.Path(__file__).resolve().parents[2]
_LOG_README = _REPO / "infra" / "log" / "README.md"
_AUDIT_DOC = _REPO / "docs" / "security" / "devsecops-audit.md"


def test_log_readme_has_security_section():
    """infra/log/README.md 에 보안/공개 노출 섹션이 존재해야 한다."""
    text = _LOG_README.read_text(encoding="utf-8")
    has_section = bool(
        re.search(r"##.*보안|##.*security|##.*노출|##.*exposure", text, re.IGNORECASE)
    )
    assert has_section, (
        "infra/log/README.md: 보안 섹션(## 보안, ## Security, ## 네트워크 노출 등) 없음\n"
        "  → F-08: 무인증 공개 노출을 의도적 트레이드오프로 명시 필요"
    )


def test_log_readme_mentions_ports_and_auth_tradeoff():
    """infra/log/README.md 가 3포트 전체와 인증/무인증 트레이드오프를 언급해야 한다.

    #280: any(8400/8500/8181) → 포트별 개별 assert — 1개 누락도 탐지.
    F-08 은 3포트 전체 노출 문서화가 목적이므로 all 검증 필요.
    """
    text = _LOG_README.read_text(encoding="utf-8")

    for port in ("8400", "8500", "8181"):
        assert port in text, (
            f"infra/log/README.md: 포트 {port} 언급 없음 — F-08 3포트 전체 노출 명시 필요"
        )

    auth_tradeoff = bool(
        re.search(
            r"무인증|인증 없|unauthenticated|no.auth|auth.*없|api.?key|트레이드오프|trade.?off|의도적|intentional",
            text,
            re.IGNORECASE,
        )
    )
    assert auth_tradeoff, (
        "infra/log/README.md: 인증 없는 공개 접근의 의도적 트레이드오프 언급 없음\n"
        "  → F-08 결정(데모/운용 목적 공개 또는 하드닝 경로) 명시 필요"
    )


def test_log_readme_documents_hardening_path():
    """infra/log/README.md 에 최소 하드닝 경로(SG 좁히기/API key/CloudFront 등)가 언급돼야 한다."""
    text = _LOG_README.read_text(encoding="utf-8")
    has_hardening = bool(
        re.search(
            r"cidr|api.?key|mTLS|cloudfront|sg.*좁|ingress.*limit|allowlist|허용.*ip|운영.*환경",
            text,
            re.IGNORECASE,
        )
    )
    assert has_hardening, (
        "infra/log/README.md: 하드닝 경로 언급 없음 — SG CIDR 축소, API key, CloudFront 뒤 배치 등 권고안 필요"
    )


def test_audit_doc_f08_references_decision():
    """docs/security/devsecops-audit.md 후속 조치 테이블의 F-08 행에 결정 참조(#275)가 있어야 한다.

    P2 수정: text.index("F-08") 는 findings 테이블 첫 출현을 잡으므로 후속 행을
    검증하지 못함. 후속 조치 섹션 내에서 F-08 행을 직접 탐색한다.
    """
    text = _AUDIT_DOC.read_text(encoding="utf-8")

    # 후속 조치 섹션 경계 확인
    assert "후속 조치" in text, "devsecops-audit.md 에 후속 조치 섹션 없음"
    followup_idx = text.index("후속 조치")
    followup_section = text[followup_idx:]

    # 후속 조치 섹션 내 F-08 행 탐색 — `| ... | F-08 |` 패턴
    f08_row_match = re.search(r"\|[^\n]*F-08[^\n]*\n", followup_section)
    assert f08_row_match, (
        "devsecops-audit.md 후속 조치 섹션에 F-08 행(| ... | F-08 |) 없음"
    )

    # 해당 행에 #275 결정 참조가 있어야 함
    f08_row = f08_row_match.group(0)
    assert "#275" in f08_row, (
        f"후속 조치 F-08 행에 #275 결정 참조 없음:\n  {f08_row.strip()}\n"
        "  → PR #275 결정 참조를 해당 행에 추가 필요"
    )
