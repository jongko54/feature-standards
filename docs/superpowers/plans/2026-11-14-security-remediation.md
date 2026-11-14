# 보안 경고 호환 패치와 CI 복구

## 목표와 범위

현재 `main`/원격을 확인하고 먼저 push한 다음, 남은 의존성 보안 경고의
공식 영향 범위와 공개 패치를 확인해 호환 가능한 업데이트를 적용한다.
기존 API·인증 프로필·DB 스키마를 유지한다. npm/PyPI/crates.io/Maven 게시,
유료 지원 구매, 계정 권한 변경과 운영 배포는 수행하지 않는다.

## 확인한 출발점

- 시작 커밋 `d68593e5b73a811f2cd9c1bedeafdeba4f331d5c`는 원격과 같고
  작업 트리가 깨끗하다. `git push origin main`은 up-to-date였다.
- 기존 기능 CI `43033112046` attempt 2도 Playwright OS 의존성 설치 중
  `azure.archive.ubuntu.com` DNS 오류로 실패했다. React 자체 검사와 구분한다.
- 2026-11-14 새 실제 검사에서는 75건의 manifest 발생, 고유 30개
  advisory/ecosystem/package/version 조합을 관찰했다. 과거 29개 기록은 보존한다.

## 순서

1. GitHub Ubuntu runner의 APT mirror 파일을 Canonical의 공식 HTTPS
   archive로 지정하고 APT 재시도/대기 시간을 제한한다. 시스템 패키지 서명
   검증과 브라우저 검사는 유지한다. 워크플로와 `ci/` 사본을 함께 검증해
   먼저 커밋·push하고 실제 CI에서 기존 환경 실패 구간을 확인한다.
2. Go `x/crypto`, Rust `ctutils`, Java의 Jackson/Tomcat/Log4j/JDBC에서
   공개된 호환 패치를 확인해 원본 SDK, 소비 예제와 생성 템플릿을 갱신한다.
   Maven은 추론 그래프와 실제 resolved classpath를 각각 확인한다.
3. 기존 Semgrep 1.185.0의 MCP/OpenTelemetry 고정 제약과 Spring 6.2의
   공개 패치 부재를 명시한다. 지원되지 않는 강제 의존성 override, 취약점
   무시 또는 Spring 7로의 조용한 호환성 변경은 하지 않는다.
4. 실제 scanner로 전후 결과를 비교하고, 런타임 자체 테스트·공통 HTTP·
   브라우저·DB·생성 앱 검사를 해당 소스에 대해 실행한다. 환경 실패와
   코드 실패를 구분하고 새 경고도 결과에 포함한다.
5. 날짜·커밋·변경 버전·범위·실제 결과와 남은 차단 사유를 새 보고서에
   기록하고 README의 최신 보고서 포인터를 갱신한다. 변경을 push하고
   원격 ref/CI를 확인한다. 보안 게이트는 발견 사항이 남으면 실패를 유지한다.

## 검증

설정 변경은 Actionlint, YAML/셸 구문, workflow 사본 일치와 실제 원격 실행으로
검증한다. 잠금 파일은 해당 언어의 resolver와 frozen/locked build로 검증한다.
보안 도구 자체의 실패/시크릿 검출 회귀는 기존 `test_security_*`, scanner
self-test와 실제 전체 검사를 재사용한다. 계약/API를 바꾸지 않는 버전 수정에
구현을 복제하는 인위적인 단위 테스트는 추가하지 않는다.

성공은 지원 가능한 패치 적용과 검증 결과의 공개이며, 알려진 경고를 지우기
위해 정책을 약화시키거나 ASVS 인증·취약점 부재를 주장하지 않는다. 패치가
없는 항목의 메이저 마이그레이션은 별도 호환성 범위로 남긴다.
