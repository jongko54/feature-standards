# Go / net/http 참조 구현

`browser-session-v1`의 Go 구현이다. HTTP는 표준 라이브러리, 비밀번호 해싱은 공식 `golang.org/x/crypto/argon2`의 Argon2id를 사용한다. 구현 계약은 [공통 명세](../../features/auth/specification.md)에 있다.

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

## 구현 범위

- Origin 검증, 독립 CSRF 토큰, `HttpOnly`/`SameSite=Lax` 쿠키, 서버 세션 파기와 절대 만료를 제공한다.
- 로그인할 때 전달된 이전 세션만 교체하고 다른 브라우저의 세션은 유지한다.
- 이메일은 ASCII 공백과 영문 대문자만 정규화해 언어별 Unicode 동작 차이를 없앤다. JSON의 짝이 없는 surrogate escape는 거절하며 정상 surrogate pair와 이스케이프된 역슬래시 문자열은 보존한다.
- 실패 횟수는 신뢰된 프록시 설정이 없는 TCP peer IP 기준이다. `X-Forwarded-For`를 신뢰하지 않는다.
- Argon2id는 64 MiB 메모리, 3회 반복, 병렬도 4를 사용한다. 검증을 직렬화해 동시 해싱 메모리와 실패 횟수를 제한한다.
- 설정에 있는 비밀번호는 초기화 때 해싱하며 서버 상태에는 해시와 솔트만 보관한다. 요청 본문과 인증 토큰을 로그에 남기지 않는다.
- 모든 세션과 실패 기록은 프로세스 메모리에 있다. 만료된 기록은 다음 인증 요청에 정리한다. 재시작하면 사라지며 다중 인스턴스에 공유되지 않는다.

비데모 실행은 HTTPS origin, secure 쿠키, 명시적 사용자 자격 증명이 필수이다. 이는 단일 사용자 참조 설정이며 운영 사용자 관리, 분산 저장소, TLS 종료, 다중 인스턴스 정책 또는 보안 감사를 제공하지 않는다. 환경 변수의 값과 보안 경계는 공통 명세를 따른다.

## 의존성 근거

- [Go Argon2id 공식 API](https://pkg.go.dev/golang.org/x/crypto/argon2)
- [Go HTTP 쿠키 공식 API](https://pkg.go.dev/net/http#Cookie)
- [RFC 9106 권장 매개변수](https://www.rfc-editor.org/rfc/rfc9106.html#section-7.4)
