# AI 인증 통합 평가

실제 코딩 에이전트가 새 프로젝트에 기존 패키지를 통합하는지 평가한다. 모델의 내부 사고나
고정된 보편 알고리즘을 재구성하지 않는다. 입력 과제 → 실행 trace·산출물 → 결정적 검사라는
[공식 스킬 평가 방식](https://developers.openai.com/blog/eval-skills)을 사용한다.
[에이전트의 구현·검증·수정 반복](https://developers.openai.com/blog/run-long-horizon-tasks-with-codex)과
[Codex의 `.agents/skills` 탐색](https://learn.chatgpt.com/docs/build-skills)을 관찰 가능한 대상으로 삼는다.

`tasks.json`의 네 과제는 스택만 다르고 같은 v1 통합 동작을 요구한다. CLI의 기존 인증과
실행자가 명시한 `--model`을 사용한다. 모델 ID를 생략할 수 없으며 도구가 임의의 모델을 고르지 않는다.
[공식 CLI의 모델 옵션](https://learn.chatgpt.com/docs/developer-commands#global-flags)과
설치된 `codex exec --help`에서 해당 버전의 지원 여부를 확인한다.
사용자 설정의 `model`은 선택의 참고 자료일 뿐, `--ignore-user-config`에서 선택될 기본 모델이나
서비스가 실제 해석한 모델 ID를 증명하지 않는다. 설정 전체나 인증 파일을 출력하지 않는다.
`--ignore-user-config`로 사용자 MCP·hooks
설정을 로드하지 않고 `--ephemeral --sandbox workspace-write`, 승인 정책 never를 사용한다.
CLI의 작업 디렉터리는 외부 임시 경로의 snapshot/generated이고, 참조 소스는 그 상위 snapshot에 둔다.
빈 Git 저장소를 snapshot에 초기화해 실제 저장소의 지침 상속을 막고 스킬 탐색 루트를 고정한다.
기존 Git 데이터는 복사하지 않고, 이 임시 저장소에서 commit/push하지 않는다.
snapshot은 Git이 추적하거나 ignore하지 않은 소스만 선택하며 환경 파일·Git 데이터·빌드·캐시를 제외한다.
기존 소스는 쓰기 비트를 제거하고 전후 hash를 비교한다. 운영 DB·SMTP·외부 수신자는 사용하지 않는다.

```sh
mkdir -p eval-results
AUTH_EVAL_MODEL='YOUR_FIXED_MODEL_ID'
uv run --frozen --project tools python tools/auth_eval.py --stack all --condition both --model "$AUTH_EVAL_MODEL" --repeats 3 --timeout 600 --output eval-results/v1-paired-3
```

`YOUR_FIXED_MODEL_ID`를 사용할 수 있는 모델 ID로 바꾼다. 이 명령은 **실제 모델 실행 24회**를 시작한다.
한 언어만 평가할 때는 `--stack python|go|java|rust`, 한 조건만 실행할 때는 `--condition baseline|skill`을 사용한다.
반복은 조건·스택별 1~10회(기본 3회)이며, 한 회의 모델·빌드·검사 총 시간은 최대
600초이며 약 1/3을 빌드·독립 검사에 남긴다. 출력 경로는 새 경로여야 하고 symlink를 거절한다.
출력에 기존 파일을 덮어쓰거나 저장소의 실제 구현을 변경하지 않는다. 프로그램의 build/start는
shell 문자열 대신 검증한 argv/cwd로 실행하며 cwd는 generated 내부여야 한다.
실행한 프로세스 그룹과 실행 중 ps의 PPID 관계로 추적한 자식·별도 session은
성공·실패·시간 초과 모두 종료한다. 샘플 사이에 생성·고아화되는 임의 daemon까지
완전히 통제하지는 못하므로 과제는 foreground 서버만 허용한다.

## 비교 조건

양 조건 모두 **같은 현재 패키지 코드·공개 API·소비 예제·구현 README**를 복사한다.
`baseline`은 루트 AGENTS.md·README.md와 integrate-auth/SKILL.md만 고정 commit
`2a18bbd50f142b2fc0a991fe0d40ccf7032476b9`의 내용으로 교체하고 `.agents/`,
`feature-standards.json`, `tools/auth_catalog.py`, 새 스킬 references와 docs/ai-integration.md를
제외한다. 구현 계획 문서는 양쪽 모두 제외한다. `skill`은 현재 지침·자동 탐색·manifest를
포함한다. 따라서 결과는 이 **문맥 구성 변경**의 비교이며 패키지 분리 전후 효과를 측정하지 않는다.
한 명령의 모든 스택·조건·반복은 시작 시 한 번 만든 읽기 전용 template에서 복사한다.
template을 만드는 중 소스가 바뀌면 실행하지 않는다. 이후 checkout이 바뀌어도 이미 고정한 소스와
과제 입력을 사용한다. 반복마다 baseline→skill, skill→baseline 순서를 번갈아 실행하고 실제 순서를 기록한다.
패키지·공개 API의 바이트는 두 조건에서 같고, 생성기 패키지도 양쪽에 포함한다. 이는 생성기가 없던
버전과의 비교가 아니다. 설치·빌드 캐시는 공유될 수 있으므로 이 순서만으로 cold/warm cache를 통제했다고 보지 않는다.
현재 추적되지 않은 작업 소스도 포함하므로 source_commit, source_dirty, 공통 source_sha256,
조건별 snapshot_sha256, runner_sha256, tasks_sha256, CLI 버전, 요청 모델 ID를 기록한다.
별도 명령의 결과를 비교할 때는 이 값과 timeout·환경을 맞춘다. `--condition both --stack all`이
같은 소스·과제를 사용한 비교를 만들기 위한 기본 실행 방법이다.
baseline commit이 없는 shallow checkout은 명확히 실패하며 자동 fetch하지 않는다.
필요하면 실행자가 해당 commit을 먼저 확보한다. CLI의 전역 스킬·사용자 지침은 런타임에 따라
여전히 제공될 수 있으며 `--ignore-user-config`가 이들까지 모두 제거함을 보장하지 않는다.

## 채점과 근거의 한계

새 앱은 run.json(build argv 목록/start argv)과 integration.json(stack/profile/source_commit)을
제출한다. 독립 loopback HTTP grader는 익명·위조 쿠키·잘못된 비밀번호·없는 계정401,
로그인200·동일 사용자 조회, 서로 다른 세션·CSRF 두 개, 교차 CSRF와 잘못된 CSRF403·세션 보존,
로그아웃204·이전 쿠키401, 다른 독립 세션 보존과 그 세션의 정상 폐기를 검사한다.
Python은 AST에서 실제 공개 import와 create_app/current_user 사용을, 다른 언어는
주석을 제거한 코드·의존성 표식을 검사하고 인증 구현 파일 전체 복사 여부도 확인한다.
공식 소비 예제의 연결 코드·모듈 설정을 재사용하는 것은 허용한다.
이 정적 재사용 검사는 부분 복제가 전혀 없다는 증명이나 보안 감사는 아니다.
생성된 build/start 명령은 실행 가능한 코드이므로 별도 OS/컨테이너 경계가 필요한 환경에서는
이 harness 자체를 격리해서 실행한다. CLI sandbox가 grader 자식 프로그램까지 보호하지는 않는다.

결과에는 실제 성공 여부, 실패 코드, 시간, 명령 수, CLI가 보고한 토큰 합계와 완료 여부를 남긴다.
requested_model은 CLI에 명시한 ID이고, trace가 모델 ID를 직접 제공하면 agent.model과 agent.models에
기록한다. 없으면 model=null/models=[]이며 요청 ID로 관측 값을 채우지 않는다. model_selection은
matching/different/not_reported다. 요청 ID와 보고된 ID가 다를 때 alias인지 다른 모델인지 추정하지 않는다.
고정 ID를 전달해도 alias가 가리키는 가중치의 불변성까지 보장하지는 않는다. 명령의 스킬·manifest
경로 참조 횟수도 기록하되 이 횟수가 스킬의 실제 자동 선택·전체 읽기를 증명하지는 않는다.
토큰 정보가 없으면 null/usage_complete=false로 기록하며 실제 0 사용량과 구분한다.
미완성 trace나 모델 실행 실패는 평가 성공으로 채점하지 않는다. summary의 aggregates는 스택·조건별
성공 수·비율, 실패 코드, 시간·명령·토큰의 표본 수/누락 수와 min/p25/median/p75/max를 제공한다.
시간은 실패한 시도도 포함한다. 토큰 통계에는 완료된 turn의 사용량이 모두 있는 실행만 포함하며
부분 합계·누락을 0으로 채우지 않는다. CLI가 보고한 수치이며 청구된 전체 사용량을 증명하지 않는다.
모델·CLI·공통 소스가 섞이면 comparable_configuration=false다. 작은 표본의 사분위수는 기술 통계이며
통계적 유의성이나 일반적인 모델·언어 성능을 뜻하지 않는다. 반복별 결과와 실패도 함께 제시한다.

이 모델 과제는 **browser-session-v1만** 검증한다. v2/v3의 실제 DB·브라우저 소비 검사는
`tests/consumer_profiles.py`의 별도 근거이며, metadata 선택 가능 여부를 모델의 v2/v3 통합 성공으로 보고하지 않는다.

trace.jsonl·build/server 로그·생성 코드는 민감한 내용을 포함할 수 있다. 출력 디렉터리는 0700,
로그·JSON은 0600으로 생성하고 루트 `eval-results/`는 Git에서 제외한다. 원문 trace나 프로그램 로그를
공개 CI artifact에 올리지 않는다. 커밋 보고서에는 비밀 없는 summary 지표만 옮긴다.
`tests/test_auth_eval.py`의 fake CLI 검사는 도구·채점기 검증이며 모델 성능 근거가 아니다.
