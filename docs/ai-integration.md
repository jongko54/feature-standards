# AI가 적용하는 Feature Standards

Feature Standards의 목적은 여러 언어에서 같은 기능 계약을 찾고, 해당 스택의 기존 라이브러리를 재사용해 AI가 통합 작업을 수행하도록 돕는 것이다. 기능·프로필·스택을 선택한 뒤 필요한 계약과 공개 API를 읽고, 구현을 연결하고, 공통 conformance와 대상 앱 검증을 실행하는 흐름을 제공한다. 인증(`auth`), 권한(`authorization/rbac-v1`), 목록(`listing/offset-list-v1`)을 제공한다. 새 두 기능은 Python·Go·Java·Rust·JS/TS의 코어 라이브러리이며, [배포 기록](core-release-0.1.0.json)의 공개 다운로드·새 소비자 검증 여부를 확인해 해당 버전을 설치한다. [기능 인덱스](../features/catalog.json)와 [통합 안내](core-standards.md)에서 진입한다. 게시된 npm 0.3.2은 세 기능의 25개 문맥을 포함한다.

반복 구현과 불필요한 탐색을 줄이는 것이 목표다. 이전 v1 평가에서는 네 백엔드×두 조건×조건별 3회의 **24/24 통합**이 통과했지만 시간·토큰 결과는 혼합되어 일괄 개선을 입증하지 못했다. 이 결과는 새 `feature-standards` npm 패키지의 성능 측정이 아니다. [반복 평가 결과와 한계](validation-ai-paired-2026-11-03.md)를 확인한다. 첫 **8/8 smoke 평가**는 [별도 기록](validation-ai-2026-11-03.md)으로 보존한다.

현재 소스 후보 CLI `0.4.0`은 **26개 지원 문맥**을 제공한다. Python에만 `postgres-list-v1`을 추가하며, Python 코어 `0.2.0`도 미게시 소스 후보다. 게시된 CLI `0.3.2`의 25개 문맥과 코어 `0.1.0` 기록은 그대로 유지한다. `list`의 스택별 `profiles`를 순회하고, 지원하지 않는 언어·DB 프로필 조합을 임의로 대체하지 않는다. 현재 소스에는 Go·Java·Rust의 실제 인증·권한·목록 HTTP 예제도 포함한다.

게시된 `0.3.2` 카탈로그의 효과는 [새 통합 평가 도구](../evals/core/README.md)에서 별도로 측정한다. 동일한 고정 소스·카탈로그를 두 조건에 제공하고, 문서 진입 안내와 CLI 진입 안내를 비교한다. 독립 HTTP 검사는 세 기능, 권한 철회, 제공자 장애와 공개되지 않은 총계를 확인한다. 도구의 결정적 테스트와 실제 모델 실행 결과를 구분하며, 작은 smoke 표본으로 속도·토큰 개선을 단정하지 않는다.

2026-11-07 실제 모델 8회 실행의 [원본 결과](../evals/core/results/2026-11-07-catalog-smoke-v1.json)는 7/8 통과다. Python catalog는 도구 캐시의 symlink를 소스로 오인해 HTTP 검사 전에 막혔다. 평가기를 보완한 별도 생성물 재검사는 전체 기준에서 5/8 통과했다. Python catalog는 생략한 캐시 때문에 offline 빌드가 실패했고, Go 두 개는 HTTP 검사를 통과했지만 생성 파일 바이트 변경을 검출했다. 원본 시간·토큰·성공 여부는 수정하지 않았다. 카탈로그 조건의 입력 토큰은 네 쌍 모두 더 많았으며, 공유 캐시·스택당 조건별 1회 표본으로 일반적인 개선이나 악화를 단정할 수 없다. 새 compact 모드는 이 모델 실험으로 평가하지 않았다.

CLI `0.4.0` 소스 후보의 [2026-11-08 실제 읽기 비교](validation-ai-reading-2026-11-08.md)는 새 세션 24회 중 원본 HTTP 23/24 통과다. manual 대비 compact의 입력 토큰 합계는 19.032% 감소했지만 비캐시 입력은 16.927%, 출력은 12.933% 증가했다. 비용 절감으로 해석하지 않는다. 수정 checker의 정적 24/24와 원본 HTTP 결과를 분리하며, 사용 지시 없는 선택 관찰과 짧은 가이드의 후속 비교도 별도로 기록한다.

## 주 진입점: 기능과 스택 문맥

주 npm 패키지 `feature-standards@0.3.2`은 게시와 새 registry 설치를 확인했다. 선별한 세 기능의 계약·스택 문맥과 인증 전용 앱 생성·프로필 검사를 제공한다. 실제 생성·검증은 지정한 원본 checkout과 해당 언어 도구 체인을 사용한다. [게시·새 설치·25개 문맥 기록](npm-release-0.3.2.json)과 기존 인증의 [실제 워크플로·검색 기록](npm-workflow-release-2026-11-04.json)을 함께 확인한다.

원본 checkout에서 실행할 수도 있다.

```sh
npm --prefix packages/feature-standards run build
node packages/feature-standards/src/cli.mjs list
node packages/feature-standards/src/cli.mjs context \
  --feature auth --stack rust --profile browser-session-v3
```

인증의 스택은 `python`, `go`, `java`, `rust`, `react` 중에서, 프로필은 `browser-session-v1`, `browser-session-v2`, `browser-session-v3` 중에서 선택한다. 명령은 JSON과 실행 지침을 반환하며 설치·빌드·서버 시작·DB 이관·검증 명령을 자동으로 실행하지 않는다. [패키지 안내](../packages/feature-standards/README.md)에 배포 범위와 사용법을 정리한다.

소스의 첫 실행 전 `build`는 배포할 문서 스냅샷을 만든다. JSON의 `packagedDocuments`에는 번들에 실제 포함한 문서의 `readPath`, 원본 경로·URL, 해시가 있다. `sourceCheckout`의 런타임 진입점은 별도 원본 checkout을 기준으로 하며, 설치·검증 명령에는 `executed: false`를 표시한다. `provenance`의 원본 커밋·dirty 상태와 각 문서의 해시를 함께 확인한다. `sourceModified: true` 문서는 커밋 URL에 없는 로컬 수정을 포함하므로 번들의 실제 `readPath`를 읽는다. 이 문서 경로를 서버 코드 경로로 사용하지 않는다.

게시된 `feature-standards@0.3.2`의 npm 진입점은 다음과 같다.

```sh
npx feature-standards@0.3.2 list
npx feature-standards@0.3.2 context \
  --feature auth --stack go --profile browser-session-v2
```

## 선택한 기능을 통합하는 순서

인증 memory v1·권한 RBAC·메모리 목록 세 기능과 백엔드가 이미 정해졌으면 소스 후보의 선택형 짧은 경로를 사용할 수 있다: [Python](ai-briefs/python.md), [Go](ai-briefs/go.md), [Java](ai-briefs/java.md), [Rust](ai-briefs/rust.md). 소비 예제에서 필요한 API만 따라가고 프로필 ID를 파일명으로 추측하지 않도록 안내한다. [별도 8회 유사 과제 비교](validation-ai-reading-2026-11-08.md)에서 모두 HTTP 검사를 통과했고, compact 대비 입력 71.442%·비캐시 입력 58.301%·출력 50.176% 감소를 관측했다. 언어별 한 쌍의 결과이며 비용·일반 효율을 보장하지 않는다. 인증만 필요한 작업, v2/v3, DB 목록과 React는 해당 기능의 기존 안내를 따른다.

1. **기능·프로필·스택 선택:** 소스의 기능은 `auth`, `authorization`, `listing`이다. 인증의 단일 설정 사용자와 메모리 세션은 v1, 공유 PostgreSQL은 v2, 가입·이메일 확인·비밀번호 재설정은 v3다. SMTP는 v3의 별도 addon이다. 새 권한·목록 API는 해당 코어 라이브러리를 직접 통합한다. React/JS 권한 판정은 표시 보조이며 서버 검사를 대체하지 않는다.
2. **해당 계약과 공개 API 확인:** 선택한 명세·OpenAPI·시나리오와 스택의 공개 진입점을 읽는다. 이미 스택과 프로필을 안다면 모든 구현을 탐색하지 않고 해당 안내와 소비 예제로 바로 이동한다.
3. **기존 구현 재사용:** 라이브러리나 어댑터를 가져오고 대상 앱의 보호 API·화면을 연결한다. 새 소비 앱이 필요하면 인증 전용 생성기를 사용한다. 기존 계정·데이터·API를 보존하고 요청하지 않은 이관·SMTP·배포를 추가하지 않는다.
4. **명시적으로 검증 실행:** 선택한 스택 검사와 프로필 conformance를 실행하고, 대상 앱의 실제 API·UI도 확인한다. JSON 경로나 명령 목록을 얻은 상태는 통합 성공과 다르다. 출처 버전·프로필·명령·결과·미검증 범위를 남긴다.

원본 [manifest](../feature-standards.json)는 인증 프로필별 명세·OpenAPI·시나리오·환경·마이그레이션과 스택별 공개 진입점·로컬 패키지·소비 예제·설치/검증 argv를 제공한다. [스키마](../features/auth/catalog.schema.json)와 [검사 도구](../tools/auth_catalog.py)는 원본 경로와 프로필 연결을 확인한다.

```sh
uv run --frozen --project tools python tools/auth_catalog.py --check
uv run --frozen --project tools python tools/auth_catalog.py --stack python --profile browser-session-v1
```

이 원본 조회 도구도 명령을 자동 실행하지 않는다. npm 패키지의 휴대 가능한 문맥과 실제 소스 경로를 사용하는 원본 도구를 구분한다. [인증 통합 스킬 원본](../skills/integrate-auth/SKILL.md)은 `.agents/skills/integrate-auth` symlink로 연결되어 있다.

## 인증 구성 요소

| 역할 | 배포 단위 | 원본과 안내 |
|---|---|---|
| 기능 탐색·생성·검증 | 주 패키지 `feature-standards` `0.3.2` 게시 확인 | [패키지 안내](../packages/feature-standards/README.md) |
| 인증 서버 라이브러리 | Python·Go·Java·Rust의 개별 패키지 | [서버 배포 상태](server-releases.md) |
| 브라우저 인증 API 어댑터 | `@ugauga/feature-standards-react-auth` `0.1.4` 게시 확인 | [공개 API 안내](../clients/react/README.md), [게시 기록](npm-release.md) |
| 인증 소비 앱 생성기 | `@ugauga/create-feature-auth` `0.2.0` 게시 확인 | [생성 도구 안내](create-feature-auth.md) |

생성기는 명시적인 source checkout을 연결해 얇은 소비 앱을 만든다. 이전 생성기 `0.1.1`은 메모리 v1만 검사한다. 게시된 대표 CLI·생성기 `0.2.0`은 아래 명시적 명령에서 선택한 프로필을 검사한다. v2/v3에는 별도 `FEATURE_STANDARDS_TEST_DATABASE_URL`이 필요하며, 새 UUID 테스트 DB에서만 이관·fixture·검증을 실행하고 자신이 만든 DB를 정리한다. 원래 DB의 스키마와 데이터는 수정하지 않는다. v3는 가입·확인·재설정과 기존 세션 폐기를 검사하며 SMTP를 발송하지 않는다.

```sh
node packages/feature-standards/src/cli.mjs init \
  --source "$PWD" --feature auth --stack python \
  --profile browser-session-v1 --dest ../my-auth-app --check
node packages/feature-standards/src/cli.mjs check --project ../my-auth-app
```

`list`/`context`는 계속 읽기 전용이다. `init`은 새 앱을 만들고 `check` 또는 `init --check`는 사용자가 지정한 신뢰된 소스와 도구 체인을 실행한다. 결과의 stack·profile·검사 목록과 DB 생성/정리 여부를 확인한다. 기존 `0.1.1` 생성 앱은 새 검사 프로토콜을 포함하지 않으므로 별도의 새 대상에 `0.2.0`으로 생성한다. 자세한 설정은 [생성기 안내](create-feature-auth.md)를 따른다. 준비 버전, 로컬 tarball, registry 게시·설치, npm 검색 반영은 각각 다른 상태다. [jongko54 검색 안내](npm-discovery.md)를 함께 확인한다.

## 재사용과 모델 평가의 근거

[Go](../examples/consumer-go/README.md), [Java](../examples/consumer-java/README.md), [Rust](../examples/consumer-rust/README.md)는 인증 구현을 복사하지 않는 독립 프로젝트다. 메모리 v1에서 익명 요청·로그인·보호 API·CSRF 거절·로그아웃·이전 쿠키 거절을 검사한다. [독립 소비 matrix](../examples/consumer-python-react/PROFILE_TESTS.md)는 네 언어의 v2/v3를 별도 임시 DB에서 실행하며 세션 분리·서버 재시작·계정 흐름과 실제 소비 React 화면을 검사한다. 실행 결과와 범위는 해당 기록을 따른다. 참조 서버의 공통 harness 통과와 대상 앱의 통합 성공은 별도 근거다.

실제 AI 평가는 [평가 과제와 실행 안내](../evals/auth/README.md)를 따른다. 언어별 새 보호 API를 통합하게 하고, 별도 HTTP grader가 세션 폐기를 포함한 동작을 검사한다. 정적 manifest·unit·소비 예제 테스트만으로 모델의 통합 성공을 주장하지 않는다. 동일한 고정 소스에 baseline과 스킬/manifest 문맥을 적용해 비교하며, 모델 요청 ID·관찰된 도구 버전·입력 차이·캐시·시간·토큰과 실제 HTTP 결과를 구분한다. 이 관찰로 모델 내부 사고과정이나 모든 AI의 실행 순서를 설명하지 않는다.

기존 **24/24** 기록은 메모리 v1과 당시 문맥 구성을 대상으로 한다. React·PostgreSQL v2·계정 v3·메일의 실제 모델 통합이나 새 `feature-standards` 패키지의 효율은 측정하지 않았다. CI에는 결정적 계약·도구·소비 검증을 넣고, 실제 모델 평가는 설치된 CLI와 기존 인증을 사용하는 명시적 수동 실행으로 분리한다. raw trace와 생성물은 로컬 `eval-results/` 또는 작업 전용 임시 경로에 두고 요약만 공유한다. 운영 배포·메일 수신 성공·보안 감사는 별도 범위다.
