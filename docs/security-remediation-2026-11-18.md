# Spring 7·native 검사 엔진 전환 결과 (2026-11-18)

Java와 검사 엔진의 이전 차단 원인을 해결했다. 다만 새로 갱신된
`picomatch` 보안 권고 때문에 `feature-standards@0.4.0` 게시는 여전히 차단된다.
이 문서와 [정제한 기록](security-remediation-2026-11-18.json)은 로컬 통합 검증의
근거이며, 같은 커밋의 성공한 원격 CI나 npm 게시 영수증을 대신하지 않는다.

## 변경 범위

- Java 21을 유지하고 Boot 4.1.2 / Framework 7.0.10으로 전환했다. 실제 Maven
  의존성 트리에서 Security 7.1.2, Jackson 3.1.7, Tomcat 11.0.27을 확인했다.
  중복·후행 JSON과 잘못된 UTF-8 거절, 세션·CSRF·오류 계약을 유지했다.
- Java 인증은 플랫폼 호환성 변경을 표시하는 **2.0.0 소스 후보**다. 소비 앱과
  생성 템플릿도 같은 플랫폼을 사용한다. 과거 Maven 1.0.0과 core 0.1.0 게시
  기록은 보존했으며, Maven 재게시는 수행하지 않았다.
- Semgrep의 Python 환경을 공식 native OpenGrep 2.0.0으로 교체했다. macOS와
  Linux 릴리스 파일의 SHA-256을 고정하고, 크기 상한·새 디렉터리·실패 시
  차단을 유지했다. 기존 12개 규칙과 5개 언어의 양성·음성 fixture가 실제
  엔진으로 통과했다. OSV·Gitleaks·동일 SHA 게시 게이트는 유지했다.

## 확인한 결과

11월 18일 02:06 UTC의 로컬 통합 검사는 수정 중인 tree에서 실행했다.
기준 HEAD는 `d025d1c423b9a97d7fe90b23ffef431832c4b8a0`, `sourceDirty=true`다.
18개 의존성 입력에서 5개 생태계의 920개 manifest별 package 항목을 검사했다.

| 항목 | 결과 |
|---|---|
| 의존성 | 2회 발견 / 1개 고유 advisory·package·version 조합 |
| 정적 검사 | 소스 148/148개, 발견·오류 0 |
| 시크릿 검사 | 현재 파일 및 Git 이력, 발견 0 |
| Python 저장소 검사 | 387개 중 354개 통과, DB 등 환경 조건 33개 건너뜀 |
| Java 인증 | 88개 중 71개 통과, DB 조건 17개 건너뜀 |
| Java 코어·소비 앱 | 코어 5개, 인증 소비자 4개, 코어 HTTP 9개 통과 |
| Java 공통 HTTP·브라우저 | HTTP 19개, 실제 Chromium 8개 통과 |
| 생성 Java 앱 | 인증 6개, 세 기능 12개 HTTP·SDK 출처 검사 통과 |
| Node CLI·게시 보호 | main 52개, auth 생성기 14개, 게시/registry 회귀 30개 통과 |
| 실제 tarball | 설치·26개 context·공개 Node API smoke 통과; registry 게시 아님 |

11월 14일에 남았던 Spring 2개와 검사 도구 6개의 고유 조합은 이번 inventory의
발견 목록에 없다. native 스캐너 내부에 포함된 의존성은 소스 manifest 검사가
열거하지 않으므로 도구의 내부 의존성까지 취약점이 없다고 해석하지 않는다.
과거와 현재의 도구·입력 범위 차이도 유지한다.

## 남은 게시 차단 원인

`GHSA-fc5q-39xc-vjpf` / `CVE-2026-112366`은 반복 extglob으로 인한
ReDoS 권고다. `picomatch 4.0.7`이 React 클라이언트와 Python/React 소비자의
개발용 Vite 의존성에 각각 존재한다. 사용자 입력을 통한 실제 악용 가능성을
이 검사로 입증한 것은 아니며, 현재 저장소의 게이트는 개발 의존성도 검사한다.

11월 18일 확인한 npm latest는 picomatch 4.0.7이다. 공식 권고는 패치 버전을
제시하지 않으며 최신 Vite 8.3.8과 tinyglobby 0.2.17도 이 의존성을 사용한다.
따라서 단순한 지원 버전 업데이트로 제거할 수 없었다. 제외·무시·임의 포크나
지원하지 않는 override를 추가하지 않았다. 자동 게이트를 우회하는 직접 게시와
릴리스 태그 생성도 수행하지 않는다. npm의 마지막 확인된 버전은 0.3.2다.

공식 패치가 나오면 두 lockfile을 지원 범위에서 갱신하고 React 빌드·브라우저,
전체 보안 검사와 동일 SHA의 기능/보안 CI를 확인한 뒤 0.4.0 게시를 재개한다.

근거: [Spring Boot 4 전환 안내](https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-4.0-Migration-Guide),
[Spring SSE 권고](https://spring.io/security/cve-2026-47890/),
[Spring XsltView 권고](https://spring.io/security/cve-2026-47884/),
[OpenGrep 2.0.0](https://github.com/opengrep/opengrep/releases/tag/v2.0.0),
[picomatch 공식 권고](https://github.com/advisories/GHSA-fc5q-39xc-vjpf),
[picomatch 릴리스](https://github.com/micromatch/picomatch/releases),
[npm picomatch metadata](https://registry.npmjs.org/picomatch/latest).
