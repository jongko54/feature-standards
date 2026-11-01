# Java / Spring Boot 참조 구현

`browser-session-v1`의 Java 구현이다. Java 21 이상과 Maven wrapper를 사용한다. Spring Boot 3.5.16의 내장 Tomcat, Spring Security Crypto 6.5.11의 `Argon2PasswordEncoder`, Bouncy Castle 1.86을 사용한다. HTTP 동작의 기준은 [공통 명세](../../features/auth/specification.md)이다.

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

비데모 실행에는 `AUTH_USER_EMAIL`, `AUTH_USER_PASSWORD`, HTTPS `AUTH_ALLOWED_ORIGIN`이 필요하며 secure 쿠키를 끌 수 없다. 비밀번호를 시작 시 Argon2id로 해싱한다. 서버 상태에는 원문 비밀번호를 보관하지 않는다. 잘못된 설정은 포트를 열기 전에 거절한다. `AUTH_HOST`와 `AUTH_PORT`가 바인딩을 정한다.

다른 환경 변수는 `AUTH_SESSION_TTL_SECONDS`(1800), `AUTH_RATE_LIMIT_MAX`(5), `AUTH_RATE_LIMIT_WINDOW_SECONDS`(60)이며 양의 정수만 받는다. `AUTH_COOKIE_SECURE`는 기본 `true`, origin은 기본 `http://127.0.0.1:5173`이다. `false`는 명시적 데모의 loopback origin에서만 허용된다. 자세한 경계는 공통 명세를 따른다.

## 구현과 검증 범위

- Servlet filter가 메서드·경로·오류·캐시 헤더를 명시적으로 처리한다. Spring의 기본 로그인 화면이나 자동 CORS 응답을 추가하지 않는다.
- UTF-8 디코더는 잘못된 바이트를 거절한다. Jackson의 중복 키 검출과 추가 토큰 거절, 필드·Unicode surrogate·바이트 길이 검증을 함께 적용한다. 이메일은 ASCII 공백과 ASCII 대문자만 정규화한다.
- 32바이트 세션 ID와 독립 CSRF 토큰에 `SecureRandom`을 사용한다. CSRF는 JDK `MessageDigest.isEqual`로 비교한다. 로그인은 전달된 이전 세션만 교체하고 로그아웃은 서버 기록을 삭제한다. 조회는 절대 TTL을 늘리지 않는다.
- Argon2id는 64 MiB, 반복 3회, 병렬도 4, 솔트 16바이트, 출력 32바이트이다. 알 수 없는 계정도 동일한 해시를 검증한다. 동시 해시 검증은 직렬화한다.
- TCP peer IP로 실패를 제한한다. `server.forward-headers-strategy=none`으로 `X-Forwarded-For`와 `Forwarded`를 신뢰하지 않는다. 프록시 뒤에서는 모든 사용자가 프록시 IP의 제한을 공유하므로 별도의 신뢰 프록시 정책이 필요하다.
- 자체 JUnit 테스트는 설정 거절, Unicode/JSON 경계, 실제 Argon2id 검증, 가상 시계 만료·제한 창, 실제 내장 Tomcat HTTP의 origin·쿠키·CSRF·세션 무효화·절대 만료·제한 응답을 검증한다. 공통 API와 React 브라우저 적합성 검사는 저장소 공통 harness가 수행한다.

사용자는 한 명이며 사용자 해시·세션·실패 기록은 프로세스 메모리에만 있다. 재시작하면 세션과 실패 기록이 사라지고 여러 인스턴스가 상태를 공유하지 않는다. 만료 기록은 다음 인증 요청 때 정리한다. 세션 수와 peer 수의 별도 상한, 영속 사용자 저장소, TLS 종료, 분산 제한, 다중 인스턴스 운영 정책은 제공하지 않는다. 적합성 테스트 통과는 운영 보안 감사 완료를 뜻하지 않는다.

## 버전과 API 근거

- [Spring Boot 3.5.16 시스템 요구 사항](https://docs.spring.io/spring-boot/3.5/system-requirements.html): Java 17 이상 지원 중 이 참조 구현의 빌드 대상은 Java 21이다. 공식 문서의 안정 유지보수 버전과 Maven Central 아티팩트를 확인하고 고정했다.
- [Spring Security Argon2](https://docs.spring.io/spring-security/reference/features/authentication/password-storage.html#authentication-password-storage-argon2): Bouncy Castle 기반 `Argon2PasswordEncoder`.
- [Apache Maven Wrapper](https://maven.apache.org/tools/wrapper/): Maven 및 wrapper 버전과 배포 체크섬 고정.
- [RFC 9106 권장 매개변수](https://www.rfc-editor.org/rfc/rfc9106.html#section-7.4): 메모리 제약 환경의 Argon2id 매개변수.
