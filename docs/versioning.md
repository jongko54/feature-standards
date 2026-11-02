# 계약 버전과 업데이트

저장소 릴리스 버전, HTTP 프로필, PostgreSQL 스키마 버전은 서로 다른 대상을 식별합니다. 0.2.0 계약 확장의 로컬 결과는 [검증 기록](validation-2026-11-02.md), 원격 CI·릴리스·패키지 게시 여부는 각각 해당 원격 상태로 확인합니다.

| 대상 | 버전 | 의미 |
|---|---|---|
| React npm API 패키지 | `0.1.0` | `@ugauga/feature-standards-react-auth`, ESM JavaScript·타입 선언; [배포 기록](npm-release.md) |
| v1 OpenAPI `info.version` | `0.1.0` | 기존 단일 사용자·메모리 계약 |
| 기본 프로필 | `browser-session-v1` | `AUTH_STORE=memory` |
| v2 OpenAPI `info.version` | `0.2.0` | PostgreSQL 사용자·공유 세션·실패 기록·503 확장 |
| 선택 프로필 | `browser-session-v2` | `AUTH_STORE=postgres` |
| PostgreSQL 스키마 | `schema_version=1` | [기준 DDL](../features/auth/postgres/001_initial.sql)의 저장 형식 |
| v3 OpenAPI `info.version` | `0.3.0` | 가입·이메일 확인·비밀번호 재설정 확장 |
| 선택 프로필 | `browser-session-v3` | PostgreSQL + `AUTH_ACCOUNT_LIFECYCLE=true` |
| v3 PostgreSQL 스키마 | `schema_version=2` | [명시적 계정 이관](../features/auth/postgres/002_accounts.sql)과 generated enabled·token·outbox |

0.2.0은 v1을 조용히 덮어쓰지 않습니다. [v1 명세](../features/auth/specification.md), [OpenAPI](../features/auth/openapi.json), [시나리오](../features/auth/scenarios.json)는 유지합니다. [v2 명세](../features/auth/postgres-session-v2.md)는 HTTP 입력·쿠키·Origin·CSRF·절대 만료를 이어받으며 동적 DB 사용자 ID, DB 준비 상태와 `503 STORAGE_UNAVAILABLE`을 추가합니다. 회원가입·비밀번호 재설정·역할 관리는 포함하지 않습니다.

0.3.0의 [v3 계약](../features/auth/account-session-v3.md)은 별도 프로필·schema 2입니다. v1/v2의 기본 선택과 계약 파일을 유지하며, v2는 schema 1에서 계속 실행합니다. 이관 전 기존 서버를 중단하고 명시적 `migrate-accounts`를 실행합니다. 기존 사용자는 확인된 상태와 기존 관리자 허용을 보존하고, 새 pending 계정은 generated enabled가 구 바이너리에서도 차단합니다. v3 확인·재설정은 관리자 차단을 해제하거나 자동 로그인하지 않습니다. v3 구현·정적 매핑·최종 실행·원격 상태는 별도 근거입니다.

같은 프로필의 구현은 엔드포인트·상태 코드·오류 코드·세션 무효화·보안 전제에 합의해야 합니다. 내부 함수·프레임워크·저장소 인터페이스는 달라도 됩니다. 기존 호출을 깨뜨리는 외부 변경은 새 프로필로 정의하고, 저장 형식을 바꿀 때는 스키마 버전과 명시적 마이그레이션도 함께 바꿉니다. 앱이 버전을 바꾸지 않고 DDL을 자동 보정해서는 안 됩니다.

## 계약 파일을 바꾸는 순서

1. 기준 명세와 테스트에서 의도한 성공·실패 동작을 정의합니다.
2. v1 HTTP 공통 내용을 바꾸면 v1 계약과 회귀 범위를 확인합니다. v2와 v3 전용 확장은 각각 [v2 생성기](../tools/generate_openapi_v2.py), [v3 생성기](../tools/generate_openapi_v3.py)의 `build_spec()`에 반영합니다.
3. 생성기를 순서대로 실행합니다. v2는 v1을 읽고 v2만, v3는 v2를 읽고 v3만 씁니다. 기존 프로필의 동작을 새 버전으로 조용히 교체하지 않습니다.
4. 실제 unittest 메서드·Playwright 제목·백엔드 집합이 바뀌면 [v2 근거 맵](../features/auth/scenarios-v2.json)과 [v3 근거 맵](../features/auth/scenarios-v3.json)을 맞춥니다.
5. `uv run --frozen --project tools python tools/check_contract.py`와 두 생성기의 `--check`를 실행합니다. 세 OpenAPI의 유효성, 생성 drift, 실제 테스트 집합과 매핑을 검사합니다.
6. 구현별 자체 검사, v1·v2·v3 API·브라우저, 혼합 언어·재시작·계정 경합·Rust TLS·소비 앱 검증을 실행하고 결과를 기록합니다. 정적 계약 검사만으로 런타임 통과를 선언하지 않습니다.

복사해서 통합하는 프로젝트는 출처 URL, 통합한 커밋 SHA, 프로필, 수정한 지점, 실제 검증 명령과 결과를 해당 프로젝트 문서에 남깁니다. 이 저장소의 업데이트가 복사본에 자동 전달되지는 않습니다. Python wheel이나 React path dependency도 자동 업데이트를 보장하지 않습니다.

런타임과 라이브러리는 각 구현의 잠금 파일과 명시적 버전을 따릅니다. 버전을 바꾸면 자체 테스트와 공통 API를 검증하고 클라이언트 영향이 있으면 네 서버 대상 브라우저 검사도 실행합니다. 지원 언어·저장소·원격 연결을 추가했다는 표시는 실제 실행 근거가 있는 범위에서만 합니다. 로컬 빌드, 원격 커밋, CI 성공, 패키지 게시, 실제 배포는 각각 별개의 완료 상태입니다.
