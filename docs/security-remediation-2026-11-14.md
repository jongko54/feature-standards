# 의존성 보안 패치와 CI 복구: 2026-11-14

호환 가능한 런타임 의존성 패치를 적용해 **고유 경고 조합을 30개에서 8개로
줄였다.** 남은 8개 때문에 보안 게이트는 계속 실패한다. 경고를 무시하거나
정책을 약화하지 않았으며, 전체 취약점 부재나 운영 보안 검증 완료를 주장하지
않는다. [기계 판독용 결과](security-remediation-2026-11-14.json)를 함께 제공한다.

## 측정 기준

- 변경 전: 깨끗한 `d68593e5b73a811f2cd9c1bedeafdeba4f331d5c` 소스를
  11월 14일에 재검사했다. manifest 발생 75건, 고유 조합 30개였다.
- 변경 후: 깨끗한 `66482364d56cef473508ac1df3d20dfe4f43db23` 소스에서
  같은 도구·정책으로 실제 전체 검사를 실행했다. 발생 12건, 고유 조합 8개다.
- 고유 조합은 `(advisory ID, ecosystem, package, version)`이다.
  22개 감소는 확인된 애플리케이션 공격 22개를 재현·해결했다는 뜻이 아니다.
- [11월 11일 기록](security-baseline-2026-11-11.md)의 29개는 당시 결과로
  유지한다. 같은 소스를 재검사해도 이후 공개된 advisory로 결과가 달라진다.

## 적용한 호환 패치

| 대상 | 변경 |
| --- | --- |
| Go 암호 라이브러리 | `golang.org/x/crypto` 0.58.0 → 0.59.0 |
| Go 관련 모듈 | `x/sync` 0.25.0, `x/sys` 0.50.0, `x/text` 0.44.0으로 resolver가 갱신 |
| Rust 암호 유틸리티 | `ctutils` 0.4.2 → 0.4.8 |
| Java Jackson BOM | 2.21.4 → 2.21.8 |
| Java Tomcat | 10.1.55 → 10.1.61 |
| Java Log4j | 2.24.3 → 2.25.5 |
| Java 소비 앱의 JDBC 관리 버전 | 42.7.11 → 42.7.14; 원본 인증 SDK의 직접 버전 42.7.14는 유지 |

원본 SDK뿐 아니라 실제 소비 예제와 새 앱 생성 템플릿에도 적용했다.
Java에서는 Maven의 실제 dependency tree를 별도로 생성해 Jackson·Tomcat·
Log4j·JDBC가 위 버전으로 선택됨을 확인했다. OSV의 추론 그래프와 실제
classpath 근거를 구분한다. Spring Boot 3.5/Spring 6.2, 공개 API, HTTP 프로필,
DB 스키마는 유지한다.

변경은 미게시 소스 패치다. 기존 npm·PyPI·crates.io·Maven 패키지나 Go 태그를
새로 게시하지 않았고, 이미 설치된 소비 앱이 자동 업데이트되지 않는다.

## 실제 검증

| 검사 | 결과 |
| --- | --- |
| 전체 보안 검사 | 의존성 8개 조합으로 실패; 정적 규칙·시크릿 검사는 통과 |
| Go 인증 SDK와 두 소비 앱 | race 테스트 통과; 인증 SDK vet 통과 |
| Rust 인증 SDK | 단위 24개·통합 3개 통과; DB/TLS fixture 전용 3개는 로컬에서 미실행 |
| Java 인증 SDK | 88개 중 71개 통과·17개 DB 환경상 건너뜀, 오류·실패 0개 |
| 네 백엔드 공통 HTTP | 각 19개, 총 76개 통과 |
| 네 백엔드 실제 브라우저 | 각 8개, 총 32개 통과 |
| 세 기능 HTTP 소비 앱 | Python·Go·Java·Rust 모두 통과 |
| 생성 앱 | 소스 CLI 4개 + 실제 tarball 설치 CLI 4개 모두 통과 |
| 카탈로그 회귀 | Node 52개 통과 |
| 저장소 Python 회귀 | 369개 중 336개 통과·33개 환경상 건너뜀 |
| 릴리즈 게이트·레지스트리 회귀 | 하위 사례 포함 Node 30개 통과 |

로컬의 메모리 프로필·브라우저 결과를 전체 DB·SMTP·원격 CI 통과로 확대하지
않는다. 해당 커밋의 전체 결과는
[기능 workflow](https://github.com/jongko54/feature-standards/actions/workflows/ci.yml)와
[보안 workflow](https://github.com/jongko54/feature-standards/actions/workflows/security.yml)에서
커밋을 대조해 확인해야 한다.

## 남은 8개 경고와 차단 사유

| 그룹 | 고유 조합 | 남기는 이유 |
| --- | --- | --- |
| Spring MVC 6.2.19 | 2개 | 6.2.20 보안 패치는 Enterprise 전용이다. 공개 패치는 Spring 7.0.9 이상이며 별도 호환성 검토가 필요하다. |
| 보안 검사 도구의 MCP 1.29.0 | 4개 | Semgrep 1.185.0이 이 버전을 정확히 고정한다. 상위 패키지 제약을 무시한 강제 override는 하지 않았다. |
| 보안 검사 도구의 OpenTelemetry API 1.37.0 | 2개 | Semgrep/SDK가 1.37 계열을 요구하며, 공개 수정 버전 1.45.2와 호환되는 도구 업데이트가 필요하다. |

Spring advisory의 SSE·XsltView 사용 조건은 일반 JSON API의 취약성 확정과
구분해야 한다. 다만 재사용 라이브러리의 소비 앱 전체를 평가한 것이 아니므로
`not_affected` 예외를 추가하지 않는다. 검사 도구의 경고도 운영 런타임과
분리해서 기록하되 삭제하지 않는다. 자동 게시 차단은 유지한다.

다음 범위는 Spring 7 지원의 호환성 설계, 또는 지원되는 보안 도구 업데이트/
교체다. 기존 ASVS의 비밀번호 차단 목록·쿠키 접두사·필드별 권한 공백과
독립 보안 감사도 이번 의존성 패치로 해결됐다고 간주하지 않는다.

## 반복된 CI 환경 오류

이전 기능 CI `43033112046`의 두 실행은 Playwright OS 의존성 설치 중
`azure.archive.ubuntu.com`의 DNS 해석 오류로 실패했다. React 코드 검사와
환경 오류를 분리했다. GitHub Ubuntu runner의 APT mirror 파일을 Canonical의
공식 HTTPS archive로 지정하고 재시도·대기를 제한하는 수정
`679602472c5627b802d6927c343cfb78430dbee9`를 먼저 push했다.

그 [원격 실행](https://github.com/jongko54/feature-standards/actions/runs/43604423762)은
이전 실패 지점을 지나 브라우저 검사를 실행했다. 이는 환경 수정의 근거이며,
뒤이어 변경한 의존성 소스의 전체 원격 검증을 대신하지 않는다. TLS나 APT
패키지 서명 검증을 끄거나 브라우저 검사를 생략하지 않았다.

근거: [Spring SSE advisory](https://spring.io/security/cve-2026-47890/),
[Spring XsltView advisory](https://spring.io/security/cve-2026-47884/),
[Semgrep 1.185.0 배포 메타데이터](https://pypi.org/pypi/semgrep/1.185.0/json),
[GitHub runner APT 구성](https://github.com/actions/runner-images/blob/main/images/ubuntu/scripts/build/configure-apt-sources.sh).
