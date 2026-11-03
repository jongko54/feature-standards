# 재사용·배포·AI 적용 고도화

사용자가 승인한 남은 작업 6개를 진행한다. 인증 HTTP 계약·DB 스키마를 유지하며 npm API 동작을 바꾸지 않는다. MFA/RBAC/OAuth와 실제 운영 SMTP·클러스터 배포는 이번 범위가 아니다.

## 병렬 구현

1. `packages/create-feature-auth/`, `docs/create-feature-auth.md`: 명시적 source checkout과 새 대상 디렉터리에서 Python·Go·Java·Rust의 기존 공개 인증 패키지를 연결하는 설치 CLI. 프로필 v1/v2/v3 선택, 안전한 설정 예시, 보호 API·실행/검증 명령을 제공한다. 기존 파일·사용자 DB를 덮어쓰거나 자동 이관하지 않는다. 인증 구현 복제는 하지 않는다. 각 스택의 생성 결과를 빌드·실행한다.
2. `tests/consumer_profiles.py`, `examples/consumer-python-react/` 및 필요한 소비 예제 범위: 별도 앱 4종의 PostgreSQL v2/v3, 보호 API·세션 폐기·계정 생명주기와 실제 소비 화면 검증. 전용 임시 DB·분리된 프런트 포트만 사용한다. 공유 명세와 참조 서버 검사 통과를 소비 앱 통과로 대신하지 않는다.
3. `tools/auth_eval.py`, `tests/test_auth_eval.py`, `evals/auth/`, `skills/integrate-auth/`, `AGENTS.md`: 알려진 스택·v1 작업에서 문맥 탐색을 줄이고 재현 가능한 모델 설정·반복 평가·집계를 지원한다. 부모가 전체 코드 freeze 후 동일 소스로 실행한다. 결과가 개선을 입증하지 못하면 그대로 기록한다.

## 부모 담당 통합·원격 작업

- npm의 OIDC trusted publishing 워크플로와 패키지/버전/저장소 검증을 준비한다. 공식 지원 방식으로 계정 연결을 수행하고, 실제 신뢰 관계 및 실행 여부를 확인한다. 장기 토큰을 추가하지 않는다.
- Python wheel/sdist, Java 일반 JAR, Rust crate, Go 모듈의 배포 조건·설치 경로·산출물을 검증한다. Go는 버전 태그와 원격 설치까지 수행한다. 외부 레지스트리 계정·namespace 권한이 없으면 실제 게시 완료로 표시하지 않는다.
- 공개 저장소의 취약점 비공개 제보 기능과 정책을 정리하고, 기여 안내·과거 계획 상태를 현재 사실과 맞춘다. 대상 저장소와 계정 권한을 확인한 뒤 설정한다.
- manifest·CI·루트 README와 릴리스 기록을 통합한다. 기존 영어 README 형식을 유지한다.

## 검증과 완료 기준

- 생성 CLI의 경로/덮어쓰기 거절, 프로필 선택·의존성 설정과 네 소비 앱 실제 HTTP를 확인한다.
- v2/v3 소비 검사·브라우저·기존 공통 HTTP·React build 및 필요한 자체 테스트를 실행한다. 명령과 실제 범위·skip을 기록한다.
- 평가 도구와 메타데이터 회귀·lint·워크플로 구문/템플릿 일치를 확인한다. 모델 평가는 실제 trace·시간·토큰·완료 상태로 측정한다.
- Git 커밋·푸시와 원격 CI, 레지스트리 게시 및 설치를 별도로 확인한다. 외부 인증/설정이 필요하면 검증한 산출물·정확한 다음 동작을 제시한 뒤 해당 단계만 사용자에게 요청한다.

롤백은 이 작업의 소스 커밋을 되돌리는 방식이다. 기존 데이터 이관은 추가하지 않는다. 공개 레지스트리의 이미 게시된 버전은 덮어쓰거나 자동으로 unpublish하지 않는다.

## 실행 결과

- CLI 안전 검사7개·4개 생성 앱의 빌드/실제 HTTP와 npm tarball 설치를 확인했다. v2/v3 선택도 가능하며 CLI check 자체는 메모리 v1이다.
- 독립 소비 matrix8개 DB 조합·Chromium28개를 로컬과 구현 CI에서 실행했다. 기존 v1 공통 HTTP76개·브라우저32개도 로컬 통과했다.
- 반복 모델 평가24/24 통합에 성공했다. 효율은 혼합 결과이며 [전용 보고서](../../validation-ai-paired-2026-11-03.md)에 수치·한계·소스 고정 범위를 기록한다.
- 구현 커밋eff0d9d 전체 main CI와 npm/Python artifact 전용 workflow가 성공했다. Go v0.1.0 태그·인증 없는 공개 proxy·새 모듈 설치·race HTTP검사를 확인했다. Python/Java/Rust 산출물은 로컬 검증했고 실제 레지스트리 게시와 구분했다.
- GitHub 비공개 취약점 제보를 활성화하고 정책·기여 안내·역사적 계획 상태를 정리했다.
- 남은 외부 작업: npm 본인인증 만료로 trusted publisher 연결·새 CLI npm 게시 미완료, PyPI pending publisher/Central namespace·서명·token/crates.io 계정 설정 필요. 장기 token이나 새 서명 키를 추가하지 않았다.
