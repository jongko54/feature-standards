# Java / Spring Boot 참조 구현

`browser-session-v1`(기본 메모리)과 `browser-session-v2`(PostgreSQL)의 Java 구현이다. Java 21 이상과 Maven wrapper를 사용한다. Spring Boot 3.5.16의 내장 Tomcat, Spring Security Crypto 6.5.11의 `Argon2PasswordEncoder`, Bouncy Castle 1.86, PostgreSQL JDBC 42.7.14를 사용한다. HTTP 동작의 기준은 [v1 공통 명세](../../features/auth/specification.md)와 [v2 저장소 계약](../../features/auth/postgres-session-v2.md)이다.

## 빌드와 실행

`JAVA_HOME`이 설치된 JDK 21 이상을 가리켜야 한다. Maven을 별도로 설치할 필요는 없다. Maven Wrapper 3.3.4의 공식 스크립트가 Maven 3.10.0을 내려받고 고정한 SHA-256을 확인한다. 최초 빌드에는 Maven Central 접근이 필요하다. Wrapper의 라이선스와 출처는 [외부 파일 고지](THIRD_PARTY_NOTICES.md)에 포함했다.

```sh
cd implementations/java-spring
./mvnw -q test
./mvnw -q -DskipTests package
AUTH_DEMO=true AUTH_HOST=127.0.0.1 AUTH_PORT=8000 \
  AUTH_ALLOWED_ORIGIN=http://127.0.0.1:5173 AUTH_COOKIE_SECURE=false \
  java -jar target/auth-server.jar
```

빌드 산출물의 이름은 `target/auth-server.jar`로 고정한다. 데모는 `AUTH_DEMO=true`에서만 활성화되며 공개 계정은 `demo@example.com` / `correct-horse-battery-staple`이다. React 개발 서버의 `/auth` 프록시를 사용한다. CORS를 제공하지 않는다.

메모리의 비데모 실행에는 `AUTH_USER_EMAIL`, `AUTH_USER_PASSWORD`, HTTPS `AUTH_ALLOWED_ORIGIN`이 필요하며 secure 쿠키를 끌 수 없다. 비밀번호를 시작 시 Argon2id로 해싱한다. 서버 상태에는 원문 비밀번호를 보관하지 않는다. 잘못된 설정은 포트를 열기 전에 거절한다. `AUTH_HOST`와 `AUTH_PORT`가 바인딩을 정한다.

다른 환경 변수는 `AUTH_SESSION_TTL_SECONDS`(1800), `AUTH_RATE_LIMIT_MAX`(5), `AUTH_RATE_LIMIT_WINDOW_SECONDS`(60)이며 양의 정수만 받는다. `AUTH_COOKIE_SECURE`는 기본 `true`, origin은 기본 `http://127.0.0.1:5173`이다. `false`는 명시적 데모의 loopback origin에서만 허용된다. 자세한 경계는 공통 명세를 따른다.

## PostgreSQL 실행과 재사용

`AUTH_STORE=postgres`와 `AUTH_DATABASE_URL`로 선택한다. URL은 `postgresql://user:percent-encoded-password@host:5432/database?sslmode=...` 형식이며 JDBC URL로 변환한다. URI 사용자 정보의 percent encoding과 `sslmode`, `sslcert`, `sslkey`, `sslrootcert`, `sslpassword`, `ssl`, `user`, `password`, `application_name`, `connect_timeout` 옵션을 받는다. 별도 schema 선택은 허용하지 않는다. DB 연결·인증 대기는 5초, socket·SQL 제한은 15초로 고정되어 URI로 비활성화할 수 없다. URL과 JDBC 오류 원문은 오류 응답과 예외의 cause에 포함하지 않는다.

스키마는 서버 실행 전에 루트의 명시적 도구로 준비한다. `AUTH_DATABASE_URL`은 별도로 환경에 설정하며 아래 명령에는 값을 출력하지 않는다.

```sh
# 저장소 루트에서, 명시적 마이그레이션
uv run --project tools python tools/auth_db.py migrate
# 공개 데모 계정이 필요한 로컬 테스트에서만 실행
uv run --project tools python tools/auth_db.py seed-demo --confirm-demo

cd implementations/java-spring
AUTH_STORE=postgres AUTH_DEMO=true AUTH_COOKIE_SECURE=false \
  AUTH_ALLOWED_ORIGIN=http://127.0.0.1:5173 java -jar target/auth-server.jar
```

DB 모드에서는 `AUTH_USER_EMAIL`과 `AUTH_USER_PASSWORD`를 요구하거나 사용하지 않는다. `AUTH_DEMO=true`도 HTTP·쿠키 예외만 허용하며 사용자를 만들거나 해시를 덮어쓰지 않는다. 시작 시 schema version 1과 연결을 검사하며 자동 DDL, seed, 메모리 fallback은 없다. `/healthz`는 DB 준비 상태를 확인하고 `browser-session-v2`를 반환한다. 요청 중 저장소 실패는 쿠키를 발급하지 않는 일반 503 `STORAGE_UNAVAILABLE` 응답이다.

`dev.featurestandards.auth.AuthService`는 Servlet에 의존하지 않는다. `AuthService.create(config, memoryPassword, clock)`으로 저장소를 선택하거나 `new AuthService(authStore)`로 `AuthStore`를 주입한다. `MemoryAuthStore`와 `PostgresAuthStore`도 공개 생성자를 제공한다. `login(peer, previousToken, email, password)`은 `Login`, `session(token)`은 사용자 정보를 가진 `Session` 또는 null, `logout(token, csrf)`는 CSRF 검사 결과를 반환한다. `AuthConfig.load(env)`는 설정을 검증한다. 별도 Spring 앱은 `new AuthFilter(config, service)`를 등록할 수 있다. DB 연결 경계는 `PostgresAuthStore(config, connections)`로 주입할 수 있으며 `connections`는 요청마다 독립적인 `java.sql.Connection`을 제공한다.

### 라이브러리로 가져오기

`./mvnw -q install -DskipTests`는 기존 실행 파일 `target/auth-server.jar`와 일반 클래스 경로의 `target/auth-server-library.jar`를 함께 빌드하고 로컬 Maven 캐시에 설치한다. 다른 프로젝트는 `io.github.jongko54:java-spring-auth:1.0.0:jar:library`를 의존성으로 지정한다. 일반 JAR에는 참조 서버의 `AuthApplication`과 `application.properties`를 넣지 않으므로 소비 앱의 component scan·설정을 덮어쓰지 않는다. Maven Central 게시를 수행하지 않는다.

공개 `AuthConfig.password(env, demo)`는 메모리 사용 시 참조 구현과 같은 비밀번호 선택 규칙을 제공한다. PostgreSQL 모드는 비밀번호 인자를 null로 전달하며 기존 설정·schema 검사를 사용한다. Servlet 어댑터를 재사용할 때 `AuthFilter`를 `/auth/*`, `/healthz`에 등록하고 소비 앱의 경로는 해당 앱에서 처리한다. 보호 API는 `AuthService.session(token)`의 유효 세션만 사용하고 저장소 실패를 성공이나 익명 상태로 감추지 않는다. 실제 별도 의존성 설치·보호 API·로그아웃 후 쿠키 폐기는 [Java 소비 예제](../../examples/consumer-java/README.md)에서 검증한다.

PostgreSQL은 사용자별 PHC와 enabled 상태를 조회하고 세션 토큰의 SHA-256만 bytea로 저장한다. 로그인은 공통 advisory transaction lock 아래에서 DB 시각·실패 창·성공 시 실패 제거·이전 세션 교체·세션 생성을 처리한다. 로그아웃은 세션 행을 `FOR UPDATE`로 잠그고 CSRF를 비교한다. 사용자가 비활성화되어도 만료 전 저장 세션에는 정확한 CSRF가 필요하며, 올바른 CSRF로 삭제할 수 있다. 로그인·조회는 비활성 사용자를 거절한다. 결과와 쿠키는 commit 성공 후에만 반환한다. 조회는 절대 만료를 연장하지 않는다.

자체 DB 테스트는 이미 마이그레이션된 전용 loopback DB를 명시적으로 선택할 때만 실행된다. **해당 DB의 auth 사용자·세션·실패 기록을 초기화**하며 DB 이름은 `feature_standards_test`로 시작해야 한다.

```sh
AUTH_TEST_DATABASE_URL="$AUTH_DATABASE_URL" ./mvnw -q test
```

## 계정 생명주기 v3

명시적으로 schema 2로 마이그레이션한 별도 DB에서 `AUTH_STORE=postgres AUTH_ACCOUNT_LIFECYCLE=true`를 지정한다. 기본 false는 기존 v1/v2이며 true+memory와 잘못된 boolean(빈 문자열 포함)은 시작 전에 거절한다. v3는 schema 2만, v2는 schema 1만 허용한다. 기준 계약은 [account-session-v3.md](../../features/auth/account-session-v3.md)이다. `/healthz`는 `browser-session-v3`를 반환한다.

선택한 프로필에서만 다음 POST 경로를 제공하며 기존 프로필에는 404를 반환한다. 모든 요청은 기존 Origin·JSON·본문 제한과 no-store/nosniff 규칙을 따른다. 어떤 계정 경로도 세션 쿠키를 발급하거나 자동 로그인하지 않는다.

| 경로 | JSON 필드 | 성공 |
|---|---|---|
| `/auth/register` | email, password | 일반 202 accepted |
| `/auth/email-verification/request` | email | 동일 202 |
| `/auth/email-verification/confirm` | token | 본문 없는 204 |
| `/auth/password-reset/request` | email | 동일 202 |
| `/auth/password-reset/confirm` | token, password | 본문 없는 204 |

신규·재설정 비밀번호는 Unicode scalar 15개 이상, UTF-8 1024byte 이하이며 공백을 보존한다. 기존 로그인 규칙은 바뀌지 않는다. 계정 이메일은 ASCII 정규화 후 내부 ASCII 제어 문자·공백을 거절한다. JSON 중복·추가 키·잘못된 UTF-8·짝 없는 surrogate도 거절한다. 잘못된 형식은 `400 INVALID_REQUEST`, 올바른 형식의 무효·만료·재사용 토큰은 `400 INVALID_TOKEN`이다.

서비스의 `account(action, peer, email, token, password)`는 검증한 입력을 저장소에 전달한다. PostgreSQL 저장소는 같은 트랜잭션에서 `feature_auth.account_reserve`로 공유 제한을 먼저 검사하고, 허용된 요청만 기존 암호 라이브러리로 신규 PHC와 token을 생성한다. `account_apply`가 예약을 한 번 소비하며 결과는 commit 뒤에 반환한다. 제한된 요청은 비밀번호를 해싱하지 않는다. DB 실패는 일반 503이며 비밀번호·세션·토큰·outbox 변경이 함께 rollback된다. 로그인은 사용자 `FOR SHARE` 잠금을 해시 검증부터 commit까지 유지해 비밀번호 재설정과 직렬화한다.

schema 2의 `enabled`는 관리자 허용과 이메일 확인 여부로 계산된다. 확인·재설정이 관리자 비활성을 해제하지 않는다. 메일은 공통 DB outbox에 쌓이며 이 Java 어댑터는 외부 메일을 보내지 않는다. token 검증 테이블과 달리 outbox에는 전달할 원문 capability가 있으므로 민감 정보로 다룬다. 보존·로컬 수신 절차는 공통 계약을 따른다.

자체 v3 검사는 `AUTH_ACCOUNT_TEST_DATABASE_URL`의 별도 schema-2 DB를 초기화한다. 기존 `AUTH_TEST_DATABASE_URL`은 schema-1 전용 DB로 유지한다. 두 URL에 같은 DB를 지정하면 안 된다.

```sh
# 각각 미리 마이그레이션한 작업 전용 DB를 환경에 설정한 뒤:
./mvnw -q test
```

## 구현과 검증 범위

- Servlet filter가 메서드·경로·오류·캐시 헤더를 명시적으로 처리한다. Spring의 기본 로그인 화면이나 자동 CORS 응답을 추가하지 않는다.
- UTF-8 디코더는 잘못된 바이트를 거절한다. Jackson의 중복 키 검출과 추가 토큰 거절, 필드·Unicode surrogate·바이트 길이 검증을 함께 적용한다. 이메일은 ASCII 공백과 ASCII 대문자만 정규화한다.
- 32바이트 세션 ID와 독립 CSRF 토큰에 `SecureRandom`을 사용한다. CSRF는 JDK `MessageDigest.isEqual`로 비교한다. 로그인은 전달된 이전 세션만 교체하고 로그아웃은 서버 기록을 삭제한다. 조회는 절대 TTL을 늘리지 않는다.
- Argon2id는 64 MiB, 반복 3회, 병렬도 4, 솔트 16바이트, 출력 32바이트이다. 알 수 없는 계정도 동일한 해시를 검증한다. 동시 해시 검증은 직렬화한다.
- TCP peer IP로 실패를 제한한다. `server.forward-headers-strategy=none`으로 `X-Forwarded-For`와 `Forwarded`를 신뢰하지 않는다. 프록시 뒤에서는 모든 사용자가 프록시 IP의 제한을 공유하므로 별도의 신뢰 프록시 정책이 필요하다.
- 자체 JUnit 테스트는 설정 거절, Unicode/JSON 경계, 실제 Argon2id 검증, 가상 시계 만료·제한 창, 실제 내장 Tomcat HTTP의 origin·쿠키·CSRF·세션 무효화·절대 만료·제한 응답을 검증한다. 공통 API와 React 브라우저 적합성 검사는 저장소 공통 harness가 수행한다.

메모리 모드 사용자는 한 명이며 사용자 해시·세션·실패 기록은 프로세스 메모리에만 있다. 재시작하면 메모리 상태가 사라진다. PostgreSQL 모드는 같은 DB를 사용하는 인스턴스와 언어 간에 상태를 공유한다. 세션 수·peer 수의 별도 상한, TLS 종료와 운영 DB 권한·용량 정책은 제공하지 않는다. 적합성 테스트 통과는 운영 보안 감사 완료를 뜻하지 않는다.

## 버전과 API 근거

- [Spring Boot 3.5.16 시스템 요구 사항](https://docs.spring.io/spring-boot/3.5/system-requirements.html): Java 17 이상 지원 중 이 참조 구현의 빌드 대상은 Java 21이다. 공식 문서의 안정 유지보수 버전과 Maven Central 아티팩트를 확인하고 고정했다.
- [Spring Security Argon2](https://docs.spring.io/spring-security/reference/features/authentication/password-storage.html#authentication-password-storage-argon2): Bouncy Castle 기반 `Argon2PasswordEncoder`.
- [Apache Maven Wrapper](https://maven.apache.org/tools/wrapper/): Maven 및 wrapper 버전과 배포 체크섬 고정.
- [PostgreSQL JDBC](https://jdbc.postgresql.org/): 안정 릴리스 42.7.14 고정. [연결 문서](https://jdbc.postgresql.org/documentation/use/)의 JDBC URL·Properties와 유한 connect/socket timeout을 따른다.
- [RFC 9106 권장 매개변수](https://www.rfc-editor.org/rfc/rfc9106.html#section-7.4): 메모리 제약 환경의 Argon2id 매개변수.
