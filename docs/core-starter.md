# 세 기능을 연결한 SDK starter

현재 소스 후보의 main CLI는 인증·권한·목록을 함께 연결한 새 프로젝트를 생성한다. Python/FastAPI, Go/net/http, Java/Spring Boot, Rust/Axum을 지원한다. 선택은 `browser-session-v1` + `rbac-v1` + `offset-list-v1`이다. 기존 인증 전용 `init --feature auth`와 v1/v2/v3 검사는 유지된다.

```sh
node packages/feature-standards/src/cli.mjs init --template core \
  --source "$PWD" --stack python \
  --dest /absolute/physical/path/outside-the-checkout/new-core-app

cd /absolute/physical/path/outside-the-checkout/new-core-app
node project.mjs check
node project.mjs demo
```

Node 22.12+와 선택 언어의 도구가 필요하다. Python은 3.12+와 uv, Go는 1.26+, Java는 JDK 21+와 checkout의 Maven wrapper, Rust는 1.93.1+와 Cargo를 사용한다. Java 도구 선택은 `JAVA_HOME`으로 명시할 수 있다. 새 기능을 지원하는 source checkout을 명시해야 하며, main package는 `featureStandards.coreStarterProtocolVersion: 1` capability를 검사한다. 생성만으로 의존성 설치·빌드·서버·DB 작업을 실행하지 않는다. `--check` 또는 `check --project`는 생성 앱의 신뢰한 코드와 빌드 도구를 명시적으로 실행한다. 이 기능은 소스 후보이며 기존 npm 0.3.2의 기능이나 새 registry 게시 기록이 아니다.

## 무엇이 생성되는가

생성 앱은 `/api/profile`, `/api/documents`, `/api/documents/{id}`를 제공한다. 실제 SDK 인증 세션 → 현재 서버 신뢰 멤버십 → 명시 권한 정책 → tenant/owner 가시성 → 원본 query와 schema → 목록 응답으로 연결한다. 공개 문서에는 `id/name/score/active`만 반환한다. 사용자의 요청 header·body·query가 역할·tenant·주체를 지정하지 못한다.

인증·코어 SDK 본체는 복사하지 않는다. Python의 uv source, Go의 replace, Rust의 Cargo path, Java의 source POM overlay가 명시 source checkout을 참조한다. Java의 두 라이브러리 빌드 출력·Maven repository는 생성 앱 내부에 둔다. 상대 배치를 바꾸면 dependency manifest와 `feature-core.json`의 경로도 함께 검토해야 한다.

출처 metadata는 생성기·검사 프로토콜, 세 기능과 프로필, stack, 상대 source/SDK 경로, source Git commit과 네 catalog 파일 해시를 기록한다. source 내용은 참조이며 불변 vendoring이나 자동 업데이트가 아니다. 기록 후 catalog가 달라지면 검사는 거부한다. 소스 Git commit만으로 미커밋 변경까지 고정했다고 해석하지 않는다.

## 일반 실행과 샘플 실행

`node project.mjs start`는 `.env.example`의 설정을 사용자가 직접 export한 뒤 실행한다. `.env`를 자동으로 읽지 않으며 Secure cookie와 non-demo memory 인증이 기본이다. 기본 membership은 거부하고 샘플 문서를 공개하지 않는다. 인증이 성공해도 문서 접근은 403이다. 실제 서비스의 현재 멤버십과 문서 저장소를 내부 provider에 연결하고 명시 정책을 정의해야 한다.

`node project.mjs demo`만 loopback HTTP·샘플 계정·샘플 문서·viewer 권한을 명시적으로 연결한다. 샘플 사용자를 운영 계정으로 취급하지 않는다. core starter는 DB 세션·가입·메일·UI·정책 관리 기능을 추가하지 않는다. 이 기능이 필요하면 인증의 별도 프로필과 애플리케이션 통합을 선택한다.

## 생성된 앱의 검사

```sh
feature-standards check --project /absolute/physical/path/to/new-core-app
# Or, inside the generated app:
node project.mjs check
```

검사는 일반 실행의 기본 거부와 명시 demo 동작을 각각 확인한다. 새 loopback 프로세스에서 anonymous/forged session, 로그인과 동일 주체, 독립 세션, Origin·CSRF, owner·tenant 격리, 가시성 적용 후 total, typed filter/sort/page, 잘못된 raw query, logout 후 복사 cookie 거부를 검사한다. SDK 의존성 출처도 별도로 확인한다. 성공 영수증에는 세 프로필, 고정된 필수 검사 이름과 두 SDK 출처가 담기며 인증만 검사한 영수증은 core 성공으로 수용하지 않는다.

검사 환경은 상속된 AUTH/PORT/DB/계정 설정과 분리하고 memory/v1을 강제한다. DB 연결·SQL·SMTP를 실행하지 않으며 자신의 프로세스와 작업 소유 fixture만 정리한다. 기존 프로젝트·목적지·symlink·source 내부 목적지는 거부한다. 검사 실패 후 생성 앱은 확인할 수 있게 남는다.

네이티브 의존성 검사와 HTTP 검사는 SDK 연결·동작의 근거이며 보안 감사·브라우저 UI·운영 배포·AI 채택률·토큰 절감률의 증명이 아니다. 기존 AI 실험 원본은 바꾸지 않는다. 새로운 starter를 AI가 실제로 더 많이 선택하는지는 별도 비교 실험이 필요하다.

[SDK 연결 카드](ai-entry/README.md), [공통 코어 계약](core-standards.md), [기존 인증 생성기](create-feature-auth.md)를 함께 참고한다.
