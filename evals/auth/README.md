# AI 인증 통합 평가

실제 코딩 에이전트가 새 프로젝트에 기존 패키지를 통합하는지 평가한다. 모델의 내부 사고나
고정된 보편 알고리즘을 재구성하지 않는다. 입력 과제 → 실행 trace·산출물 → 결정적 검사라는
[공식 스킬 평가 방식](https://developers.openai.com/blog/eval-skills)을 사용한다.
[에이전트의 구현·검증·수정 반복](https://developers.openai.com/blog/run-long-horizon-tasks-with-codex)과
[Codex의 `.agents/skills` 탐색](https://learn.chatgpt.com/docs/build-skills)을 관찰 가능한 대상으로 삼는다.

`tasks.json`의 네 과제는 스택만 다르고 같은 v1 통합 동작을 요구한다. CLI의 기존 인증과
기본 모델을 사용하며 모델을 변경하지 않는다. `--ignore-user-config`로 사용자 MCP·hooks
설정을 로드하지 않고 `--ephemeral --sandbox workspace-write`, 승인 정책 never를 사용한다.
CLI의 작업 디렉터리는 외부 임시 경로의 snapshot/generated이고, 참조 소스는 그 상위 snapshot에 둔다.
빈 Git 저장소를 snapshot에 초기화해 실제 저장소의 지침 상속을 막고 스킬 탐색 루트를 고정한다.
기존 Git 데이터는 복사하지 않고, 이 임시 저장소에서 commit/push하지 않는다.
snapshot은 Git이 추적하거나 ignore하지 않은 소스만 선택하며 환경 파일·Git 데이터·빌드·캐시를 제외한다.
기존 소스는 쓰기 비트를 제거하고 전후 hash를 비교한다. 운영 DB·SMTP·외부 수신자는 사용하지 않는다.

```sh
mkdir -p eval-results
python3 tools/auth_eval.py --stack python --condition baseline --repeats 1 --timeout 600 --output eval-results/python-baseline-1
python3 tools/auth_eval.py --stack python --condition skill --repeats 1 --timeout 600 --output eval-results/python-skill-1
```

Go·Java·Rust는 `--stack`만 바꾼다. 반복은 1~3회, 한 회의 모델·빌드·검사 총 시간은 최대
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
현재 추적되지 않은 작업 소스도 포함하므로 source_commit, source_dirty, snapshot_sha256을 기록한다.
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
trace가 모델 ID를 직접 제공하면 기록하고 그렇지 않으면 model=null이다. 명령의 스킬·manifest
경로 참조 횟수도 기록하되 이 횟수가 스킬의 실제 자동 선택·전체 읽기를 증명하지는 않는다.
토큰 정보가 없으면 null/usage_complete=false로 기록하며 실제 0 사용량과 구분한다.
미완성 trace나 모델 실행 실패는 평가 성공으로 채점하지 않는다. 1회 결과는 일반적인 모델·언어
성능을 대표하지 않으며, 비교할 때 같은 소스·환경·CLI를 사용하고 반복별 결과를 함께 제시한다.

trace.jsonl·build/server 로그·생성 코드는 민감한 내용을 포함할 수 있다. 출력 디렉터리는 0700,
로그·JSON은 0600으로 생성하고 루트 `eval-results/`는 Git에서 제외한다. 원문 trace나 프로그램 로그를
공개 CI artifact에 올리지 않는다. 커밋 보고서에는 비밀 없는 summary 지표만 옮긴다.
`tests/test_auth_eval.py`의 fake CLI 검사는 도구·채점기 검증이며 모델 성능 근거가 아니다.
