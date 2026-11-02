# Go 패키지 소비 예제

별도 `go.mod`에서 `github.com/jongko54/feature-standards/implementations/go-net-http/auth`를 import한다. 인증 구현·쿠키 파싱·비밀번호 해싱·세션 조회 로직을 복사하지 않고, 원래 HTTP handler와 `Server.CurrentUser`로 `GET /api/profile`을 추가한다.

## 실행과 검증

Go 1.26 이상을 사용한다. 아래 명령은 저장소 루트에서 시작한다.

```sh
cd examples/consumer-go
go test -race ./...
go build -o bin/consumer-go .
AUTH_DEMO=true AUTH_COOKIE_SECURE=false \
  AUTH_ALLOWED_ORIGIN=http://127.0.0.1:5173 AUTH_PORT=8000 go run .
```

공개 로컬 데모 계정은 `demo@example.com` / `correct-horse-battery-staple`이다. React 개발 서버의 `AUTH_API_TARGET=http://127.0.0.1:8000` 프록시에서 기존 인증 화면을 사용할 수 있다. `/api/profile`은 별도 소비 앱 API이므로 직접 호출하거나 소비 화면의 개발 프록시에 추가한다. 이 예제 자체의 브라우저 화면 검증은 제공하지 않는다.

`go test -race ./...`는 실제 `httptest.Server`의 loopback HTTP 요청으로 다음을 검증한다.

- 익명 보호 API의 401과 로그인한 사용자의 identity·쿠키 속성·캐시 금지
- 잘못된 CSRF의 로그아웃 거절과 기존 세션 유지
- 정상 로그아웃의 204·쿠키 제거와 복사해 둔 이전 쿠키의 보호 API·`/auth/me` 401
- 한 세션의 로그아웃 뒤 독립적인 두 번째 세션 유지

`go.mod`의 `replace`는 이 checkout의 구현을 사용한다. `v0.0.0`은 로컬 의존성을 위한 표기이며 공개 registry 게시나 원격 버전의 존재를 뜻하지 않는다. 다른 저장소에 통합할 때는 원본 저장소 URL·커밋 SHA·계약 프로필·실행한 검증 결과를 기록하고 의존성 위치를 명시한다.

## 저장소와 계약 선택

기본 테스트는 단일 데모 사용자·프로세스 메모리의 `browser-session-v1`이다. 재시작하면 세션이 사라지고 다중 인스턴스 간 공유되지 않는다.

같은 앱 factory가 `AUTH_STORE=postgres`의 v2와 `AUTH_ACCOUNT_LIFECYCLE=true`의 v3를 그대로 전달한다. PostgreSQL은 [v2 안내](../../docs/postgres-v2.md)에 따라 별도 DB에 명시적으로 이관·seed한 뒤 `AUTH_DATABASE_URL`을 설정한다. 가입·이메일 확인·비밀번호 재설정은 [v3 안내](../../docs/account-v3.md)의 schema 2와 계정 설정을 사용한다. 앱은 자동 DDL·seed·메모리 fallback을 하지 않는다. 소비 예제의 기본 테스트가 PostgreSQL 또는 계정 생명주기 실행 검증을 대신하지 않으며, 해당 저장소의 공통 v2/v3 conformance로 따로 확인한다.

`CurrentUser` 실패 시 handler는 즉시 반환해야 한다. 데이터베이스 실패는 503, 알 수 없는 내부 실패는 진단 문자열이 없는 500이며 identity를 반환하지 않는다. 이 helper는 인증만 수행한다. 소비 앱의 역할·자원 접근 권한과 상태 변경 API의 Origin·CSRF 정책은 그 앱의 책임이다. 예제는 보호된 읽기 전용 API만 추가하며 운영 배포나 보안 감사 완료를 뜻하지 않는다.
