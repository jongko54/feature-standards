# AI 통합·패키지 재사용 검증 (2026-11-03)

## 결과와 범위

Python·Go·Java·Rust 각각 baseline/skill 조건 한 번씩, 총 8회 실제 Codex 통합이 독립 HTTP 검사 19개를 모두 통과했다. 새 조건 4회 모두 실행 명령에서 스킬과 manifest 경로 참조가 관측됐다. **통합 가능성은 확인했고 시간·토큰 절감 효과는 입증하지 못했다.** 세 언어에서는 새 조건의 시간이 더 길었고, 입력 토큰도 대체로 증가했다. 다음 문맥 개선은 스택·v1이 이미 정해진 작업에서 중복 문서·전체 manifest 탐색을 줄이는 방식으로 비교할 수 있다.

소스는 clean commit `61185fa05b65211ef3ba8e7a31aa1235c196c08b`, CLI는 `codex-cli 0.166.0`, 실행 환경은 macOS arm64·Python 3.13.13이다. 모델은 CLI 기본값을 사용했으며 trace에 모델 ID가 없어 `null`로 기록했다. 모델 ID를 추정하거나 특정 모델의 성능이라고 표현하지 않는다.

## 실제 모델 실행

[기계 판독 결과](../evals/auth/results/2026-11-03-smoke.json)에 시간·명령 수·토큰·출처·snapshot hash를 기록했다. 모든 snapshot의 구현 디렉터리 바이트 hash가 같고, source_dirty=false 및 source_unchanged=true다. baseline은 기존 루트 문맥, skill은 새 자동 발견 스킬·manifest를 제공하며 패키지 코드·소비 예제는 같다.

| 스택 | 조건 | HTTP | 모델 구간 초 | 전체 초 | 명령 수 | 입력 토큰 | 캐시 입력 | 출력 토큰 |
|---|---|---|---:|---:|---:|---:|---:|---:|
| python | baseline | 19/19 | 40.2 | 42.2 | 5 | 145,627 | 112,896 | 1,298 |
| python | skill | 19/19 | 54.4 | 57.6 | 5 | 156,968 | 103,808 | 1,939 |
| go | baseline | 19/19 | 57.1 | 58.4 | 5 | 230,451 | 210,944 | 1,962 |
| go | skill | 19/19 | 50.9 | 52.5 | 7 | 230,198 | 204,672 | 1,986 |
| java | baseline | 19/19 | 80.3 | 104.5 | 5 | 170,119 | 149,376 | 3,553 |
| java | skill | 19/19 | 94.4 | 118.9 | 7 | 242,942 | 216,704 | 3,720 |
| rust | baseline | 19/19 | 40.5 | 52.8 | 4 | 123,662 | 99,712 | 1,862 |
| rust | skill | 19/19 | 52.2 | 61.9 | 5 | 200,107 | 158,720 | 2,111 |

입력 토큰은 CLI가 각 모델 호출에서 보고한 합계이며 캐시 입력을 포함한다. 캐시 입력은 입력의 부분집합으로 별도 표시했다. 모델 구간은 CLI 실행 시간, 전체 시간은 snapshot·모델·빌드·HTTP 검사를 포함한다. 같은 호스트에서 조건을 병렬 실행했고 compiler·dependency·prompt cache와 부하를 통제하지 않았다. 조건별 n=1이며 통계적 개선이나 언어 간 모델 성능 순위를 판단할 수 없다.

각 실행은 다음 명령에서 스택·조건·새 출력 디렉터리를 바꿔 수행했다. Python/Go는 300초, Java/Rust는 360초 상한을 사용했고 JDK 21의 JAVA_HOME/PATH를 전달했다.

```sh
mkdir -p eval-results
uv run --frozen --project tools python tools/auth_eval.py --stack python --condition baseline --timeout 300 --output eval-results/python-baseline-2
uv run --frozen --project tools python tools/auth_eval.py --stack python --condition skill --timeout 300 --output eval-results/python-skill-2
```

기존 출력은 덮어쓰지 않으므로 재실행할 때 새 경로를 쓴다. 앞선 Python pilot 2회도 통과했지만 catalog 참조 파일을 snapshot에 포함하는 수정 전이므로 위 8회 집계에서 제외했다. 실제 사용 중 발견한 snapshot 누락은 재현·회귀로 보완했다.

평가는 메모리 v1 보호 API 통합이다. React의 모델 통합 과제와 v2/v3·SMTP 모델 과제는 측정하지 않았다. import·공개 API 사용·전체 인증 파일 복사 검사는 보조 근거이며 부분 복제나 임의 코드를 완전히 검증하지 않는다. raw trace·생성물·로그는 ignored `eval-results/`에만 보관하고 위 JSON에는 선택한 비밀 없는 지표만 남겼다.

## 결정적 검사와 참조 구현

| 검사 | 실제 결과 |
|---|---|
| catalog | 5개 스택·3개 프로필 경로/환경/이관/좌표/공개 심볼 연결, 회귀 15개 통과 |
| 평가 도구 | 19개 unit 통과: 가짜 구현 거절, snapshot 실제 catalog 조회, 경로/링크/출처/토큰 누락/timeout과 관찰된 별도 session 자식 종료 |
| 루트 unittest | 102개 중 69개 통과, DB 설정 없는 33개 skip; 전체 통과로 표현하지 않음 |
| Python 자체 | 87개 통과, 전용 DB 설정 없는 12개 skip |
| Go 자체·소비 앱 | race·vet·build 통과, 소비 HTTP 2개 및 외부 저장소 오류 회귀 통과 |
| Java 자체·소비 앱 | 자체 71개 통과·DB 없는 17개 skip, 일반 library JAR 실제 로드·소비 HTTP 4개·실행 JAR smoke 통과 |
| Rust 자체·소비 앱 | 자체 24개 통과·fixture 3개 ignored, 소비 1개·공개 helper 실패 회귀 3개 통과; fmt/clippy/build 통과 |
| React | API unit 8개·TypeScript/Vite 빌드 통과 |
| v1 참조 서버 4종 | 공통 HTTP 19개씩·Secure cookie 및 React 브라우저 8개씩 통과 |
| v2 참조 서버 4종 | 공통 HTTP·Secure cookie·브라우저, 혼합 상태 8개·각 2-instance/재시작 검사 통과 |
| v3 참조 서버 4종 | 기존+계정 HTTP 총 126개·계정 브라우저 총 12개 통과 |
| 정적 계약·문서 | v1/v2/v3 OpenAPI·generator drift, 메일 46개 source 맵, 스킬 frontmatter/자동 발견 symlink, 로컬 링크·YAML·CI 템플릿 동일·diff 검사 통과 |

로컬 공통 실행은 다음과 같다. JDK 21과 실제 서버 바이너리가 포함된 PostgreSQL 18 bin 경로를 환경으로 지정했다. libpq의 initdb만 있는 경로는 사용할 수 없다.

```sh
uv run --frozen --project tools python tests/conformance.py --backend all --browser
uv run --frozen --project tools python tests/postgres_conformance.py --browser
uv run --frozen --project tools python tests/account_conformance.py --browser
uv run --frozen --project tools python -m unittest discover -s tests -p 'test_*.py'
```

참조 서버의 v2/v3 통과가 새 Go·Java·Rust 소비 앱의 DB·실제 화면 검증을 대신하지 않는다. PostgreSQL·SMTP 코드는 이 작업에서 계약을 변경하지 않았다. 원격 CI는 [Actions](https://github.com/jongko54/feature-standards/actions)에서 최종 commit별로 확인한다. 레지스트리 게시·운영 배포·보안 감사 완료를 의미하지 않는다.
