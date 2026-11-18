# React 개발 도구 교체와 0.4.0 게시 재개

## 원인과 범위

공식 picomatch 최신 버전 4.0.7에 패치가 없고 최신 Vite 8.3.8도 이를 직접
사용한다. 두 데모 앱의 실제 개발 의존성을 제거하기 위해 Vite 대신 공식
esbuild 0.28.2의 build/watch/serve와 loopback Node 프록시를 사용한다.
인증 SDK의 공개 API·서버 계약·UI 동작·게시 게이트는 유지한다. 임의 포크,
취약점 제외와 강제 dependency override는 사용하지 않는다.

Fast Refresh 대신 코드 변경 시 전체 페이지를 새로고침한다. 이 개발 경험의
차이를 명시한다. Node 22.12+, 기존 dev/build/preview 명령과 포트, 공개
계정 flag 및 환경 파일 우선순위를 보존한다. 새 운영용 서버를 추가하지 않는다.

## 실행 순서

1. 실제 TCP fixture로 프록시·정적 제공·환경·종료 경계를 검사한다. API의
   Origin/Host/Cookie/CSRF/body 및 응답 status/Set-Cookie/cache/retry 헤더를
   보존하고, API 오류를 SPA HTML로 바꾸지 않는다.
2. esbuild 내장 서버에는 생성물 디렉터리와 loopback만 제공한다. 정적 서버가
   소스 checkout·환경 파일을 제공하지 않는지, 잘못된 Host·포트 점유·잘못된
   인자가 실패하는지 확인한다. 계정 flag 외 환경 값은 번들에 넣지 않는다.
3. 두 앱의 공식 의존성과 lockfile을 실제 resolver로 갱신한다. SDK 빌드·타입
   검사·단위 테스트·v1 브라우저·preview·watch 검사와 관련 소비 앱을 검증한다.
   CI의 기존 React 단계에 새 경계 검사를 추가하고 mirror를 맞춘다.
4. 전체 보안 스캔을 실행해 원래 picomatch 발견이 제거되고 새 오류·누락이
   없는지 확인한다. 합친 변경을 독립 검토하고 카탈로그·tarball을 검사한다.
5. 검증한 변경을 main에 푸시한다. 같은 정확한 SHA에서 기능 CI와 보안 CI가
   모두 성공한 뒤 기존 OIDC 워크플로로 `feature-standards@0.4.0`을 게시한다.
6. 실제 npm metadata·다운로드 integrity·새 설치 환경의 context/CLI 결과를
   확인한다. Java 2.0.0과 Python core 0.2.0의 별도 미게시 SDK 상태는 유지한다.

## 완료와 기록

로컬 fixture, 실제 브라우저, 원격 기능·보안 CI, registry 게시는 각각 별도
근거로 기록한다. 과거 11월 18일 첫 검사와 그때의 차단 기록은 수정하지 않는다.
모든 게시 조건을 통과하기 전에는 태그·직접 게시로 게이트를 우회하지 않는다.

## 전체 검사에서 확인한 추가 원인

React 교체 후 로컬 전체 스캔은 취약점 발견 0건이지만 OSV가 미게시 Java
auth 2.0.0을 사용하는 두 소비 POM의 레지스트리 해석에 실패해 exit 127로
차단됐다. 이 결과를 성공으로 바꾸지 않는다. 네 Maven 프로젝트를 전용
repository·빈 설정에서 실제 빌드/해결하고, 고정한 공식 dependency plugin의
결과로 SBOM을 생성해 검사한다. 원래 POM 해시, 생성 SBOM 해시와 정확한
source alias를 연결한다. Java 2.0.0을 게시된 패키지로 가장하거나 입력을
누락하지 않는다. 검사는 신뢰한 checkout의 빌드 코드를 실행하는 범위다.

## 로컬 수용 기준 확인

프록시/빌드 회귀 15개, 기존 API 8개, 실제 네 언어 HTTP 76개와 브라우저
32개, preview의 실제 브라우저 8개를 통과했다. 전체 보안 검사는 Maven
identity 4개 집합의 완전 일치를 포함해 1,021개 package 항목·소스 151개·
시크릿 검사 모두 통과했다. Python은 400개 중 367개 통과/33개 환경상
건너뜀, main 카탈로그 Node 52개 통과다. 원격 exact-SHA 검증과 실제 게시는
이 로컬 결과와 구분해 다음 단계에서 확인한다.
