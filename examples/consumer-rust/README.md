# Rust 소비 프로젝트

인증 코드를 복사하지 않고 `../../implementations/rust-axum`의
`feature-standards-auth` crate를 Cargo path dependency로 사용하는 별도 앱이다.
`publish = false`이며 crates.io에 게시된 패키지가 아니다. Rust 1.93.1 이상을 사용한다.

```sh
# 저장소 루트
cargo build --locked --manifest-path examples/consumer-rust/Cargo.toml
AUTH_DEMO=true AUTH_COOKIE_SECURE=false AUTH_PORT=8005 \
  cargo run --locked --manifest-path examples/consumer-rust/Cargo.toml
```

위 명령은 `127.0.0.1:8005`에 바인딩하며, 허용 Origin은
`http://127.0.0.1:5173`이다. `AUTH_PORT`를 지정하지 않으면 8000이다.
로컬 데모 계정은 공통 공개 fixture인 `demo@example.com` /
`correct-horse-battery-staple`이다. React 클라이언트를 연결하려면
`clients/react`에서 `AUTH_API_TARGET=http://127.0.0.1:8005 npm run dev`를 실행한다.

`src/lib.rs`는 다음 공개 API만으로 인증을 조합한다.

- `Config::from_env()` / `Config::from_lookup()`로 공통 설정을 검증한다.
- `AuthService::from_config(&mut config).await`로 선택한 저장소를 연다.
  메모리 비밀번호는 해싱 후 설정에서 제거되므로 같은 메모리 설정으로 서비스를 두 번 만들지 않는다.
- `app_with_service(config, service.clone())`가 기존 `/auth/*`와 `/healthz`를 제공한다.
- 보호된 `GET /api/profile`은 `current_user(&service, &headers).await`로 같은 세션을 조회한다.
  자체 Cookie 파싱·비밀번호 해싱·SQL·세션 캐시는 없다.

조회 성공은 `{"user":{"id":"…","email":"…"}}`이며 응답에 `no-store`와
`nosniff`를 적용한다. 익명·만료·폐기된 세션은 401, 저장소 장애는 503으로 닫힌다.
`current_user`는 사용자 조회 경계이다. 상태를 변경하는 제품 API를 추가할 때는
해당 요청의 Origin·CSRF·권한 정책을 별도로 검증해야 한다.

## 프로필 선택

기본값은 단일 사용자·프로세스 메모리인 v1이다. v2는
`AUTH_STORE=postgres AUTH_DATABASE_URL=…`로, v3는 여기에
`AUTH_ACCOUNT_LIFECYCLE=true`를 추가해 선택한다. 소비 앱의 코드 분기는 필요 없다.
DB 연결·schema 준비 검사와 장애 응답은 라이브러리가 처리한다.
앱은 DDL·seed·메모리 fallback을 하지 않는다. v2는 schema 1,
v3는 명시적 계정 migration을 적용한 schema 2가 필요하다.

실제 DB 준비·TLS·메일·운영 경계는
[PostgreSQL v2 안내](../../docs/postgres-v2.md),
[계정 v3 안내](../../docs/account-v3.md),
[Rust 구현 설명](../../implementations/rust-axum/README.md)을 따른다.
이 소비 프로젝트의 아래 테스트는 메모리 v1에서 실행하며 DB 동작 검증을 대신하지 않는다.

## 검증

```sh
cargo test --locked --manifest-path examples/consumer-rust/Cargo.toml
cargo fmt --all --manifest-path examples/consumer-rust/Cargo.toml -- --check
cargo clippy --locked --manifest-path examples/consumer-rust/Cargo.toml --all-targets -- -D warnings
```

통합 테스트는 실제 라이브러리의 메모리 저장소와 Axum 라우터를 사용한다.
익명 보호 API 401, 로그인 후 동일 사용자 조회, CSRF 없는 로그아웃 거절과 세션 보존,
정상 로그아웃 204, 복사해 둔 이전 Cookie의 보호 API 401을 검증한다.
실제 네트워크·PostgreSQL·React 브라우저 검증은 저장소 루트의 공통 하네스 범위이며
이 라우터 테스트 통과를 해당 검증까지 통과한 것으로 표현하지 않는다.

## Database consumer validation

The separate [consumer profile matrix](../consumer-python-react/PROFILE_TESTS.md) now builds and runs this application against PostgreSQL v2 and v3, using unique disposable databases and the shared consumer React UI. The four-backend matrix passed eight backend/profile combinations and 28 Chromium scenarios locally on 2026-11-03. This is additional runtime evidence; the unit tests described above still target memory v1. See the [validation record](../../docs/validation-reuse-2026-11-03.md).
