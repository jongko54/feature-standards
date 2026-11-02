# PostgreSQL v2

`features/auth/postgres-session-v2.md`, `features/auth/openapi-v2.json`, `docs/postgres-v2.md`와 선택 스택 README를 읽는다. `AUTH_STORE=postgres`와 schema 1이 필요하다. 자동 DDL·seed·메모리 fallback은 없고 DB 사용자·실패 기록·세션을 공유한다. `AUTH_USER_EMAIL`·`AUTH_USER_PASSWORD`를 DB 계정 프로비저닝으로 사용하지 않는다.

이관·시크릿·기존 세션 폐기·배포의 영향이 기존 승인에 포함되는지 확인한다. 데모 seed는 기존 사용자 비밀번호를 덮어쓰지 않는다. Python은 wheel, Go는 auth package, Java는 library classifier JAR, Rust는 path crate, React는 API export를 사용하고 manifest의 소비 예제를 따른다. 레지스트리 게시를 가정하지 않는다.

Rust 원격 DB는 `sslmode=verify-full`로 TLS 1.2 이상·CA·hostname을 확인하며 평문 재시도는 없다. `sslrootcert` 지정 시 그 PEM CA, 없으면 플랫폼 루트를 사용한다. 명시적 loopback `sslmode=disable`은 로컬 예외다. 프록시 신뢰·운영 DB 권한·백업·용량은 별도로 검토한다.

참조 구현은 `uv run --frozen --project tools python tests/postgres_conformance.py --browser`와 `tests/consumer_conformance.py`로 확인한다. 이 harness는 `feature_auth` 스키마를 재생성하므로 작업 전용 임시 DB만 허용한다. 외부 fixture URI는 loopback·명시적 포트·ASCII `feature_standards_test*` DB명·단일 `sslmode=disable`만 허용하고 값이 있는 `PG*` 환경을 거절한다. 대상 앱·운영 DB에는 초기화 harness를 실행하지 않는다.
