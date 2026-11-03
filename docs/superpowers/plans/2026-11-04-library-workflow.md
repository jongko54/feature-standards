# 라이브러리 적용·생성·프로필 검증 고도화

## 목표와 범위

사용자가 승인한 세 보완점을 진행한다: Python·Java·Rust의 독립 설치/배포, 생성 앱의 선택 프로필 검증, 대표 CLI에서 선택 → 생성 → 검증 연결. 기존 인증 계약·DB 스키마·React API를 유지한다. 새 인증 기능·React UI·실제 운영 SMTP·기존 사용자 DB 이관은 추가하지 않는다.

## 작업 분담과 인터페이스

1. 생성기 담당: `packages/create-feature-auth/**`, `docs/create-feature-auth.md`. 버전 `0.2.0`. v1은 메모리 HTTP 검사, v2/v3는 명시적인 `FEATURE_STANDARDS_TEST_DATABASE_URL`을 검사한 후 별도의 UUID 테스트 DB에서 해당 계약을 확인한다. 일반 `AUTH_DATABASE_URL`은 테스트 대상으로 사용하지 않는다. 기존 DB의 데이터나 스키마를 수정하지 않고 자신이 생성한 DB만 정리한다. v3는 테스트 fixture의 outbox를 사용하고 SMTP를 발송하지 않는다.
2. 대표 CLI 담당: `packages/feature-standards/**`. 버전 `0.2.0`. 기존 읽기 전용 `list`/`context`를 유지하고 명시적인 `init --feature auth --source CHECKOUT --stack STACK --profile PROFILE --dest NEW_DIRECTORY [--check]`, `check --project GENERATED_DIRECTORY`를 추가한다. 의존성이 없는 배포를 유지하며 사용자가 지정한 신뢰된 원본 생성기를 호출한다. 원본과 생성 프로젝트의 경로·버전·프로토콜을 검증하고 구형 검사기를 조용히 실행하지 않는다.
3. 서버 배포 담당: 언어별 실제 wheel/JAR/crate가 원본 checkout 밖의 소비 프로젝트에서 로드되는지 검증한다. 기존 빌드 검사를 재사용하고 필요한 경우 `tools/check_server_distributions.py`와 관련 테스트를 추가한다. 계정·namespace·서명·신뢰 관계의 미충족 상태를 실제 게시 성공과 분리한다.
4. 주 에이전트: 계정/레지스트리 상태 확인, 명시적으로 허용된 게시, CI와 템플릿·README·manifest·배포 기록 통합, 독립 리뷰, 커밋·푸시·원격 검증.

PyPI 계정 페이지의 브라우저 접근이 보안 정책에 거절되었고, 로컬에 PyPI/Cargo/Central 자격 증명과 운영 서명 키가 없다. 사용자의 계정 연결을 기다리는 동안 전체 CI가 만든 wheel/sdist/library JAR/crate와 출처·체크섬을 GitHub 릴리스 자산으로 제공한다. 이 경로는 원본 checkout 없이 산출물을 내려받도록 돕지만, PyPI·Maven Central·crates.io 게시 완료를 뜻하지 않는다. 임시 fixture 서명 키로 실제 Central 릴리스를 서명하지 않는다.

생성 메타데이터는 `checkProtocolVersion: 1`을 포함한다. 생성기 `generate`와 생성 runner의 `runProject` API를 유지하며 `runProject('check', directory)`는 `{schemaVersion: 1, stack, profile, passed: true, checks: [...]}`를 반환한다. 대표 CLI는 요청한 stack/profile과 결과를 대조한다. 실제 빌드·실행 출력과 최종 검사 결과의 범위를 문서화한다. 잘못된 인수·존재하는 대상·경로 탈출·구형 프로토콜·결과 불일치는 성공으로 처리하지 않는다.

## 검증 순서

- 안전 경계와 선택 프로필의 회귀를 먼저 재현하고 관련 단위 검사를 통과시킨다.
- 새 tarball의 빈 캐시 오프라인 설치, 기존 15개 조회와 새 명령의 호출·거절 경계를 확인한다.
- 생성 앱 4언어 × 3프로필을 전용 테스트 자원에서 실행한다. DB나 계정 준비 부족은 건너뛴 성공으로 보고하지 않는다.
- 독립 wheel/JAR/crate 소비와 공개 Go 설치, 실제 레지스트리 버전·다운로드를 별도로 기록한다.
- 기존 서버 자체 검사·공통 API·브라우저·프로필·소비 예제와 워크플로 구문/템플릿을 확인한다. 실제 전체 CI를 통과한 소스만 새 버전 태그로 게시한다.
- 원격 ref, 게시 버전·파일 무결성·새 registry 설치를 확인한다. npm의 게시 검사 지연은 기존 제한된 대기 검증기를 사용한다.

계정 로그인이 필요한 경우 비밀값을 요청하거나 로그에 출력하지 않는다. 장기 토큰을 새로 CI에 넣지 않는다. 이미 존재하는 게시 버전과 태그는 덮어쓰지 않으며, 외부 계정 설정이 필요한 작업 때문에 독립 구현 작업을 멈추지 않는다.
