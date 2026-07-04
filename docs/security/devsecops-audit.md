# CI/CD 파이프라인 DevSecOps 컴플라이언스 감사 (#228)

## 1. 감사 개요

| 항목 | 내용 |
|---|---|
| 감사 일자 | 2026-07-04 |
| 감사 범위 | GitHub Actions 워크플로, Terraform IaC, 배포 스크립트/Dockerfile — **코드/설정 열람 및 GitHub API 조회만 수행. 코드 변경 없음.** |
| 기준 브랜치 | `origin/main` (HEAD `041ed60`) |
| 배경 | #208(커밋 `0990586`) 배포 보안 회귀 → #221(커밋 `f150853`) 즉시 remediation. 본 감사는 **remediation 이후 현 main 상태**를 기준으로 하되, 회귀가 가능했던 프로세스 갭을 별도로 짚는다. |
| 기준 표준 | NIST SP 800-218 (SSDF), DoD DevSecOps 참조 아키텍처, NIST SP 800-204D (공급망/C-SCRM) |
| 저장소 가시성 | **PUBLIC** (`s1ns3nz0/fried-mushroom`, `gh repo view` 확인) — 공급망/OIDC 관련 심각도 판단에 반영 |

### 감사 대상 파일
- `.github/workflows/ci.yml`, `codeql.yml`, `deploy-dashboard.yml`, `deploy-log.yml`
- `infra/terraform/*.tf` (iam.tf, ecr.tf, network.tf, instance_profile.tf, outputs.tf, data.tf, cloudfront_dns.tf, ground.tf, dashboard.tf, security.tf, uav.tf, variables.tf, versions.tf, providers.tf) + `README.md` + `terraform.tfvars.example`
- `infra/log/Dockerfile`, `infra/log/.dockerignore`, `infra/log/requirements.txt`, `infra/dashboard/requirements.txt`
- 참고: `.gitignore`, `pyproject.toml`, 저장소 브랜치 보호/환경/룰셋 설정(GitHub API), 커밋 히스토리(`0990586`, `f150853`)

### 감사 방법
- 각 파일 전체를 정독. GitHub API(`gh api repos/.../branches/main/protection`, `.../environments`, `.../rulesets`)로 정책 강제 여부를 실측. `git show`로 #208/#221 커밋 diff를 직접 대조.

---

## 2. Findings

| ID | 심각도 | 표준 매핑 | 파일:라인 | 설명 | 권고 조치 |
|---|---|---|---|---|---|
| F-01 | **HIGH** | DoD DevSecOps 파이프라인 게이트 / SSDF PS.1, PW.4 | `README.md:125-128` (정책) vs. 저장소 설정(강제 부재) | README는 "리뷰어 1명 approve 필요 + CI(pytest) 통과 필수"를 `main` 머지 조건으로 문서화하지만, `gh api repos/{owner}/{repo}/branches/main/protection` → `404 Not Found`, `gh api repos/{owner}/{repo}/rulesets` → `[]` 로 실측 확인. 즉 이 정책은 GitHub 상 **기술적으로 전혀 강제되지 않는다** — 누구든 `main`에 직접 push하면 PR 리뷰·CI·CodeQL을 모두 우회할 수 있다. #208(`0990586`)과 #221(`f150853`) 자체는 실제로 PR(#208, #221)을 거쳐 병합됐음을 `gh pr list`로 확인했으나(이번 회귀가 direct-push로 발생한 것은 아님), 이 통제가 없다는 사실 자체가 "감사 게이트 부재로 유사 회귀가 재발 가능"한 근본 프로세스 갭이다. | `main`에 branch protection rule(또는 ruleset) 추가: required PR + 1 approval, required status check(`ci`, `codeql`), force-push/삭제 금지. 별도 이슈로 분리. |
| F-02 | **HIGH** | DoD DevSecOps OIDC 신뢰범위 / SSDF PW.4(최소권한) | `infra/terraform/iam.tf:26-31` (특히 `values = ["repo:${var.github_org}/${var.github_repo}:*"]`, L29) | OIDC 신뢰정책의 `sub` 클레임이 `repo:{org}/{repo}:*` 와일드카드로, `refs/heads/main`이 아닌 **저장소 내 임의 브랜치/태그/PR ref**에서 실행되는 워크플로도 `id-token: write` 권한만 있으면 `fried-mushroom-uav-deploy-dev` role을 assume할 수 있다. 저장소가 PUBLIC이고(`gh repo view` 확인), GitHub Environment가 0개(`gh api .../environments` → `{"total_count":0}`)라 이 role에 대한 추가 승인 게이트도 없다. #208 커밋 메시지 자체가 "하드코딩값이 안전한 이유"로 이 와일드카드 조건을 인용했는데(`git show 0990586`), 이는 신뢰 범위가 이미 넓다는 방증이다. deploy 워크플로 자체는 `branches: [main]` 트리거로 제한돼 있으나, IAM 신뢰정책은 그 트리거와 무관하게 독립적으로 넓게 열려 있다. | `sub` 조건을 `repo:{org}/{repo}:ref:refs/heads/main` (또는 environment 기반 `repo:{org}/{repo}:environment:prod`)으로 좁힌다. 별도 이슈로 분리. |
| F-03 | MEDIUM | DoD DevSecOps 배포 승인 통제 | `.github/workflows/deploy-dashboard.yml:27`, `deploy-log.yml:28` | 배포 job은 `if: vars.DEPLOY_ENABLED == 'true'` 로만 게이트된다(레포 Actions variable — 편집에 admin/settings 권한 필요, 일반 write 콜라보레이터는 토글 불가). GitHub Environment(수동 승인 리뷰어)는 설정돼 있지 않음(`gh api .../environments` → 0건). #221이 도입한 `DEPLOY_ENABLED` opt-in은 #208의 "무조건 자동배포" 회귀는 막지만, "사람이 명시적으로 승인"하는 이중 게이트는 아니다. | `environment: production` + required reviewers를 deploy job에 추가. 별도 이슈로 분리. |
| F-04 | MEDIUM | SSDF PW.4(최소권한) / SP 800-204D | `infra/terraform/iam.tf:79-87`(SsmSendCommand), `:89-94`(DescribeInstances), `:96-101`(CloudFrontInvalidate) | 세 statement 모두 `resources = ["*"]`. 특히 `ssm:SendCommand`가 계정 내 임의 EC2 인스턴스를 대상으로 발동 가능(현재는 코드가 `GROUND_INSTANCE_ID` 하나만 사용하지만 IAM 정책이 이를 강제하지 않음). `DashboardS3Deploy`/`EcrPush` statement는 이미 리소스 ARN으로 정확히 스코프돼 있어 대조적이다(양호 사례). | `ssm:SendCommand`는 태그 조건(`ssm:resourceTag/Name`) 또는 인스턴스 ARN으로, `cloudfront:CreateInvalidation`은 distribution ARN으로 스코프. 별도 이슈로 분리. |
| F-05 | MEDIUM | SP 800-204D(아티팩트 무결성) / SSDF PW.4 | `infra/terraform/ecr.tf:10` (`image_tag_mutability = "MUTABLE"`) | 3개 ECR repo(uav/ground/log) 모두 태그 변경 가능. `deploy-log.yml:47`이 `:${github.sha}`와 `:latest` 두 태그로 push하는데, mutable이면 동일 SHA 태그도 사후 재작성/덮어쓰기가 가능해 "이 SHA=이 이미지"라는 추적성이 보장되지 않는다. `scan_on_push = true`(ecr.tf:14)는 이미 적용돼 있어 취약점 스캔 자체는 준수. | `image_tag_mutability = "IMMUTABLE"`로 변경(SHA 태그 한정 또는 전체). 별도 이슈로 분리. |
| F-06 | MEDIUM | SP 800-204D(컨테이너 base image 핀) | `infra/log/Dockerfile:11` (`FROM --platform=linux/amd64 python:3.11-slim`) | base image가 다이제스트가 아닌 가변 태그(`3.11-slim`)로 고정돼, 업스트림이 동일 태그를 재푸시하면 빌드 입력이 조용히 바뀐다. GitHub Actions는 SHA 핀(#122)이 이미 적용돼 있어 대조적. | `python:3.11-slim@sha256:<digest>` 로 다이제스트 고정. 별도 이슈로 분리. |
| F-07 | MEDIUM | SP 800-204D(의존성 고정) | `infra/log/requirements.txt:9-15`, `infra/dashboard/requirements.txt:1-2` | `fastapi`, `uvicorn[standard]`, `pydantic`, `httpx` 모두 버전 핀 없음 — 빌드 시점마다 다른 버전(및 전이 의존성 그래프)이 설치될 수 있어 재현 가능 빌드가 보장되지 않는다. 참고로 온보드 코어(`pyproject.toml`)는 표준 라이브러리만 사용해 이 문제가 없음(CLAUDE.md 원칙 준수, ✅). | `pip freeze` 또는 `==` 버전 핀 (+ 가능하면 `pip-compile`/hash 고정)으로 전환. 별도 이슈로 분리. |
| F-08 | MEDIUM | DoD DevSecOps 네트워크 최소노출 | `infra/terraform/security.tf` ground SG (`ground_app_port`/`log_server_port`/`raw_log_port` ingress, `cidr_blocks = ["0.0.0.0/0"]`) + `infra/log/log_server.py`(374줄)·`main.py`(27줄) | 8400/8500/8181 포트가 전 인터넷에 개방되고, 두 FastAPI 서비스 소스에 `auth`/`token`/`api_key`/`secret` 키워드가 전혀 없음(grep 확인) — 즉 인증 없이 공개 접근 가능. 대시보드/로그 스트림을 공개 시연 목적으로 의도한 설계일 수 있으나, 그렇다면 최소한 문서화된 의도적 트레이드오프로 명시할 필요가 있다. | 필요 시 CloudFront/ALB 뒤에 두거나 API key/mTLS 도입, 혹은 의도적 공개 설계임을 README에 명시. 별도 이슈로 분리(애플리케이션 레이어 변경 필요하므로 이 감사에서 직접 수정하지 않음). |
| F-09 | MEDIUM | SSDF PW.4(정보노출 방지) / OPSEC | `git show 0990586` (`.github/workflows/deploy-dashboard.yml`, `deploy-log.yml` 당시 diff) | #208 커밋이 AWS 계정 ID, 배포 role ARN, S3 버킷 전체 이름, CloudFront distribution ID, EC2 instance ID를 폴백 리터럴로 하드코딩했다. #221이 **현재 파일에서는** 완전히 제거했지만(확인됨: 현재 `deploy-dashboard.yml`/`deploy-log.yml`에 리터럴 없음, `secrets.*`/`vars.*` 참조만 존재), 저장소가 PUBLIC이므로 커밋 `0990586`을 통해 이 값들이 **git history에 영구 잔존**하며 누구나 조회 가능하다. #221 커밋 메시지가 "AWS 리소스 검토/로테이션 권장"을 명시했으나, 완료 여부는 이 저장소 감사 범위(AWS 콘솔 접근 불가) 밖이라 확인 불가. | AWS 측에서 해당 role ARN 신뢰정책 재검토, 버킷/CloudFront/인스턴스 교체 필요 여부 판단(자격증명이 아닌 리소스 식별자이므로 즉시 rotation 필수는 아니나 검토 필요). 별도 이슈로 분리(AWS 측 조치, 코드 변경 아님). |
| F-10 | LOW | SSDF PW.4(안전한 기본값) | `infra/terraform/variables.tf:31-35`, `terraform.tfvars.example:15` | `allowed_ssh_cidr` 기본값이 `"0.0.0.0/0"` — `variables.tf:32`에 "0.0.0.0/0 지양" 주석까지 있으면서 기본값 자체는 그대로 둠. `README.md:75`도 "0.0.0.0/0으로 두지 말 것"이라 재차 경고하지만 강제 수단(예: `validation` block)은 없음. | `variable "allowed_ssh_cidr"`에 `validation` block 추가해 `0.0.0.0/0` 지정 시 plan 단계에서 오류 처리(문서 경고만으로는 실수 방지 불충분). 별도 이슈로 분리. |
| F-11 | LOW | SSDF PW.4(최소 자격증명 노출) | `deploy-dashboard.yml:29`, `deploy-log.yml:30` | 두 워크플로의 `actions/checkout` 스텝에 `persist-credentials: false`가 없음(반면 `ci.yml:27`, `codeql.yml:28`은 명시적으로 false). job이 git push를 필요로 하지 않는데도 `GITHUB_TOKEN`이 로컬 git config에 남는다. | `persist-credentials: false` 추가해 4개 워크플로 일관성 확보. 별도 이슈로 분리. |
| F-12 | LOW | SSDF PS.3/PW.4(provenance) / SP 800-204D | `deploy-log.yml:41-49`, `deploy-dashboard.yml:36-46` | ECR push나 S3 sync 어디에도 아티팩트 서명(cosign 등)이나 SLSA provenance attestation 단계가 없다. 빌드-푸시가 동일 job 내에서 일어나 외부 변조 위험은 낮지만, 배포 대상(EC2/S3)이 나중에 이미지/자산의 출처를 검증할 방법이 없다. | `cosign sign`/`attest` 단계 추가 검토(우선순위 낮음 — MVP 스코프 감안). 별도 이슈로 분리. |
| F-13 | LOW | SP 800-204D(IaC 재현성) | `.gitignore:29` (`infra/terraform/.terraform.lock.hcl` 제외) vs. `versions.tf:4-8` (`version = "~> 5.0"`) | provider 버전을 정확히 고정하는 lock 파일이 커밋에서 제외되고, 제약도 `~> 5.0` 범위(고정 아님)라 `terraform init` 시점마다 다른 `hashicorp/aws` provider 빌드를 받을 수 있다. `infra/terraform/README.md:3-4`가 명시하듯 apply는 사용자가 본인 계정에서 수동 실행하는 구조라(CI에서 자동 apply 없음) 실제 악용 난이도는 낮음. | `.terraform.lock.hcl`을 커밋 대상으로 전환(사용자별 로컬 재생성 방식 유지할지 팀 판단 필요). 별도 이슈로 분리. |
| F-14 | LOW | 문서 정확성 / DoD DevSecOps 파이프라인 완결성 | `infra/terraform/README.md:65-69`(`terraform.yml`/`deploy-uav.yml`/`deploy-ground.yml` 언급) vs. 실제 `.github/workflows/`(`ci.yml`/`codeql.yml`/`deploy-dashboard.yml`/`deploy-log.yml`만 존재); `variables.tf:79-83`(`github_repo` 기본값 `"fried-mushroom-uav"`) vs. `terraform.tfvars.example:26`(`"fried-mushroom"`, 실제 저장소명과 일치) | README가 존재하지 않는 워크플로 3개를 문서화하고 있어(구 리포지토리명 `fried-mushroom-uav` 시절 문서로 추정) 감사/신규 인력이 실제 파이프라인 구성을 오인할 수 있다. 부수적으로 `terraform plan`/`fmt`/`validate`를 CI에서 검증하는 워크플로 자체가 없음(설계상 수동 apply이므로 BLOCKER는 아님). `variables.tf` 기본값도 저장소 리네임 이전 값으로 드리프트. | README를 실제 워크플로 4개 기준으로 갱신, `github_repo` 기본값을 현재 저장소명으로 정정. 별도 이슈로 분리. |

**BLOCKER: 0건.** 현재 `origin/main`에서 즉시 악용 가능하거나 배포를 차단해야 할 수준의 결함은 발견되지 않았다.

---

## 3. 요약

| 심각도 | 건수 |
|---|---|
| BLOCKER | 0 |
| HIGH | 2 (F-01, F-02) |
| MEDIUM | 7 (F-03 ~ F-09) |
| LOW | 5 (F-10 ~ F-14) |
| **합계** | **14** |

### ✅ 이미 준수 중인 항목 (정직하게 기록)
- 4개 워크플로 전부 action이 **커밋 SHA로 고정**(가변 태그 없음) — #122 정책 적용 확인 (`ci.yml:25,29`, `codeql.yml:26,30,34`, `deploy-dashboard.yml:29,31`, `deploy-log.yml:30,32,39`).
- `GITHUB_TOKEN` 권한이 워크플로 레벨에서 `contents: read`로 최소화되고, 필요한 job에서만 elevate(`codeql.yml` security-events:write, deploy 워크플로 id-token:write) — 최소권한 원칙 준수.
- CodeQL SAST가 push/PR/주간 스케줄로 구성되어 있음(`codeql.yml`).
- CI(pytest) 워크플로가 존재하고 15분 타임아웃으로 제한됨(`ci.yml`).
- **#208/#221 remediation은 현재 main 기준으로 완전히 반영됨**: `deploy-dashboard.yml`/`deploy-log.yml`에 하드코딩 폴백 리터럴이 전혀 없고(직접 정독 확인), `vars.DEPLOY_ENABLED == 'true'` opt-in 게이트가 두 워크플로 모두에 존재하며, CloudFront invalidation/SSM 재기동 스텝의 조건 가드(`if: vars.X != ''`)도 복원돼 있다.
- OIDC(GitHub Actions ↔ AWS)로 배포하며 장기 액세스 키를 저장소에 두지 않음(`iam.tf`).
- 두 EC2 인스턴스 모두 IMDSv2 강제(`http_tokens = "required"`, `uav.tf:19`, `ground.tf:31`)와 루트 볼륨 암호화(`encrypted = true`, `uav.tf:25`, `ground.tf:37`) 적용.
- ECR: `scan_on_push = true`(취약점 스캐닝, `ecr.tf:14`) + lifecycle policy로 이미지 10개 초과분 자동 정리(`ecr.tf:21-37`).
- CloudFront 사용 시 S3는 OAC 전용으로 잠기고 `enable_cloudfront=true`일 때 public access block이 모두 활성화(`dashboard.tf:25-31, 49-67`) — 퍼블릭/CDN 두 모드 모두 설계가 일관됨.
- AMI는 `data aws_ami` lookup으로 하드코딩 없이 해석(`data.tf:1-20`), 계정 ID·액세스키가 코드에 없음(README 명시 및 실측 확인).
- `.gitignore`가 `*.tfstate`, `terraform.tfvars`를 이미 제외 — 상태/변수 파일 커밋 사고 없음.
- 온보드 코어 파이프라인(`pyproject.toml`)은 서드파티 의존성이 전혀 없어(표준 라이브러리만 사용) 이 축에서는 공급망 표면 자체가 없음(CLAUDE.md 원칙과 일치).

### #208 → #221 remediation 상태 (히스토리 왜곡 없이 반영)
1. #208(`0990586`, 2026-07-04 21:30)이 "secret/var 미설정 시에도 배포되도록" AWS 계정ID·role ARN·버킷명·CloudFront ID·EC2 instance ID를 워크플로에 평문 폴백으로 내장 + 조건 가드(`if:`) 제거 → 해당 배포 경로(`infra/dashboard/static/**`, `infra/log/**`)를 건드리는 main 머지마다 실 AWS 배포가 발화하는 회귀 도입(deploy 워크플로의 `paths` 필터 범위 내).
2. #221(`f150853`, 2026-07-04 21:42, 12분 뒤)이 즉시 되돌림: `DEPLOY_ENABLED` opt-in 게이트 추가, 하드코딩 폴백 전부 제거(secrets/vars만 사용), 조건 가드 복원. 커밋 메시지에 "하드코딩됐던 식별자는 git history에 잔존 — 노출 간주, AWS 리소스 검토/로테이션 권장" 명시.
3. **#208이 도입했던 하드코딩 폴백 회귀는 #221로 완전히 제거됐다** — 두 워크플로 파일을 직접 정독해 하드코딩 리터럴 부재를 확인했다. (단 이 판정은 하드코딩 회귀 재발 여부에 한정되며, 파이프라인 전반의 F-01·F-02(HIGH) 등 구조적 갭은 아래 findings대로 여전히 유효하다.)
4. 잔여 갭: (a) 이 회귀가 애초에 "PR은 거쳤으나 branch protection 없이도 머지 가능한" 환경에서 일어났다는 점(F-01), (b) `0990586`에 노출된 리소스 식별자가 public repo history에 영구 잔존하며 rotation 완료 여부를 저장소만으로는 확인할 수 없다는 점(F-09) — 이 두 가지가 "#208류 회귀가 재발 가능한" 근본 원인으로 남아있다.

---

## 4. 후속 조치 이슈 후보 (코드 수정 필요 — 이 감사에서는 직접 고치지 않음)

| # | 제목 | 관련 finding |
|---|---|---|
| 1 | `main` 브랜치 보호 규칙(1 approval + required status check) 설정 | F-01 |
| 2 | OIDC 신뢰정책 `sub` 클레임을 `refs/heads/main`(또는 environment)으로 스코프 축소 | F-02 |
| 3 | 배포 job에 GitHub Environment + 필수 리뷰어 게이트 추가 | F-03 |
| 4 | IAM deploy role의 `ssm:SendCommand`/`cloudfront:CreateInvalidation` 리소스 스코프 축소 | F-04 |
| 5 | ECR `image_tag_mutability`를 `IMMUTABLE`로 전환 | F-05 |
| 6 | `infra/log/Dockerfile` base image 다이제스트 고정 | F-06 |
| 7 | `infra/log/requirements.txt`, `infra/dashboard/requirements.txt` 버전 핀 | F-07 |
| 8 | ground 서비스(8400/8500/8181) 인증 방안 또는 의도적 공개 설계 문서화 — ✅ 결정 명시됨(#275): `infra/log/README.md` "보안 / 네트워크 노출" 섹션, 데모 전용 의도적 공개 + 운영 하드닝 경로 기록 | F-08 |
| 9 | `0990586`에 노출된 AWS 리소스(role ARN/버킷/CloudFront/인스턴스) rotation 필요 여부 AWS 측 검토 | F-09 |
| 10 | `allowed_ssh_cidr` variable에 `0.0.0.0/0` 금지 validation 추가 | F-10 |
| 11 | deploy 워크플로 checkout에 `persist-credentials: false` 추가 | F-11 |
| 12 | 아티팩트 서명/provenance(cosign/SLSA) 도입 검토 | F-12 |
| 13 | `.terraform.lock.hcl` 커밋 전환 검토 | F-13 |
| 14 | `infra/terraform/README.md` 워크플로 목록/`github_repo` 기본값 갱신 | F-14 |

총 **14건**의 후속 조치 후보. 본 감사(#228)는 이 중 어느 것도 직접 수정하지 않았다(`git diff --stat`으로 확인 가능 — `docs/security/devsecops-audit.md` 1개 파일만 추가).
