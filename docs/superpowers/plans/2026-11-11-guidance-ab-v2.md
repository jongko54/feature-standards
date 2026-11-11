# SDK 연결 안내와 명확한 과제의 A/B 평가

## 승인 범위와 목표

이전 답변의 우선순위인 계약·빌드 조건 명확화, 선택형 SDK 최소 연결 안내의 A/B 검증, 서로 다른 업무 흐름으로 평가 확장을 실행한다. 사용자는 에이전트 활용과 진행을 승인했다. 출발점은 clean main `07022e278b07d6c9ac8d7b34399254d37f4a65a5`다.

기존 32회 및 이전 실험의 prompt·grader·원본 결과는 보존한다. 제품 SDK API·DB schema·인증 프로필은 바꾸지 않는다. MFA/역할 관리, 다른 언어의 PostgreSQL 목록 구현, 사용자 계측 서버, 실제 메일·고객 데이터·운영 DB, 새 registry 게시는 이번 범위가 아니다. 승인된 저장소의 변경·검증·GitHub push와 해당 ref CI까지 진행한다.

## 고정한 비교 설계

- 한 요청 모델 `gpt-6.1-sol` × 네 백엔드(FastAPI/net/http/Spring Boot/Axum) × 두 업무 과제 × 두 안내 조건 × 두 반복 = **32개 새 통합 CLI 세션**이다. 조건별·백엔드별·과제별 반복은 2개다. 한 모델의 작은 pilot이며 다른 모델로 일반화하지 않는다.
- 과제는 기존 documents의 명확한 owner 가시성 규칙과, 다른 필드·viewer/dispatcher 권한·비공개 합성 데이터·inbox summary를 갖는 tickets workflow다. 후자는 단순 경로 변경이 아니지만 둘 다 통제한 합성 과제이며 실제 외부 고객 사용은 아니다. unsafe mutation은 포함하지 않는다.
- documents의 ambiguous collection/read 문장은 collection/detail 모두 owner 읽기 가시성을 filters/totals 이전에 적용하도록 명시한다. 기존 143 HTTP 검사 자체는 변경하지 않는다.
- 양쪽 prompt에 반복 가능한 build 조건을 똑같이 제공한다. 기존 `.venv`가 있을 수 있고 uv-created venv에는 pip가 없을 수 있음을 명시한다. SDK 사용을 강제하지 않는다. source/config 2MB, foreground, 원본 참조 보존, 일반 온라인 의존성 해결과 기존 안전 경계를 유지한다.
- 로컬 Python 3.14의 XML parser 환경 오류를 확인해 실험의 Python bootstrap은 양쪽 모두 정상인 uv-managed Python 3.13으로 명시한다. CLI는 실제 설치된 `0.167.1`이다. 기존 임시 JDK 일부 파일이 없어 별도 캐시에 SHA-256을 검증한 Temurin `21.0.13+9`를 준비하며 전역 Java 설정은 바꾸지 않는다.
- **baseline**은 명확한 공통 과제만 받는다. **sdk-pointer**는 같은 과제와 함께 선택 사항인 `../docs/ai-entry/<stack>.md` 경로 한 개를 안내받는다. 두 조건 모두 같은 source/archive/중립 AGENTS와 모든 SDK 카드를 갖는다. 처리 조건은 포인터 안내이며 파일 존재·강제 사용·채점 기준을 바꾸지 않는다. baseline의 자발적인 카드 사용도 제외하지 않는다.
- tickets 실제 데이터는 모델 작업 이후 grader가 생성하는 private fixture다. fresh seed를 pair별로 고정하여 같은 backend/task/repeat의 A/B에 같은 데이터를 쓴다. 모델 prompt·사전 env·제공 checkout에 seed/실제 값을 넣지 않는다. fixture 생성 로직과 공개 계약은 보이므로 OS 수준 보안 격리나 비공개 전체 grader라고 주장하지 않는다.
- backend 순서는 고정하고 내부 task/condition 순서를 회전하며 두 번째 반복은 역순이다. 실제 통합은 직렬, 총 600초/모델 작업 약 402초를 유지한다. 요청 모델 접근 확인은 별도 세션으로 기록하고 32개 분모에서 제외한다. 가용하지 않으면 자동 대체하지 않는다.
- 실행기와 카드·과제·fixture generator를 커밋하고 source/archive/runner/카드/prompt/fixture/task 해시를 고정한 후 실행한다. 실행 도중 조건·과제·grader·예산은 바꾸지 않는다. 캐시·서버 가중치·호스트 부하는 통제하지 못한다.

## 인터페이스와 소유권

1. 안내 에이전트: `docs/ai-entry/{README,python,go,java,rust}.md`. 실제 공개 API/소비 예제와 import origin을 검증한다. 코드 복사·SDK 사용을 금지/강제하지 않는다.
2. 과제 에이전트: `tools/choice_tasks_v2.py`, `tests/test_choice_tasks_v2.py`. `prompt(..., condition, *, scenario)`, `contract_factory(scenario, condition, *, ticket_data=None)`, `expected_assertions(scenario)`, `ticket_fixture(seed)`를 제공한다. requester는 지역 주입하며 전역 monkeypatch를 하지 않는다.
3. 주 에이전트: 새 실행기·회귀 검사·private ledger·A/B 집계·공개 보고서·Git. 기존 도구의 파일/trace/source review 안전 helper를 재사용하되 old protocol의 함수/결과는 바꾸지 않는다. 필요한 독립 검토는 별도 읽기 전용 에이전트에 맡긴다.

## 분모와 성공 판정

모든 시도, 지원 시작, 사전 인프라 거절, 시작 미확인, 소스 판정 가능 여부를 분리한다. 시작 뒤 timeout·빌드·HTTP 실패를 제외하지 않는다. 사용량 누락은 null이며 내부 모델 미보고도 unknown이다. 한 세션은 내부 API 요청 수나 review/orchestration 비용을 뜻하지 않는다.

기능별 원본 의존성 연결, 복사/vendor API 사용, 직접 구현, 혼합, 미확인을 실제 시작점→route→API 출처→응답 경로로 판정한다. import/이름 일치만으로 재사용을 확정하지 않는다. 원본 연결+HTTP 성공은 각 과제의 고정 expected assertion 수를 써서 확인한다. raw result/trace는 수정하지 않고 별도 source review를 결합한다.

A/B 연결/복사/직접 구현/HTTP 수를 같은 분모로 보여준다. paired fixture·과제·반복이 맞는 완전한 usage pair만 token 합계를 비교하고 제외 이유·불완전 pair도 남긴다. input/cached/uncached/output을 분리하고 reasoning을 중복 가산하지 않는다. 모델 이름·가중치·캐시·n=2의 한계로 인과 효과·일반 절감률·시장 채택률을 단정하지 않는다. 2026-11-10의 조건이 다른 32회와 합산하거나 변경 전후 효과로 비교하지 않는다.

## 검증 및 반영

1. 과제 문장/순서/두 조건 차이, fresh paired fixture 비노출, role/visibility/summary/typed-query 양성·음성 loopback 검사, 반복 build 안내, unknown/실패 분모·출처 hash 변조·안전 경로·비공개 export를 테스트한다.
2. 관련 unit suite·Ruff·catalog/link/diff 검사, 네 실제 core consumer와 CLI/도구/모델 접근 preflight를 확인한다. 문서만 바꾼 SDK 카드는 실제 예제/API 출처에 대조한다. mock CLI 검사를 실제 모델 실험으로 세지 않는다.
3. 원본을 보존하며 32회 실행하고 별도 에이전트의 route source 검토를 받는다. private trace·앱·fixture·절대 경로·credential은 공개하지 않는다.
4. 정제된 새 dataset과 English README/평가 안내, 한국어 결과 보고서를 반영한다. 선택한 변경만 커밋·푸시하고 원격 ref 및 그 커밋 CI를 확인한다. 기존 worktree와 사용자 상태는 정리·삭제하지 않는다.

OpenAI Docs의 [harness-aware evaluation 안내](https://developers.openai.com/cookbook/examples/partners/harness_aware_plugin_evals/harness_aware_plugin_evals#overview)를 참고해 실제 CLI 환경의 관측과 단위 검사를 분리한다. 이 문서는 실행 전 계획이며 통과·개선의 증거가 아니다.
