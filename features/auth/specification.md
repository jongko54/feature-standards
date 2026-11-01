# Auth / browser-session-v1

상태: 실험적 참조 구현. 웹 브라우저의 같은 사이트 배포를 위한 서버 저장 세션 규격이다. 인증 프로토콜을 새로 발명하지 않고 OWASP 세션 관리 지침을 구현 가능한 동작으로 좁힌다. 모바일 bearer token, 소셜 로그인, 회원가입, 여러 사용자 저장소, 모든 기기 로그아웃은 이 버전의 범위 밖이다.

## 설정과 실행

- 구현은 `implementations/python-fastapi`, `implementations/go-net-http`, `implementations/java-spring`, `implementations/rust-axum`에 둔다. 언어별 내부 구조와 달리 아래 HTTP 동작은 공통이다.
- 서버는 `AUTH_HOST`(기본 `127.0.0.1`)와 `AUTH_PORT`(기본 `8000`)에 바인딩한다.
- 데모는 명시적인 `AUTH_DEMO=true`에서만 켜진다. 이때 공개 테스트 계정은 `demo@example.com` / `correct-horse-battery-staple`이다.
- 데모 밖에서는 `AUTH_USER_EMAIL`, `AUTH_USER_PASSWORD`가 필수이다. 비밀번호는 시작할 때 Argon2id로 해싱하고 원문을 로그에 출력하지 않는다. 이 단일 사용자 환경 설정은 참조용이며 운영 사용자 관리 API가 아니다.
- `AUTH_ALLOWED_ORIGIN` 기본값은 `http://127.0.0.1:5173`이다. 정확한 scheme/host/port 한 개만 허용하며 와일드카드를 허용하지 않는다.
- `AUTH_COOKIE_SECURE`는 기본 `true`이다. `false`는 데모 모드의 loopback origin에서만 허용한다. 데모 밖에서는 HTTPS origin만 허용한다.
- `AUTH_SESSION_TTL_SECONDS` 기본 `1800`, `AUTH_RATE_LIMIT_MAX` 기본 `5`, `AUTH_RATE_LIMIT_WINDOW_SECONDS` 기본 `60`이며 모두 양의 정수이다. 테스트는 짧은 값으로 별도 서버를 실행할 수 있다.
- 사용자·세션·실패 횟수는 각 프로세스 메모리에 저장한다. 재시작하면 모든 세션과 실패 횟수가 사라진다. 다중 인스턴스용 저장소는 이 버전에서 제공하지 않는다.

## 공통 HTTP 동작

- 모든 `/auth/*` 응답(오류 포함)은 `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`를 가진다.
- 오류 본문은 `{"error":{"code":"ERROR_CODE","message":"..."}}`이다. 메시지 문구는 계약 대상이 아니며 비밀번호·세션 토큰·CSRF 토큰은 오류나 로그에 포함하지 않는다.
- 잘못된 메서드는 `405 METHOD_NOT_ALLOWED`; 알 수 없는 경로는 `404 NOT_FOUND`이다.
- 상태 변경 요청은 정확한 `Origin: AUTH_ALLOWED_ORIGIN`이 필수이다. 누락·불일치는 `403 ORIGIN_DENIED`. 로그인에도 적용해 login CSRF를 막는다. `X-Forwarded-For`는 신뢰하지 않는다.
- 이 프로필은 CORS를 제공하지 않는다. React 개발 서버의 `/auth` 프록시 또는 운영 reverse proxy로 같은 origin에서 호출한다. 교차 사이트 배포는 별도 프로필로 정의해야 한다.
- Python 서버는 `uvicorn --no-proxy-headers`로 실행한다. 전달 헤더를 실제 peer 주소로 바꾸지 않는다. 프록시 뒤 배포에서는 모든 사용자가 같은 peer 제한을 공유하므로 신뢰 프록시·분산 rate limit은 별도 운영 설계가 필요하다.

## 엔드포인트

### POST /auth/login

- `Content-Type: application/json`(charset 매개변수 허용)이 필수이다. 아니면 `415 UNSUPPORTED_MEDIA_TYPE`.
- UTF-8 JSON 객체에 문자열 `email`, `password` 두 필드만 허용한다. email은 아래의 정확한 규칙으로 정규화하며 `@`가 있어야 하고 254 UTF-8 바이트 이하여야 한다. password는 1~1024 UTF-8 바이트이다. 중복 JSON 키·배열·null·알 수 없는 필드·잘못된 UTF-8/JSON·짝이 없는 UTF-16 surrogate escape는 `400 INVALID_REQUEST`. 올바른 surrogate pair(예: 이모지)는 정상 Unicode 문자열로 처리한다.
- 이메일 정규화는 양끝 ASCII 공백(`U+0009`~`U+000D`, `U+0020`)만 제거하고 ASCII `A`~`Z`만 소문자로 바꾼다. 그 밖의 Unicode 문자는 보존한다. 언어별 Unicode case/whitespace 테이블에 의존하지 않으며, 국제화 이메일의 동등성 판단은 이 참조 규격에서 제공하지 않는다. 환경 설정 사용자에도 동일 규칙을 적용한다.
- 본문은 4096바이트 이하이다. 초과 시 `413 REQUEST_TOO_LARGE`. 비밀번호를 자르거나 공백 제거하지 않는다.
- 잘못된 이메일 또는 비밀번호는 동일한 `401 INVALID_CREDENTIALS`. 존재하지 않는 계정에도 Argon2id 검증을 수행한다.
- 실패 횟수는 TCP peer IP 기준으로 제한한다. 창 안에서 N번의 자격 증명 실패 후 이후 로그인 요청은 올바른 자격 증명이어도 `429 RATE_LIMITED`와 양의 정수 `Retry-After`를 반환한다. 성공 시 해당 peer의 실패 기록을 지운다. 잘못된 origin·본문 형식은 실패 횟수로 세지 않는다.
- 성공 시 새 암호학적 난수 세션 ID(256비트 이상)와 독립 CSRF 토큰(256비트 이상)을 생성한다. 현재 쿠키로 전달된 이전 세션이 있으면 무효화한다. 다른 독립 브라우저의 세션에는 영향을 주지 않는다.
- 응답 `200 {"user":{"id":"demo-user","email":"demo@example.com"},"csrfToken":"..."}`. 비데모 사용자의 ID도 `demo-user`로 고정되며 이메일은 설정값이다.
- 쿠키 이름 `fs_session`; 속성 `Path=/; HttpOnly; SameSite=Lax`, secure 설정 시 `Secure`, `Domain` 없음. 수명은 세션 TTL을 넘지 않는 `Max-Age`로 설정한다.

### GET /auth/me

- 유효한 세션: `200`과 로그인과 같은 user/csrfToken 형식.
- 누락·만료·무효·변조된 세션: `401 UNAUTHENTICATED`.
- 고정된 절대 TTL을 사용한다. 조회는 수명을 늘리지 않는다. 로그인 전의 세션 ID는 인증 후 재사용할 수 없다.

### POST /auth/logout

- Origin 검증 후 유효한 세션에는 세션과 일치하는 `X-CSRF-Token`이 필수이다. 누락·불일치 시 `403 CSRF_INVALID`이며 세션은 유지한다. 비교는 상수 시간 함수를 사용한다.
- 성공 시 서버 세션을 삭제하고 동일 이름·경로·보안 속성의 쿠키를 `Max-Age=0`으로 제거한다. 응답은 본문 없는 `204`.
- 이미 없거나 만료된 세션에도 허용 origin이면 `204`와 쿠키 제거를 반환한다. 반복 로그아웃은 안전하다.
- 삭제 전 복사한 쿠키를 새 클라이언트에서 재전송해도 `/auth/me`는 `401`이어야 한다.

### GET /healthz

- `200 {"status":"ok","profile":"browser-session-v1","implementation":"..."}`. implementation은 구현 이름이며 인증 세부 정보는 반환하지 않는다.

## 수용 기준

공통 API 테스트는 네 서버를 별도 프로세스로 시작하고 같은 시나리오를 실행한다. 로그인 성공·실패, 정규화, 입력 경계, origin, 쿠키 속성, 캐시 방지, 세션 갱신과 이전 쿠키 재사용, CSRF 실패 후 세션 유지, 독립 세션, 로그아웃 멱등성, 절대 만료, 로그인 제한, 메서드·경로 오류를 확인한다. 실제 브라우저 테스트는 각 서버에 같은 React 화면을 연결해 로그인·새로고침 유지·로그아웃·오류·만료 처리를 확인한다.

테스트 통과는 해당 프로필의 적합성을 뜻한다. 운영 보안 감사, 분산 환경 안정성, 외부 인증 제공자와의 호환성을 의미하지 않는다.

## 근거

- https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html
- https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html
- https://github.com/realworld-apps/realworld/tree/main/specs/api
