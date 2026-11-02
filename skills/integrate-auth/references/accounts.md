# 계정 생명주기 v3

`features/auth/account-session-v3.md`, `features/auth/openapi-v3.json`, `docs/account-v3.md`와 [PostgreSQL 전제](postgres.md)를 읽는다. `AUTH_STORE=postgres AUTH_ACCOUNT_LIFECYCLE=true`, 명시적 schema 2 이관이 필요하다. React는 개발·빌드 시 `VITE_AUTH_ACCOUNT_LIFECYCLE=true`로 선택한다. 기존 로그인 화면만 변경할 때 이관을 추가하지 않는다.

같은 트랜잭션에서 `account_reserve`를 해싱보다 먼저 실행하고 허용된 요청만 PHC·token을 만들어 `account_apply`에 전달한다. generated `enabled`는 관리자 허용과 이메일 확인의 DB 불변식이다. 확인·재설정이 관리자 차단을 해제하거나 자동 로그인하면 안 된다. 재설정은 기존 세션을 원자적으로 폐기한다.

`mail_outbox` 원문 capability는 인증 token 해시 테이블과 다른 민감 데이터다. `tools/mail_capture.py`는 작업 전용 DB에서 새 mode 0600 파일로만 캡처하며 외부 발송을 하지 않는다. 수신 원문을 로그·이슈·CI artifact로 노출하지 않는다.

`uv run --frozen --project tools python tests/account_conformance.py --browser`로 API·언어 간 상태·로그인/reset 경합·로컬 링크 화면을 확인한다. 작업 전용 DB 제한을 적용한다. 계정 화면 설정은 `clients/react/playwright.accounts.config.ts`다. Rust TLS 변경은 `implementations/rust-axum/tests/postgres_tls.py`에서 신뢰 체인·hostname·평문 거절을 확인한다.
