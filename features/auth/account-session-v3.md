# Auth / browser-session-v3 — 계정 생명주기

v2의 PostgreSQL·로그인·Origin·CSRF·쿠키·절대 만료를 유지하고 회원가입, 이메일 확인, 비밀번호 재설정을 추가한다. `AUTH_ACCOUNT_LIFECYCLE=true`와 `AUTH_STORE=postgres`를 함께 지정해야 선택된다. 기본 false는 기존 v1/v2이다. true+memory 또는 올바르지 않은 boolean은 시작 전에 거절한다. health profile은 `browser-session-v3`이다.

## 저장소와 호환성

v3는 명시적 `002_accounts.sql` 마이그레이션의 schema_version=2를 요구한다. v2는 기존 schema 1에서 유지되며 schema 2 시작을 거절한다. 마이그레이션 전 서버를 중단한다. 기존 사용자의 enabled를 admin_enabled로 옮기고 기존 계정은 마이그레이션 시점에 이메일 확인된 것으로 이관한다. 새 enabled는 `admin_enabled AND email_verified_at IS NOT NULL`의 generated column이다. 새 가입자는 email_verified_at=NULL이다. 이 DB 불변식 때문에 이전 바이너리가 남더라도 미확인 사용자는 로그인·조회에서 거절된다. 관리자의 비활성 상태를 확인/재설정이 바꾸면 안 된다.

로그인은 사용자 행을 `FOR SHARE`로 읽고 PHC 검증부터 새 세션 COMMIT까지 잠금을 유지한다. 재설정은 동일 사용자를 FOR UPDATE로 잠근다. 구 비밀번호를 읽은 로그인이 재설정 COMMIT 뒤에 새 세션을 발급하는 경합을 막는다.

## HTTP 계약

모든 경로는 POST만 허용하고 같은 정확한 Origin, JSON content-type, 최대 4096 bytes, 중복·추가 키·짝 없는 surrogate 거절, no-store/nosniff 규칙을 적용한다. v1/v2에서는 새 경로를 404로 처리한다. 성공/실패 모두 Set-Cookie를 발급하지 않는다. 쿠키나 기존 로그인 상태로 요청을 인증하지 않으며 자동 로그인도 하지 않는다.

| 경로 | 정확한 JSON 키 | 성공 |
|---|---|---|
| `/auth/register` | email, password | 202 `{"status":"accepted"}` |
| `/auth/email-verification/request` | email | 동일 202 |
| `/auth/email-verification/confirm` | token | 본문 없는 204 |
| `/auth/password-reset/request` | email | 동일 202 |
| `/auth/password-reset/confirm` | token, password | 본문 없는 204 |

email은 v1의 ASCII 정규화와 UTF-8 254byte 제한을 사용하며, 정규화 후 U+0000~U+0020 또는 U+007F가 들어 있으면 거절한다. 신규/재설정 password는 Unicode scalar 15개 이상이면서 UTF-8 1024byte 이하이다. 공백을 제거하지 않으며 기존 로그인 password 규칙은 유지한다. 추가적인 비밀번호 blocklist나 MFA 정책은 이 참조 프로필에 포함하지 않는다. token은 정확히 `[A-Za-z0-9_-]{43}`이다.

잘못된 본문/형식/길이는 400 INVALID_REQUEST, 잘못된/만료된/이미 사용한 올바른 형식 token은 동일 400 INVALID_TOKEN이다. Origin·미디어·크기·메서드는 v2 오류를 유지한다. DB/커밋 오류는 503 STORAGE_UNAVAILABLE이다. register의 기존 이메일, resend의 없는/확인된/비활성 계정, reset-request의 없는/미확인/비활성 계정은 같은 202이며 계정 상태·토큰·링크를 HTTP로 노출하지 않는다. 응답 본문 일치를 보장하며 네트워크 지연의 완전한 상수 시간은 주장하지 않는다.

## 원자적 동작과 공유 함수

네 언어는 한 트랜잭션에서 먼저 `SELECT feature_auth.account_reserve(action,peer)`로 공유 제한을 확인한다. 양수이면 해싱 없이 COMMIT하고 429와 그 값의 Retry-After를 반환한다. 0일 때만 검증된 라이브러리로 새 PHC와 32byte 난수의 base64url token을 생성하고 같은 연결/트랜잭션에서 `SELECT feature_auth.account_apply(action, peer, email, token, password_hash)`를 호출한다. apply는 transaction-local 예약을 한 번 소비하여 중복으로 횟수를 늘리지 않는다. 예약 없는 직접 apply도 스스로 제한을 확인한다. 사용하지 않는 인자는 빈 문자열이다. action은 `register`, `verify-request`, `verify-confirm`, `reset-request`, `reset-confirm`이다. apply 반환 0은 성공/일반 접수, -1은 INVALID_TOKEN, 양수는 429이다. 결과를 COMMIT한 뒤 응답한다. DB 함수에 HTTP 로직은 없다.

모든 요청은 실제 peer+action 기준 60초에 10회이며 성공·존재하지 않는 대상·잘못된 token도 같은 정책이다. SQL advisory namespace 20261104로 peer/action을 직렬화한다. 이메일별 요청은 namespace 20261105로 직렬화하고 사용자→token 순서로 행을 잠근다. token에서 사용자를 찾는 최초 조회는 잠그지 않고, 이메일 잠금과 사용자 잠금 후 token·만료를 다시 확인한다. 시각은 잠금 획득 뒤 DB clock_timestamp이다.

가입은 기존 이메일을 변경하지 않고 신규 사용자·PHC·확인 token·outbox를 한 트랜잭션으로 저장한다. 중복 가입에서 password를 덮어쓰지 않는다. 신규 가입과 확인 재요청은 같은 이메일의 verify 발송을 60초 cooldown으로 제한하며 응답은 202이다. reset 요청도 같은 이메일/종류의 60초 cooldown을 가진다. 새 발급은 같은 사용자의 같은 종류 기존 token과 미전달 outbox를 제거한다.

token 검증 테이블에는 SHA-256(UTF-8 token) 32byte만 저장한다. 확인 token은 24시간, reset token은 15분 절대 수명이다. 확인 COMMIT은 email_verified_at을 설정하고 해당 확인 token을 제거한다. reset COMMIT은 PHC 교체·모든 사용자 세션 삭제·모든 reset token 삭제를 원자적으로 수행한다. 비밀번호 정책 오류·잘못된/만료 token·DB 오류는 기존 password·세션·token을 변경하지 않는다. reset은 관리자 비활성을 해제하거나 이메일을 확인하지 않는다. confirm은 활성(관리자 허용) 대상만 처리한다.

## 메일 전달 경계

mail_outbox는 발송 종류·수신자·유효기간과 전달할 원문 token을 가진 트랜잭션 queue이다. 인증용 account_tokens의 해시 저장과 구분한다. outbox의 원문 token은 민감한 bearer credential이며 공개 HTTP·로그·CI artifact에 출력하면 안 된다. API 서버는 직접 발송하지 않는다. 선택적 `mail-delivery-v1.md`의 확장 migration과 SMTP 워커를 명시적으로 설정하면 외부 중계 서버로 전달할 수 있다. 로컬 수신 도구는 검사된 전용 DB의 SMTP 소유권 없는 queue만 읽어 mode 0600의 새 파일에 저장·fsync한 뒤 queue의 원문을 제거한다. fsync 후 COMMIT 결과가 불명확하면 파일을 보존하고 메시지 id로 중복을 구분한다. DB와 수신 파일은 운영에서 별도 접근 권한·암호화·보존 정책이 필요하다. 이 참조 queue는 at-least-once이다.

확인/재설정 링크는 설정한 신뢰 origin의 URL fragment에 token을 담는다. React는 fragment를 메모리로 읽은 뒤 주소에서 지우며 자동 확인 요청을 보내지 않는다. 사용자가 버튼을 눌러 POST로 확인한다. 비밀번호·token을 localStorage/sessionStorage에 저장하지 않는다.

## 수용 기준

v1/v2 회귀, 각 언어 v3 HTTP, 교차 언어 가입→확인→로그인→재설정, 토큰 종류·단일 사용·만료·동시 소비, 중복 가입의 비밀번호 보존, 관리자 비활성 보존, 모든 세션 폐기 및 구 로그인 경합 방지, peer 제한·email cooldown, DB 실패 rollback, 실제 React 흐름과 로컬 수신함, TLS 체인·hostname 검증을 확인한다.
