# AI가 적용하는 인증 표준

목표는 같은 요청에 대해 에이전트가 지원 프로필을 고르고, 기존 패키지를 통합하고, 실행으로 결과를 확인하도록 만드는 것이다. 모델 가중치나 비공개 추론 알고리즘을 분석했다고 주장하지 않는다. 공통 동작의 표준화와 AI가 통합을 성공하는지는 별도 측정이다.

첫 smoke 평가는 네 백엔드×두 조건 **8/8 성공**이었으며 [이전 결과](validation-ai-2026-11-03.md)를 보존한다. 이후 같은 고정 소스와 명시적 요청 모델로 조건별 3회 반복한 **24/24 통합**이 모두 통과했다. 시간·토큰 효율은 언어별 혼합 결과이며 일괄 개선을 입증하지 못했다. [반복 평가 결과와 한계](validation-ai-paired-2026-11-03.md)를 확인한다.

## 탐색과 선택

루트 [manifest](../feature-standards.json)는 스택별 공개 진입점·로컬 패키지·소비 예제·설치/검증 argv와 프로필별 명세·OpenAPI·시나리오·환경·마이그레이션을 제공한다. [스키마](../features/auth/catalog.schema.json)와 [검사 도구](../tools/auth_catalog.py)가 경로·프로필 연결을 확인한다. 명령은 실행 지침이며 자동으로 실행하지 않는다.

```sh
uv run --frozen --project tools python tools/auth_catalog.py --check
uv run --frozen --project tools python tools/auth_catalog.py --stack rust --profile browser-session-v3
```

기본은 메모리 v1, 공유 PostgreSQL은 v2, 가입·확인·reset은 v3다. SMTP는 v3의 별도 addon이다. React는 네 백엔드에 붙는 클라이언트 축이다. 대상 앱의 기존 계정·데이터·API를 보존하고 요청하지 않은 이관·SMTP·배포를 추가하지 않는다.

[스킬 원본](../skills/integrate-auth/SKILL.md)은 `.agents/skills/integrate-auth` symlink로 연결한다. Codex는 저장소 `.agents/skills`를 탐색하며 symlink를 지원한다. 메타데이터로 스킬을 선택하고 관련 프로필·참조를 필요할 때 읽도록 구성했다. [공식 스킬 문서](https://learn.chatgpt.com/docs/build-skills)

## 분석할 수 있는 작업 흐름

공개 문서의 Codex 실행 흐름은 계획·수정·도구 실행·결과 관찰·수정 반복이다. 저장소에서는 어느 문서를 찾았는지, 어떤 프로필·API를 선택했는지, 명령이 성공했는지와 결과물을 관찰할 수 있다. 이 흐름은 모델 내부 사고과정을 그대로 공개하거나 모든 AI가 같은 순서로 행동한다는 뜻은 아니다. [공식 에이전트 흐름](https://developers.openai.com/blog/run-long-horizon-tasks-with-codex)

그에 맞춰 진입점을 줄이고, 공개 API와 의존성을 명시하고, 실제 검증 명령을 제공한다. 문서 양을 늘리는 것만으로 개선을 가정하지 않는다. 세부 사항은 필요한 시점에 읽는 구조를 사용한다. [공식 문맥·스킬 지침](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra)

## 재사용 검증

[Go](../examples/consumer-go/README.md), [Java](../examples/consumer-java/README.md), [Rust](../examples/consumer-rust/README.md)는 인증 구현을 복사하지 않는 독립 프로젝트다. 메모리 v1에서 익명 요청·로그인·보호 API·CSRF 거절·로그아웃·이전 쿠키 거절을 실행한다. 추가 [독립 소비 matrix](../examples/consumer-python-react/PROFILE_TESTS.md)는 네 언어의 v2/v3를 각각 별도 임시 DB에서 실행하며 세션 분리·서버 재시작·계정 흐름과 실제 소비 React 화면을 검사한다. 8개 backend/profile 조합과 Chromium 28개가 로컬 및 구현 커밋 CI에서 통과했다.

참조 서버의 v1/v2/v3 API·브라우저와 언어 간 상태·경합 검증은 기존 공통 harness가 담당한다. React API의 npm 게시·설치 상태는 [배포 기록](npm-release.md)을 확인한다. 서버 패키지의 레지스트리 게시·보안 감사·운영 SMTP 수신 성공은 별도 범위다.

## 실제 AI 통합 평가

[평가 과제와 실행 안내](../evals/auth/README.md)를 따른다. 과제는 언어별로 새 보호 API를 통합하고, 별도의 HTTP grader가 세션 폐기를 검사하는 것이다. 정적 manifest·unit·소비 예제 테스트는 모델이 통합을 성공했다는 증거가 아니다.

동일한 구현 코드에 이전 문맥 baseline과 새 스킬/manifest 문맥을 적용해 비교한다. 실행마다 새 디렉터리를 사용하고 모델 응답, 명령 수, 시간, 토큰, 종료 사유와 실제 HTTP 결과를 구분해서 기록한다. 한 번씩의 smoke 결과를 일반적인 성공률·통계적 개선으로 표현하지 않는다. 모델·도구 버전과 입력 차이를 함께 남겨야 비교할 수 있다. [공식 스킬 평가 방법](https://developers.openai.com/blog/eval-skills)

CI에는 결정적 계약·도구·소비 검증만 넣는다. 실제 모델 평가는 설치된 CLI와 기존 인증을 사용하는 명시적 수동 실행이며 CI에 공급자 자격 증명을 추가하지 않는다. raw trace와 생성물은 로컬 `eval-results/` 또는 작업 전용 임시 경로에만 두고 요약만 공유한다.

## 생성 도구와 배포 상태

알려진 스택·v1 통합은 선택한 소비 예제와 공개 API 안내로 바로 이동한다. 명시적 checkout을 연결하는 [생성 CLI](create-feature-auth.md)도 제공한다. CLI HTTP check는 메모리 v1만 확인하며 DB 검증을 대신하지 않는다. Go v0.1.0은 공개 모듈 설치까지 확인했고, 나머지 서버 레지스트리와 새 CLI npm 게시·OIDC 활성화는 [배포 안내](server-releases.md)와 [검증 기록](validation-reuse-2026-11-03.md)을 따른다.
