# Java 소비 프로젝트

인증 코드를 복사하지 않고 `io.github.jongko54:java-spring-auth:1.0.0:jar:library`를 가져오는 별도 Maven 프로젝트다. 공개 `AuthConfig`, `AuthService`, `AuthFilter`를 조합하고 소비 앱의 `GET /api/profile`만 구현한다. JDK 21 이상을 사용한다.

## 설치·검증

저장소 루트에서 실행한다. 첫 명령은 참조 구현의 일반 라이브러리 JAR를 **로컬 Maven 캐시**에 설치한다. Maven Central에 게시하는 명령이 아니다. 두 번째 프로젝트는 소스 디렉터리나 참조 서버의 `target/classes`를 classpath에 직접 추가하지 않는다.

```sh
implementations/java-spring/mvnw -f implementations/java-spring/pom.xml -q install -DskipTests
implementations/java-spring/mvnw -f examples/consumer-java/pom.xml -q test
implementations/java-spring/mvnw -f examples/consumer-java/pom.xml -q package -DskipTests
```

테스트는 실제 loopback Tomcat 서버와 Java HTTP 클라이언트를 사용한다. 일반 JAR에서 클래스가 로드되는지, 미인증·위조 쿠키의 401, 로그인 후 보호 API의 사용자, 잘못된 CSRF 뒤 세션 보존, 로그아웃 후 복사해 둔 쿠키의 거절을 검사한다. 별도 실패 저장소를 주입해 보호 API가 일반 503으로 닫히는지도 검사한다. 테스트 프로필은 메모리 v1이며 DB를 만들거나 변경하지 않는다.

## 로컬 실행

```sh
AUTH_DEMO=true AUTH_COOKIE_SECURE=false \
  java -jar examples/consumer-java/target/consumer-java.jar
```

기본 주소는 `http://127.0.0.1:8000`이다. `/auth/*`와 `/healthz`는 라이브러리의 `AuthFilter`, `/api/profile`은 소비 앱의 controller가 소유한다. 프록시 헤더를 신뢰하지 않으며 인증 응답·보호 API에는 `Cache-Control: no-store`를 사용한다. `AuthService.session(cookieToken)`이 반환한 세션만 사용자로 인정하고, 저장소 장애는 일반 503으로 반환한다. 데모 암호·쿠키 예외는 공개 로컬 예제에만 사용한다.

`AUTH_PORT`로 소비 서버 포트를 선택한다. `AUTH_ALLOWED_ORIGIN`은 브라우저가 실제 사용하는 origin과 정확히 맞춰야 한다. 기존 React 클라이언트의 Vite `AUTH_API_TARGET`을 이 서버 주소로 지정하면 같은 `/auth` API를 사용할 수 있지만 이 Java 예제 자체에는 화면이 없다.

## 저장소와 계정 프로필

- 기본 메모리 v1은 공개 데모 사용자 한 명과 프로세스 세션을 사용한다. 재시작하면 세션이 사라진다.
- 미리 이관한 전용 schema-1 DB와 `AUTH_STORE=postgres AUTH_DATABASE_URL=...`를 제공하면 같은 `AuthService.create`가 PostgreSQL v2를 선택한다.
- 미리 schema 2로 이관하고 `AUTH_ACCOUNT_LIFECYCLE=true`를 추가하면 v3 가입·이메일 확인·비밀번호 재설정을 사용한다. SMTP 전달은 공통 선택 워커의 별도 설정이다.

앱은 자동 DDL·seed·메모리 fallback을 하지 않는다. DB 준비와 프로필 선택은 [PostgreSQL 안내](../../docs/postgres-v2.md), [계정 안내](../../docs/account-v3.md)를 따른다. 소비 테스트 통과는 v2/v3 소비 앱 런타임이나 운영 DB·메일 발송을 검증했다는 뜻이 아니다. 해당 백엔드의 v2/v3 공통 검증은 저장소의 별도 harness가 맡는다.

이 예제는 저장소 내 로컬 artifact를 사용한다. 원본 커밋은 `git rev-parse HEAD`로 기록하고, 업데이트 후 같은 테스트와 대상 앱의 검증을 실행한다. 레지스트리 게시나 운영 보안 감사 완료를 의미하지 않는다.

## Database consumer validation

The separate [consumer profile matrix](../consumer-python-react/PROFILE_TESTS.md) now builds and runs this application against PostgreSQL v2 and v3, using unique disposable databases and the shared consumer React UI. The four-backend matrix passed eight backend/profile combinations and 28 Chromium scenarios locally on 2026-11-03. This is additional runtime evidence; the unit tests described above still target memory v1. See the [validation record](../../docs/validation-reuse-2026-11-03.md).
