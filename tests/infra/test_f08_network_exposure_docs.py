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
    """infra/log/README.md 가 포트 번호와 인증/무인증 트레이드오프를 언급해야 한다."""
    text = _LOG_README.read_text(encoding="utf-8")

    port_mentioned = any(p in text for p in ("8400", "8500", "8181"))
    assert port_mentioned, (
        "infra/log/README.md: 포트 번호(8400/8500/8181) 언급 없음 — 노출 범위 명시 필요"
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
    """docs/security/devsecops-audit.md F-08 항목에 결정 참조(#275 또는 README 링크)가 있어야 한다."""
    text = _AUDIT_DOC.read_text(encoding="utf-8")

    # F-08 섹션이 존재해야 함
    assert "F-08" in text, "devsecops-audit.md 에 F-08 항목 없음"

    # F-08 이후 텍스트에서 결정 참조 확인
    f08_idx = text.index("F-08")
    f08_section = text[f08_idx: f08_idx + 600]
    has_ref = bool(
        re.search(r"#275|README|결정|addressed|완료|documented|명시됨", f08_section, re.IGNORECASE)
    )
    assert has_ref, (
        "devsecops-audit.md F-08 항목에 결정 참조(#275 또는 README 링크) 없음"
    )
