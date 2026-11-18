# React 개발 의존성 제거와 게시 재검증

11월 18일 첫 [검사 기록](security-remediation-2026-11-18.md)은 당시의
picomatch 발견과 게시 차단을 보존한다. 이번 재개에서는 공식 패치 대기 대신
두 데모 앱의 실제 빌드·개발 의존성을 교체했다. 취약점 제외나 임의 포크,
강제 override를 사용하지 않았다.

## 실제 의존성 교체

두 앱은 Vite 대신 공식 esbuild 0.28.2를 사용한다. 기존 dev/build/preview
명령, 5173·5174·4173 포트, SPA 계정 경로와 API 프록시를 유지한다.
프록시는 Origin·Host·Cookie·CSRF·body, 응답 status·Set-Cookie 배열과
cache/retry 헤더를 전달한다. SDK의 공개 API·UI 소스·인증 계약은 바꾸지 않았다.

개발 중 TSX/JavaScript/CSS 변경은 watch와 SSE를 통해 전체 새로고침한다.
React Fast Refresh와 같지 않으며 편집 중 React 메모리 상태는 초기화된다.
환경·HTML 설정을 바꾸면 재시작한다. dotenv와 mode/process 우선순위는
유지하고 공개 계정 flag만 번들에 넣는다. API target은 서버 설정이다.

정적 제공은 loopback과 생성물에 한정한다. 자식·실행 중 추가·dangling
symlink를 거절하고, 포트 점유 시 다른 포트로 옮기지 않는다. 정적 빌드 오류의
HTTP 응답은 소스 줄을 노출하지 않는다. API 오류 응답은 별도로 그대로 전달한다.

## 로컬에서 확인한 범위

- 새로운 실제 TCP·빌드·환경·watch·preview·종료 경계 검사 15개 통과.
- 기존 API 단위 검사 8개, 두 데모 앱 production build, 실제 SDK tarball의
  5개 파일·ESM·TypeScript 소비 검사 통과.
- 네 백엔드 공통 HTTP 76개와 실제 Chromium 32개, Secure cookie 검사 통과.
- 추가 4173 미리보기와 실제 Python 메모리 서버의 Chromium 8개 통과.
- 두 npm lockfile의 OSV 검사: manifest별 package 항목 125개, 발견 0건.

이 결과는 로컬 통합 tree의 근거다. 같은 소스의 원격 기능·보안 CI와 실제
레지스트리 다운로드를 확인해야 게시 완료로 판단한다. DB·가입·SMTP의
전체 회귀 검증은 원격의 전용 fixture 검사와 구분한다.

## Maven 검사 입력의 추가 보강

React 교체 뒤 첫 전체 스캔은 발견 0건이었지만, 미게시 auth 2.0.0을 참조하는
두 Java 소비 POM을 OSV의 레지스트리 기반 resolver가 해석하지 못해 exit 127로
실패했다. 이 실패를 성공으로 바꾸지 않는다.

이를 해결하기 위해 신뢰한 checkout의 네 Maven 프로젝트를 전용 repository와
빈 설정에서 실제 해결하고, 공식 고정 dependency plugin 결과를 SBOM으로
검사하는 경로를 구현했다. 원래 POM과 생성 SBOM의 해시·정확한 source alias로
출처를 연결한다. 미게시 Java SDK를 게시됐다고 표시하거나 검사 입력을
누락하는 방식은 사용하지 않는다. Java 2.0.0은 계속 별도 미게시 소스 후보다.

최종 로컬 통합 스캔(13:43:50–13:44:35 UTC)은 기준 HEAD
`4aa50ffaafc3de30a284ac7dd8b63e5c7b68033a`, `sourceDirty=true`에서 실행했다.
의존성 1,021개 manifest별 package 항목에서 발견 0건, 정적 소스 151개에서
발견·오류 0건, 시크릿 발견 0건으로 세 검사가 모두 통과했다. Maven 네
프로젝트는 각각 72/72, 12/12, 73/73, 74/74 identity·version이 일치했다.
빌드 플러그인과 JDK 내부는 이 dependency inventory의 범위 밖이다.

Python 저장소 검사 400개 중 367개가 통과하고 DB 등 환경 조건 33개는
건너뛰었다. main 카탈로그 Node 검사 52개가 통과했다. 정제한 수치는
[`security-remediation-2026-11-18-react-build.json`](security-remediation-2026-11-18-react-build.json)에
별도로 기록한다. 이는 원격 exact-SHA CI나 npm 게시 영수증이 아니다.

공식 근거: [esbuild API](https://esbuild.github.io/api/),
[개발 서버 앞단 프록시](https://esbuild.github.io/api/#customizing-server-behavior),
[live reload와 범위](https://esbuild.github.io/api/#live-reload),
[picomatch 권고](https://github.com/advisories/GHSA-fc5q-39xc-vjpf).
