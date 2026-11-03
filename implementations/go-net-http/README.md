# Go / net/http 참조 구현

`browser-session-v1` 메모리, [PostgreSQL v2](../../features/auth/postgres-session-v2.md), 선택적 [계정 생명주기 v3](../../features/auth/account-session-v3.md)를 제공한다. HTTP는 표준 라이브러리, 비밀번호 해싱은 공식 `golang.org/x/crypto/argon2`의 Argon2id를 사용한다. 구현 계약은 [공통 명세](../../features/auth/specification.md)에 있다.

## 실행

Go 1.26 이상이 필요하다. 고정한 `golang.org/x/crypto` 버전의 최소 Go 버전을 따른다. 루프백에서만 사용하는 데모는 명시적으로 활성화한다.

```sh
cd implementations/go-net-http
AUTH_DEMO=true AUTH_COOKIE_SECURE=false \
  AUTH_ALLOWED_ORIGIN=http://127.0.0.1:5173 AUTH_PORT=8000 go run .
```

React 클라이언트는 별도 터미널에서 시작한다. 공개 데모 계정은 `demo@example.com` / `correct-horse-battery-staple`이다. 브라우저 요청은 React 개발 서버의 같은 origin 프록시로 보낸다. 서버는 CORS를 열지 않는다.

```sh
go test ./...
go test -race ./...
go vet ./...
go build -o bin/auth-server .
```

## 다른 Go 프로젝트에서 사용하기

실행 진입점은 루트 `main.go`이며 `go run .`과 기존 공통 검증 명령은 유지한다. 인증 구현은 import 가능한 [`auth`](auth) 패키지에 있다. 공개 진입점은 `auth.LoadConfig()`, `auth.NewServer(config)`, `auth.NewServerWithStore(config, store)`, `(*Server).CurrentUser(w, r)`, `(*Server).Close()`이다.

```go
import "github.com/jongko54/feature-standards/implementations/go-net-http/auth"

// config는 auth.LoadConfig()로 검증한 설정을 사용한다.
server, err := auth.NewServer(config)
// err 처리 후 앱 종료 시 server.Close()를 호출한다.
mux.Handle("/auth/", server)
mux.Handle("/healthz", server)
mux.HandleFunc("GET /api/profile", func(w http.ResponseWriter, r *http.Request) {
    user, ok := server.CurrentUser(w, r)
    if !ok { return } // 이미 안전한 401/503/500 응답을 기록했다.
    // user의 복사본으로 프로젝트의 읽기 전용 응답을 만든다.
    _ = user
})
```

`CurrentUser`는 `fs_session` 쿠키를 같은 저장소에서 조회하며 실패 시 identity를 반환하지 않는다. 반환 map을 바꿔도 세션에 저장된 identity는 바뀌지 않는다. 보호 응답에는 `no-store`와 `nosniff`를 설정한다. 이 API는 요청의 인증만 담당하며, 소비 앱의 업무 권한과 상태 변경 API의 Origin·CSRF 검증은 소비 앱에서 별도로 적용해야 한다. 예제는 `GET /api/profile`만 추가한다.

외부 `AuthStore`는 `auth.UnauthenticatedError()`·`InvalidCredentialsError()`·`CSRFInvalidError()`·`StorageUnavailableError()`·`RateLimitedError(retryAfterSeconds)`로 고정된 계약 오류를 반환할 수 있다. 선택적 `AccountStore`의 잘못된 확인·재설정 token에는 `InvalidTokenError()`를 사용한다. 임의 HTTP 상태·오류 코드·진단 문자열을 전달하는 API는 제공하지 않는다. 오류를 `%w`로 감싸도 HTTP 응답은 계약 코드만 사용하며 내부 진단을 드러내지 않는다. 알 수 없는 오류는 identity·쿠키 없는 `500 INTERNAL_ERROR`로 닫힌다. `auth_test`의 외부 패키지 검사가 공개 경계의 400·401·403·429·503과 wrapping 후 비노출을 검증한다.

[독립 Go 소비 프로젝트](../../examples/consumer-go/README.md)는 별도 `go.mod`와 로컬 `replace`로 이 패키지를 참조하고, 실제 loopback HTTP로 로그인·보호 API·잘못된 CSRF·로그아웃·복사한 이전 쿠키 거절과 독립 세션 보존을 검사한다. 인증 소스를 복사하지 않으며 공개 모듈 버전을 배포했다는 의미는 아니다. 메모리 검증과 PostgreSQL/v3 검증의 범위는 해당 문서를 따른다.

## 구현 범위

- Origin 검증, 독립 CSRF 토큰, `HttpOnly`/`SameSite=Lax` 쿠키, 서버 세션 파기와 절대 만료를 제공한다.
- 로그인할 때 전달된 이전 세션만 교체하고 다른 브라우저의 세션은 유지한다.
- 이메일은 ASCII 공백과 영문 대문자만 정규화해 언어별 Unicode 동작 차이를 없앤다. JSON의 짝이 없는 surrogate escape는 거절하며 정상 surrogate pair와 이스케이프된 역슬래시 문자열은 보존한다.
- 실패 횟수는 신뢰된 프록시 설정이 없는 TCP peer IP 기준이다. `X-Forwarded-For`를 신뢰하지 않는다.
- Argon2id는 64 MiB 메모리, 3회 반복, 병렬도 4를 사용한다. 검증을 직렬화해 동시 해싱 메모리와 실패 횟수를 제한한다.
- 설정에 있는 비밀번호는 초기화 때 해싱하며 서버 상태에는 해시와 솔트만 보관한다. 요청 본문과 인증 토큰을 로그에 남기지 않는다.
- 기본 `AUTH_STORE=memory`에서는 모든 세션과 실패 기록이 프로세스 메모리에 있다. 만료된 기록은 다음 인증 요청에 정리한다. 재시작하면 사라지며 다중 인스턴스에 공유되지 않는다.

메모리 모드의 비데모 실행은 HTTPS origin, secure 쿠키, 명시적 사용자 자격 증명이 필수이다. 이는 단일 사용자 참조 설정이며 운영 사용자 관리, TLS 종료, 운영 용량 정책 또는 보안 감사를 제공하지 않는다. 환경 변수의 값과 보안 경계는 공통 명세를 따른다.

## PostgreSQL 모드와 저장소 주입

앱 시작 전에 루트의 `tools/auth_db.py migrate`로 기준 DDL을 적용하고 로컬 데모 계정은 `seed-demo --confirm-demo` 명령으로 명시적으로 넣는다. 앱은 DDL·seed를 실행하지 않는다.

```sh
AUTH_STORE=postgres AUTH_DATABASE_URL='postgresql://user@127.0.0.1/feature_standards_test?sslmode=disable' \
AUTH_DEMO=true AUTH_COOKIE_SECURE=false go run .
```

DB 모드는 환경 설정 사용자 대신 DB 사용자를 조회한다. schema version 1과 연결 가능 여부를 바인딩 전에 검증한다. DB 실패는 URL·연결 오류를 드러내지 않는 `503 STORAGE_UNAVAILABLE`이며 세션 쿠키를 발급하지 않는다.

HTTP는 `AuthStore`의 `Login`, `Current`, `Logout`, `Ready`를 사용하며 SQL을 참조하지 않는다. `NewServerWithStore(config, store)`로 원자적 저장소를 주입할 수 있다. 기본 memory adapter와 pgx/v5 기반 PostgreSQL adapter가 같은 경계에 연결된다. DB adapter는 공유 peer advisory lock과 DB 시각으로 실패 횟수·세션 회전·로그아웃을 처리하며, 커밋이 끝난 뒤 응답한다. 토큰은 SHA-256 bytea로 저장하고 저장 PHC는 Argon2id 64 MiB/t3/p4/salt16/hash32만 검증한다.

실제 DB 자체 검사는 seed된 loopback 전용 DB에서 실행한다. 세션과 실패 기록을 초기화하므로 이름이 `feature_standards_test`로 시작해야 한다.

```sh
AUTH_TEST_DATABASE_URL='postgresql://user@127.0.0.1/feature_standards_test?sslmode=disable' \
go test -race ./...
```

## 계정 생명주기 v3

기존 v2 DB와 분리한 DB에 명시적으로 `002_accounts.sql`을 적용하고 `AUTH_STORE=postgres AUTH_ACCOUNT_LIFECYCLE=true`로 선택한다. v3는 schema 2, 기본 false인 v2는 schema 1을 요구한다. true+메모리와 빈 값·true/false 이외의 설정은 시작 전에 거절하며 앱이 마이그레이션·seed를 실행하지 않는다.

5개 계정 POST 경로는 [v3 계약](../../features/auth/account-session-v3.md)의 엄격한 JSON·Origin·새 비밀번호·token 규칙을 적용한다. 기존 프로필에서는 경로가 404이다. 선택적 `AccountStore`는 같은 트랜잭션의 공통 `account_reserve`로 peer 예산을 먼저 예약한 뒤, 허용된 요청만 새 PHC·난수 token 생성과 `account_apply`를 실행한다. 소진된 요청은 Argon2를 실행하지 않는다. 커밋 성공 이후에만 202·204 또는 token/rate 결과를 반환한다. 로그인은 사용자 행 `FOR SHARE`를 검증부터 커밋까지 유지해 reset과 직렬화한다. outbox는 민감한 queue이며 실제 외부 메일은 발송하지 않는다.

자체 v3 검사는 schema2의 작업 전용 DB를 초기화하므로 기존 `AUTH_TEST_DATABASE_URL`(v2)과 분리한다.

```sh
AUTH_ACCOUNT_TEST_DATABASE_URL='postgresql://user@127.0.0.1:5432/feature_standards_test_v3_go?sslmode=disable' \
go test -race ./... -run TestPostgresAccount
```

## 의존성 근거

- [Go Argon2id 공식 API](https://pkg.go.dev/golang.org/x/crypto/argon2)
- [Go HTTP 쿠키 공식 API](https://pkg.go.dev/net/http#Cookie)
- [RFC 9106 권장 매개변수](https://www.rfc-editor.org/rfc/rfc9106.html#section-7.4)

- [pgxpool 트랜잭션 API](https://pkg.go.dev/github.com/jackc/pgx/v5/pgxpool)

## Published module

The public `v0.1.0` nested-module release is available without a local replace directive:

```sh
go get github.com/jongko54/feature-standards/implementations/go-net-http/auth@v0.1.0
```

A fresh module passed both real HTTP consumer lifecycle tests with race detection. See the [release receipt](../../docs/go-release-0.1.0.json) and [source CI](https://github.com/jongko54/feature-standards/actions/runs/41571472426). The checked-in consumer continues using a local replace to verify current checkout changes.
