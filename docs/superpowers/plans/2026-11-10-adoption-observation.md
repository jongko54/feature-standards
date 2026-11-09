# 외부 공개 사용과 AI 자발적 선택 관찰

## 범위

사용자가 승인한 1번(외부 사용 프로젝트 조사)과 3번(사용 지시 없는 AI 선택 실험 확대)을 수행한다. 선택형 사용자 계측, 개인정보 수집 서버, 메시지 발송, 신규 registry 배포는 포함하지 않는다. 이전 37개 모델 세션과 원본 결과는 수정하지 않는다.

출발점은 clean main `5119bad602dc6354824adf055c36f6922cdd115c`다. 이 Git 객체와 clean CLI 0.4.0 로컬 후보 archive를 고정했다. archive SHA-256은 `3600b69734f0c5ef3bb9cfe62165d005ca3c594efb489cd8bbac782aa52ae62e`다. 실제 CLI catalog에서 `gpt-6.1-sol`, `gpt-6-astra`를 확인했고 별도 접근 확인 세션은 두 모델 모두 완료했다. 이 2회는 통합 선택 분모에서 제외한다. trace의 실제 모델 ID 미보고는 unknown이다.

## 외부 공개 사용 조사

공식 registry와 tracked receipt에서 12개 배포 식별자를 확인하고 공개 의존성 그래프, GitHub 검색, 실제 manifest/제품 호출 파일을 교차 조사한다. 같은 외부 저장소는 패키지 수와 무관하게 하나로 세고 자체 저장소·포크·미러·레지스트리 인덱스·메타데이터 수집·이름 충돌·단순 언급을 분리한다. 선언과 실제 연결을 별도로 기록한다. 검색 실패/인덱스 누락/페이지 제한을 0으로 해석하지 않는다. 분모를 알 수 없는 외부 시장 채택률은 계산하지 않는다.

`docs/adoption/2026-11-10-public-projects.json`에 관측 UTC·식별자·query·source URL·commit·경로·분류와 제약을, 대응 Markdown에 해석을 남긴다. 다운로드·스타·clone은 실제 통합이나 AI 사용의 근거로 세지 않는다.

## 고정한 새 AI 실험

- 요청 모델 2개 × backend 4개 × documents/notes 2개 × 각 2반복 = 32개 통합 세션.
- 두 과제는 경로 라벨이 다른 고정 유사 과제 계열이다. 다양한 제품 과제로 일반화하지 않는다.
- 동일 source/archive와 중립 AGENTS를 제공하고 기능 라이브러리·SDK·공개 API·CLI·시작 문서의 사용을 강제하지 않는다. 기존 tasks의 강제 import 설명은 prompt에 넣지 않는다.
- 지원 SDK의 실제 환경에 맞춰 Python/FastAPI, Go/net/http, Java/Spring Boot, Rust/Axum을 고정하되 해당 기능 패키지를 사용할지는 지정하지 않는다. 일반 HTTP 서버를 자유롭게 고른 과거 4회와 이 조건도 다르므로 합산하지 않는다.
- source/config 2MB 제한, conventional build/cache 위치, 정상 의존성 해결을 공통 안내한다. 기존 Go 실행 파일 때문에 발생한 미고지 artifact 오염을 줄이되 크기·symlink·provenance 경계는 완화하지 않는다.
- 모델/과제 순서를 backend별 회전하고 두 번째 반복은 역순으로 고정한다. 실제 실행은 직렬, timeout은 600초다. 기존 정상 host cache를 사용하며 server prompt cache·가중치·호스트 부하는 통제했다고 주장하지 않는다.
- documents와 notes 모두 기존 143개 독립 HTTP 검사를 쓴다. 새 notes 어댑터는 지역 requester 주입으로 경로만 바꾸고 전역 함수를 교체하지 않는다. 검사 코드는 공개 참조 소스이므로 비공개 holdout이 아니다.
- 원본 result/trace를 보존하고 사후 분석은 별도 파일에 기록한다. 모든 시도·완전/누락 usage·CLI/모델 접근 실패·timeout·build/artifact/HTTP 실패를 남긴다.

## 분모와 판정

제출 시도, 지원 모델의 시작 관측, 시작 불명, 사전 인프라 차단, source 검토 가능 여부를 각각 기록한다. 시작 후 timeout/build/artifact/HTTP 실패를 선택 분모에서 제거하지 않는다. 사용·호출·임포트 단서만으로 채택을 확정하지 않는다.

실제 source의 build/start→제품 경로를 독립 검토하여 기능별 `library_connected`, `transitive_library_connected`, `direct_independent`, `copied_runtime_source`, `mixed`, `uncertain`를 구분한다. 세 기능 전체 연결과 일부 연결, 연결+143 HTTP 성공을 분리한다. 검토되지 않았거나 검토 불가능한 source는 unknown으로 남긴다. 검토율과 unknown 수를 함께 제시하며 확인된 비율을 전체 시장 채택률로 확대하지 않는다.

## 구현·검증·반영

1. 에이전트가 외부 공개 사용 조사, 다른 에이전트가 중립 task/지역 grader 어댑터와 회귀 검사를 맡는다. 주 에이전트는 다중 모델 실행기·집계·source 검토 입출력을 구현한다.
2. 순서·분모·불명/인프라·기능별 판정·hash 불일치·private 정보 제외·143 HTTP 유지·원본 보존을 결정적 테스트로 확인한다. mock CLI 단위 검사는 실제 모델 실험으로 세지 않는다.
3. 실행기 bytes를 커밋한 뒤 실제 32개 세션을 실행한다. 사후 source 판정은 원본을 변경하지 않는 별도 근거로 수록한다.
4. 새 결과와 과거 4회 discovery를 분리해 정제 결과와 README/평가 안내에 반영한다. 승인된 GitHub 저장소에 푸시하고 최종 ref의 CI를 확인한다. raw trace·앱 코드·로컬 절대 경로·credential은 공개하지 않는다.
