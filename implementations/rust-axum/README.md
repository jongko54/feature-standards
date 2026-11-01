# Rust / Axum

`browser-session-v1`(기본 메모리)과 `browser-session-v2`(PostgreSQL)의 Rust 참조 구현이다. HTTP 동작의 기준은
[`features/auth/specification.md`](../../features/auth/specification.md)이다.
Rust 1.93.1에서 빌드·검증한다. 직접 의존성과 전이 의존성의 정확한 버전은
`Cargo.lock`으로 고정하며 CI와 로컬 실행은 `--locked`를 사용한다.

```sh
cd implementations/rust-axum
cargo build --locked
AUTH_DEMO=true AUTH_COOKIE_SECURE=false AUTH_PORT=8004 \
  target/debug/feature-standards-auth
```

데모는 `AUTH_DEMO=true`에서만 활성화된다. 공개 계정은 `demo@example.com` /
`correct-horse-battery-staple`이다. 기본 허용 Origin은
`http://127.0.0.1:5173`이며 React의 `/auth` 프록시로 같은 origin에서 호출한다.
그 외 환경 설정, HTTPS 및 쿠키 보안 제약은 공통 명세와 같다.
메모리 비데모에서는 `AUTH_USER_EMAIL`, `AUTH_USER_PASSWORD`, HTTPS
`AUTH_ALLOWED_ORIGIN`이 필요하다. PostgreSQL 모드는 계정 환경 변수를 사용하지 않고
DB의 `feature_auth.users`를 조회한다. 오류에는 설정값이나 인증 토큰을 기록하지 않는다.

구현의 주요 선택은 다음과 같다.

- [Axum 0.8.9](https://docs.rs/axum/0.8.9/axum/)과
  [Tokio 1.54.1](https://docs.rs/tokio/1.54.1/tokio/)을 사용한다. 명시적인 요청 분기로
  404·405·413 오류도 공통 JSON 오류 형태와 보안 헤더를 유지한다. HEAD는
  405와 `Allow`·보안 헤더를 반환하며 HTTP 규칙에 따라 본문을 보내지 않는다.
- [RustCrypto Argon2 0.6.0](https://docs.rs/argon2/0.6.0/argon2/)의 Argon2id
  64 MiB·3회·4 lane과 16바이트 무작위 salt를 사용한다. 시작 해싱과 모든
  로그인 검증은 `spawn_blocking`에서 실행한다. owned semaphore permit 한 개가
  검증 및 실패 기록 갱신 전체를 직렬화하며 요청 취소 중에도 해시 작업의 제한을 유지한다.
  세션 조회·로그아웃은 해시 연산 중 저장소 잠금을 기다리지 않는다.
- debug 실행에도 같은 해싱 강도를 유지한다. 개발 프로필은 Argon2와 Blake2
  의존성만 컴파일 최적화하며 비용 파라미터는 바꾸지 않는다.
- `getrandom`의 운영체제 난수에서 독립적인 32바이트 세션/CSRF 토큰을 생성한다.
  CSRF와 비밀번호 해시 비교는 `subtle::ConstantTimeEq`를 사용한다.
- JSON은 객체 여부와 Serde의 문자열·필드 검증으로 처리한다. 중복/추가 키,
  잘못된 UTF-8, 짝 없는 surrogate는 거부하고 올바른 surrogate pair는 허용한다.
- 프로세스 메모리 저장소는 짧은 mutex 구간으로 보호한다. 만료 상태는 인증
  요청에서 정리하며 절대 TTL을 사용한다. rate limit은 `ConnectInfo`의 실제
  TCP peer IP만 사용한다. `X-Forwarded-For`는 사용하지 않는다.

```sh
cargo test --locked
cargo fmt --all -- --check
cargo clippy --locked --all-targets -- -D warnings
```

자체 테스트는 입력·설정 경계, Unicode 정규화, 세션 교체/독립성/폐기,
CSRF, 절대 만료, 동시 rate limit 및 HTTP 오류 형태를 확인한다.
공통 API 및 React 브라우저 검증은 저장소 루트의 공통 runner를 사용한다.
메모리 모드는 단일 프로세스 실험용이며 PostgreSQL 모드는 여러 프로세스가 같은
세션과 실패 기록을 공유한다. 신뢰 프록시나 운영 보안 감사를 제공하지 않는다.

## PostgreSQL v2

[`postgres-session-v2.md`](../../features/auth/postgres-session-v2.md)와
[`001_initial.sql`](../../features/auth/postgres/001_initial.sql)을 따른다. 시작 전에
공통 도구로 명시적으로 migrate/seed한다. 앱은 DDL이나 사용자 생성을 실행하지 않으며,
DB 연결과 schema version=1을 확인한 뒤 HTTP 포트를 연다. 준비 실패에는 시작을 거부한다.

```sh
AUTH_STORE=postgres AUTH_DATABASE_URL="$AUTH_TEST_DATABASE_URL" \
  AUTH_DEMO=true AUTH_COOKIE_SECURE=false AUTH_PORT=8004 \
  target/debug/feature-standards-auth
```

이 빌드는 [tokio-postgres 0.7.18](https://docs.rs/tokio-postgres/0.7.18/tokio_postgres/)
`NoTls`를 사용하므로 **loopback 호스트와 명시적인 `sslmode=disable` URI만 허용**한다.
예: `postgresql://localhost/feature_standards_test_rust?sslmode=disable`.
쿼리의 host/hostaddr 재정의도 거부한다. 원격 운영 DB와 TLS 연결은 현재 지원하지 않는다.
인증서 검증을 임의로 해제하거나 요구된 TLS를 평문으로 낮추지 않는다. 원격 지원은 별도
TLS 어댑터와 인증서/호스트 검증, DB 인증·권한·용량 검토가 필요하다.
연결 시도는 5초, 요청 DB 작업과 대기열은 각각 10초, SQL/잠금 대기는 8초로 제한한다.
DB 작업은 최대 8개 연결을 사용하며 DB 오류 원문·URI를 출력하지 않는다.
`/healthz`도 DB 준비 상태를 검사한다. 런타임 저장소 실패는 쿠키 없이 일반
`503 STORAGE_UNAVAILABLE`이며 메모리로 전환하지 않는다.

Argon2id PHC는 v=19, m=65536, t=3, p=4, 16바이트 salt, 32바이트 hash와
표준 무패딩 base64를 검증한다. 지원하지 않는 해시는 503으로 거부한다.
알 수 없는 사용자도 같은 비용의 dummy hash를 검증한다. 비활성 사용자는 로그인과
세션 조회가 거부된다. 세션 원문은 저장하지 않고 UTF-8 토큰의 SHA-256 bytea를 저장한다.
로그인은 공통 advisory transaction lock 아래 DB 시각으로 제한 검사·검증·실패 기록·세션
교체를 수행한다. 로그아웃은 세션 행을 `FOR UPDATE`로 잠그고 CSRF를 비교한다.
성공 응답과 쿠키는 COMMIT 성공 후에만 반환한다. Argon2는 owned semaphore permit을
가진 `spawn_blocking` 작업으로 제한하고 DB await 구간에 표준 mutex를 잡지 않는다.

## 서비스 주입

`AuthStore`는 저장소 독립적인 `ready/login/me/logout` 비동기 경계이고
`AuthService::new(Arc<dyn AuthStore>)`로 주입한다. `MemoryStore::new(&mut Config)`와
`PostgresStore::connect(&Config)`를 공개하며 기존 `app(Config).await` 실행도 유지한다.
`app_with_service(Config, AuthService)`는 같은 서비스로 Axum 라우터를 만든다.
HTTP 어댑터는 SQL을 알지 않고 `LoginSession`/`AuthError`를 공통 응답으로 변환한다.
주입한 사용자 정의 저장소의 시작 준비 검사는 호출자가 `service.ready().await`로 수행한다.

실제 PostgreSQL 자체 테스트는 명시적인 폐기 가능 DB에서만 실행한다. DB 이름은
`feature_standards_test`로 시작해야 한다. 이 테스트는 해당 DB를 migrate하고 테스트
사용자/세션/실패 기록을 초기화하므로 앱 DB와 공유하면 안 된다.

```sh
AUTH_TEST_DATABASE_URL='postgresql://localhost/feature_standards_test_rust?sslmode=disable' \
  cargo test --locked postgres_real_transactions -- --ignored
```

이 테스트는 시작 시 seed 부재, 두 인스턴스·라우터 재생성 후 세션 유지, 다중 사용자,
세션 SHA-256/TTL, CSRF와 중복 헤더, 만료, disabled 사용자, 잘못된 PHC,
공유 IP 제한의 동시 원자성, DB 테이블 가용성 실패 시 503과 시작 실패를 확인한다.
서로 다른 언어/실제 프로세스 재시작·PostgreSQL 중단·React 통합은 루트 공통 runner의
검증 범위다.
