# Three-feature SDK starter

## Scope

사용자가 다음 고도화와 에이전트 활용을 승인했다. clean main `c4a044e`에서 시작한다. 인증·권한·목록이 실제 원본 SDK에 연결된 외부 프로젝트를 CLI로 생성하고 build/demo/check할 수 있게 한다. 기존 인증 생성 v1/v2/v3와 read-only context는 유지한다. 새 registry 게시, DB 기능 추가, UI, 운영 배포, AI 모델 재실험은 이번 범위에 포함하지 않는다. 구현·검증·GitHub push 및 해당 커밋 CI를 완료한다.

## Interface and behavior

- `feature-standards init --template core --source CHECKOUT --stack python|go|java|rust --dest NEW_DIRECTORY [--profile browser-session-v1] [--check]`.
- 기존 `--feature auth`는 유지한다. `--template core`와 명시 `--feature`의 조합은 거부한다. core의 auth v2/v3, React, 다른 template/profile은 생성 전에 거부한다.
- core는 `browser-session-v1`, `rbac-v1`, `offset-list-v1`을 함께 선택하며 네 backend를 지원한다. 네이티브 SDK 본체는 복사하지 않고 명시 checkout의 auth/core 상대경로 의존성을 연결한다.
- main package 내부 core generator/runner/templates로 구현한다. 새 npm package identity는 만들지 않는다. 기존 `create-feature-auth`는 변경하지 않는다.
- source main package의 `featureStandards.coreStarterProtocolVersion: 1` capability와 regular generator entrypoint를 확인한 후 실행한다. source/manifest/stack/library markers와 새 목적지를 모두 검증한 뒤 생성한다.
- generated metadata는 `feature-core.json`, generator `feature-standards`, template `core`, core check protocol 1, stack, auth profile, 세 feature/profile 조합, 상대 source/auth/core 경로와 세 manifest/source commit/hash를 기록한다. source reference는 immutable vendoring이나 자동 업데이트가 아니다.
- `check --project`는 auth/core metadata를 구분하고 둘 다 존재하면 거부한다. core 성공은 세 기능 선택과 필수 HTTP/SDK-origin 검사 receipt를 검증해야 한다. auth-only receipt를 core 성공으로 수용하지 않는다.
- generated `node project.mjs build|start|demo|check`. start는 Secure/non-demo auth와 default-deny membership, 비데모 샘플 문서 비노출을 유지한다. demo/check만 loopback memory fixture와 명시적 demo provider를 사용한다. 제공 코드는 실제 session → current trusted membership → policy visibility → raw query/schema → page response를 연결한다.
- 문서 read-only list/detail과 기존 `/api/profile`을 제공한다. 정책과 provider 교체 지점을 안내하며 browser/header/query가 역할·tenant·주체를 결정하지 못한다.
- generation은 설치/서버/DB를 실행하지 않는다. check는 AUTH/PORT/DB/계정 설정을 격리하고 자신의 loopback 프로세스만 종료한다. DB·SMTP·브라우저 검사는 이번 core check에 포함하지 않는다.
- Java는 auth/core 각각 sourceDirectory/resources를 외부 원본에 연결한 POM overlay를 생성 앱 내부에 만들며 target/repository도 앱 안에 둔다. 모든 stack에서 source 내용 불변을 검증한다.
- SDK 연결 카드를 npm snapshot에 포함하고, 해당 네 backend의 v1/rbac/materialized context에서만 제공한다. 기존 연구 수치를 새 starter의 성능·채택 개선으로 사용하지 않는다.

## Ownership and milestones

1. Generator agent: `packages/feature-standards/src/core-generator.mjs`, `core-project.mjs`, core checker helper, `test/core-generator.test.mjs`, `test/core-generated.mjs`. 안전한 생성·출처·runner·고정 receipt와 생성 앱 검증.
2. Composition agent: `packages/feature-standards/templates/core/python` 및 `go`. 기존 core 소비 glue를 재사용하고 일반 start default-deny와 명시 demo를 분리.
3. Native agent: `packages/feature-standards/templates/core/java` 및 `rust`. 같은 계약, 실제 SDK imports와 source 의존성.
4. Parent: main CLI/workflow/index, package/build snapshot와 context, 관련 main tests, 문서·CI 및 통합검증/Git. 저자와 분리된 최종 읽기 전용 리뷰.

템플릿 경로는 기존 언어 파일 구조를 따른다. Python/Go/Rust dependency path placeholder는 JSON-quoted `{{AUTH_PATH}}`, `{{CORE_PATH}}`이다. Java POM 좌표는 `{{AUTH_GROUP_ID}}`, `{{AUTH_ARTIFACT_ID}}`, `{{AUTH_VERSION}}`, `{{CORE_GROUP_ID}}`, `{{CORE_ARTIFACT_ID}}`, `{{CORE_VERSION}}`를 사용한다. auth classifier는 library다. generator/runner 인터페이스 변경은 부모와 공유 후 적용한다.

## Verification

- CLI/API: 기존 auth/compact context 회귀, core 선택·조합·구버전 source capability·auth-only receipt 거부, no-execution read paths, 링크/기존 목적지/source escape 거부.
- 새 generator 동작은 실패하는 행동 검사부터 구현한다. 출처·manifest 변경, 상대 경로·공백, source symlink, existing target, 원본 파일 보존을 확인한다. mock는 실제 외부 경계에만 사용한다.
- 네 실제 외부 생성 앱을 순차로 build/check: anonymous/forged session, 정확한 로그인·세션, Origin/CSRF, own/other owner/tenant, visibility 전 total, filter/sort/page/raw-invalid query, logout replay, non-demo default-deny, 실제 auth/core dependency origins를 확인한다.
- 명시 source로 생성한 것과 실제 packed main CLI fresh installation으로 생성한 것을 구분한다. installed CLI의 core starter도 실제 실행한다.
- 전체 unit/패키지 검사와 프로젝트 요구 auth/browser 검증, 최종 diff·독립 리뷰. CI와 template은 같이 갱신하고 exact pushed ref와 CI를 확인한다.
- 기존 AI 실험 원본·결과는 유지한다. 이번 functional starter 검증은 새 AI 토큰 절감률이나 외부 채택률 측정이 아니다.
