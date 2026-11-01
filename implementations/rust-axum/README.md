# Rust / Axum

`browser-session-v1`의 Rust 참조 구현이다. HTTP 동작의 기준은
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
비데모에서는 `AUTH_USER_EMAIL`, `AUTH_USER_PASSWORD`, HTTPS
`AUTH_ALLOWED_ORIGIN`이 필요하다. 오류에는 설정값이나 인증 토큰을 기록하지 않는다.

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
단일 프로세스 실험용 참조 구현이며 분산 저장소·신뢰 프록시·운영 보안 감사를
제공하지 않는다.
