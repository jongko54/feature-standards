# 공개 외부 프로젝트 사용 조사 — 2026-11-10

이번 조회에서 **외부 저장소의 직접 의존성 선언을 입증한 프로젝트는 0개, 제품 코드의 API 연결을 입증한 프로젝트는 0개**였다. 이는 이번 공개 검색에서 확인한 수다. 실제 외부 사용 프로젝트의 총수와 전체 채택률은 알 수 없다.

관측 요청: 2026-11-09 15:06:09–15:10:31 UTC, 한국 시각 2026-11-10 00:06:09–00:10:31. 실제 UTC 시계는 15:10:45에 확인했다. 시각을 보존하지 않은 최초 예비 검색 1회는 별도 표시했다. 기준 소스는 [`5119bad`](https://github.com/jongko54/feature-standards/tree/5119bad602dc6354824adf055c36f6922cdd115c)다. 쿼리·시각·응답·후보별 판정은 [JSON 기록](2026-11-10-public-projects.json)에 있다.

가장 큰 한계는 **검색의 알려진 양성 대조군도 누락됐다는 점**이다. 원본의 [실제 package.json](https://github.com/jongko54/feature-standards/blob/5119bad602dc6354824adf055c36f6922cdd115c/packages/feature-standards/package.json#L1-L4)은 파일 조회에 성공했으나 같은 저장소를 지정한 connector 검색은 0건이었다. REST 검색 대조군도 두 번 모두 `incomplete_results=true`였다. 검색 0건을 전체 사용 0개로 해석할 수 없다.

## 조사 대상 12개 패키지

이름은 tracked manifest와 release receipt에서 먼저 확정한 뒤 공식 레지스트리를 다시 조회했다. 게시·설치 가능 상태는 외부 사용 증거로 세지 않았다.

| 생태계 | 공개 식별자 | 역할 | 관측 게시 버전 | 원본 근거 |
| --- | --- | --- | --- | --- |
| npm | [`feature-standards`](https://registry.npmjs.org/feature-standards) | 컨텍스트 CLI | `0.1.0`, `0.2.0`, `0.3.0`, `0.3.1`, `0.3.2` | [manifest](https://github.com/jongko54/feature-standards/blob/5119bad602dc6354824adf055c36f6922cdd115c/packages/feature-standards/package.json#L2) · [receipt](https://github.com/jongko54/feature-standards/blob/5119bad602dc6354824adf055c36f6922cdd115c/docs/npm-release-0.3.2.json) |
| npm | [`@ugauga/create-feature-auth`](https://registry.npmjs.org/@ugauga%2fcreate-feature-auth) | 앱 생성 CLI | `0.1.0`, `0.1.1`, `0.2.0` | [manifest](https://github.com/jongko54/feature-standards/blob/5119bad602dc6354824adf055c36f6922cdd115c/packages/create-feature-auth/package.json#L2) · [receipt](https://github.com/jongko54/feature-standards/blob/5119bad602dc6354824adf055c36f6922cdd115c/docs/npm-workflow-release-2026-11-04.json) |
| npm | [`@ugauga/feature-standards-react-auth`](https://registry.npmjs.org/@ugauga%2ffeature-standards-react-auth) | 인증 SDK | `0.1.0`, `0.1.1`, `0.1.4` | [manifest](https://github.com/jongko54/feature-standards/blob/5119bad602dc6354824adf055c36f6922cdd115c/clients/react/package.json#L2) · [receipt](https://github.com/jongko54/feature-standards/blob/5119bad602dc6354824adf055c36f6922cdd115c/docs/npm-product-release-2026-11-03.json) |
| npm | [`@ugauga/feature-standards-core`](https://registry.npmjs.org/@ugauga%2ffeature-standards-core) | 권한·목록 SDK | `0.1.0` | [manifest](https://github.com/jongko54/feature-standards/blob/5119bad602dc6354824adf055c36f6922cdd115c/libraries/typescript/package.json#L2) · [receipt](https://github.com/jongko54/feature-standards/blob/5119bad602dc6354824adf055c36f6922cdd115c/docs/core-release-0.1.0.json) |
| pypi | [`feature-standards-python-auth`](https://pypi.org/pypi/feature-standards-python-auth/json) | 인증 SDK | `0.2.0` | [manifest](https://github.com/jongko54/feature-standards/blob/5119bad602dc6354824adf055c36f6922cdd115c/implementations/python-fastapi/pyproject.toml#L2) · [receipt](https://github.com/jongko54/feature-standards/blob/5119bad602dc6354824adf055c36f6922cdd115c/docs/python-release-0.2.0.json) |
| pypi | [`feature-standards-core`](https://pypi.org/pypi/feature-standards-core/json) | 권한·목록 SDK | `0.1.0` | [manifest](https://github.com/jongko54/feature-standards/blob/5119bad602dc6354824adf055c36f6922cdd115c/libraries/python/pyproject.toml#L2) · [receipt](https://github.com/jongko54/feature-standards/blob/5119bad602dc6354824adf055c36f6922cdd115c/docs/core-release-0.1.0.json) |
| cargo | [`feature-standards-auth`](https://crates.io/api/v1/crates/feature-standards-auth) | 인증 SDK | `0.1.0` | [manifest](https://github.com/jongko54/feature-standards/blob/5119bad602dc6354824adf055c36f6922cdd115c/implementations/rust-axum/Cargo.toml#L2) · [receipt](https://github.com/jongko54/feature-standards/blob/5119bad602dc6354824adf055c36f6922cdd115c/docs/rust-release-0.1.0.json) |
| cargo | [`feature-standards-core`](https://crates.io/api/v1/crates/feature-standards-core) | 권한·목록 SDK | `0.1.0` | [manifest](https://github.com/jongko54/feature-standards/blob/5119bad602dc6354824adf055c36f6922cdd115c/libraries/rust/Cargo.toml#L2) · [receipt](https://github.com/jongko54/feature-standards/blob/5119bad602dc6354824adf055c36f6922cdd115c/docs/core-release-0.1.0.json) |
| go | [`github.com/jongko54/feature-standards/implementations/go-net-http`](https://proxy.golang.org/github.com/jongko54/feature-standards/implementations/go-net-http/@v/list) | 인증 SDK | `v0.1.0` | [manifest](https://github.com/jongko54/feature-standards/blob/5119bad602dc6354824adf055c36f6922cdd115c/implementations/go-net-http/go.mod#L1) · [receipt](https://github.com/jongko54/feature-standards/blob/5119bad602dc6354824adf055c36f6922cdd115c/docs/go-release-0.1.0.json) |
| go | [`github.com/jongko54/feature-standards/libraries/go`](https://proxy.golang.org/github.com/jongko54/feature-standards/libraries/go/@v/list) | 권한·목록 SDK | `v0.1.0` | [manifest](https://github.com/jongko54/feature-standards/blob/5119bad602dc6354824adf055c36f6922cdd115c/libraries/go/go.mod#L1) · [receipt](https://github.com/jongko54/feature-standards/blob/5119bad602dc6354824adf055c36f6922cdd115c/docs/core-release-0.1.0.json) |
| maven | [`io.github.jongko54:java-spring-auth`](https://repo.maven.apache.org/maven2/io/github/jongko54/java-spring-auth/maven-metadata.xml) | 인증 SDK | `1.0.0` | [manifest](https://github.com/jongko54/feature-standards/blob/5119bad602dc6354824adf055c36f6922cdd115c/implementations/java-spring/pom.xml#L7) · [receipt](https://github.com/jongko54/feature-standards/blob/5119bad602dc6354824adf055c36f6922cdd115c/docs/java-release-1.0.0.json) |
| maven | [`io.github.jongko54:feature-standards-core`](https://repo.maven.apache.org/maven2/io/github/jongko54/feature-standards-core/maven-metadata.xml) | 권한·목록 SDK | `0.1.0` | [manifest](https://github.com/jongko54/feature-standards/blob/5119bad602dc6354824adf055c36f6922cdd115c/libraries/java/pom.xml#L5) · [receipt](https://github.com/jongko54/feature-standards/blob/5119bad602dc6354824adf055c36f6922cdd115c/docs/core-release-0.1.0.json) |

CLI 소스 버전은 `0.4.0`이지만 npm latest는 `0.3.2`였고, Python core 소스 버전은 `0.2.0`이지만 PyPI 최신 게시 버전은 `0.1.0`이었다. 실제 레지스트리의 이름과 게시 버전을 조사 기준으로 사용했다.

## 집계 기준과 결과

집계 단위는 정규화한 저장소 URL 1개다. 한 저장소가 여러 대상 패키지를 사용해도 1개로 센다. 소유자 `jongko54`, 원본 저장소, 원본 예제·템플릿·실험은 외부에서 제외했다.

| 확인 단계 | 이번 조사에서 입증한 외부 저장소 수 | 의미 |
| --- | ---: | --- |
| 직접 의존성 선언 | 0 | 정확한 패키지 이름 또는 Go 모듈 URL을 manifest에서 확인 |
| 제품 소스 API 연결 | 0 | 식별된 패키지 import와 제품 경로의 API 호출을 함께 확인 |
| runtime 직접 선언 | 0 | 확인된 선언 중 runtime으로 분류 가능한 건수 |
| 개발 도구 직접 선언 | 0 | 확인된 CLI·generator·dev/build/test 선언 |
| transitive만 확인 | 0 | 간접 의존성으로 확인한 외부 저장소 |
| 실제 실행·운영 중 사용 | 미확인 | 소스 호출과 실제 실행은 별도 증거가 필요 |
| 전체 외부 사용 프로젝트·전체 채택률 | 산출 불가 | 전체 대상 프로젝트라는 분모와 비공개·미색인 사용을 알 수 없음 |

import 한 줄, lockfile 이름, 생성된 골격, 튜토리얼, 언급은 제품 API 연결로 세지 않는다. fork/mirror는 독립적인 제품 연결이 입증돼야 후보가 된다. 다운로드·스타·클론·조회수와 AI 실험 결과는 사용 프로젝트 수나 AI의 자율 선택 수로 세지 않았다.

## 발견한 후보와 제외 근거

정확한 대상 이름으로 발견한 외부 저장소 2개는 PyPI 메타데이터 수집 저장소와 crates.io 인덱스였다. 제품 의존성이나 호출을 입증하지 않으므로 제외했다. 추가로 이름·import 토큰이 겹친 후보 6개 저장소를 commit/file/line으로 확인했다.

| 후보 저장소 | 고정 commit의 근거 | 판정 |
| --- | --- | --- |
| [szabgab/pydigger-data](https://github.com/szabgab/pydigger-data) | [feature-standards-core.json 1–4행](https://github.com/szabgab/pydigger-data/blob/75eaaf042600f2e24342f9d31d2676fa90958f2d/data/pypi/fe/feature-standards-core.json#L1-L4) · [feature-standards-core.json 10–20행](https://github.com/szabgab/pydigger-data/blob/75eaaf042600f2e24342f9d31d2676fa90958f2d/data/pypi/fe/feature-standards-core.json#L10-L20) · [feature-standards-python-auth.json 1–4행](https://github.com/szabgab/pydigger-data/blob/75eaaf042600f2e24342f9d31d2676fa90958f2d/data/pypi/fe/feature-standards-python-auth.json#L1-L4) | PyPI 메타데이터 목록 |
| [rust-lang/crates.io-index](https://github.com/rust-lang/crates.io-index) | [feature-standards-core 1–1행](https://github.com/rust-lang/crates.io-index/blob/866dcc269703607801fc412bfbe7a56d5aa0141d/fe/at/feature-standards-core#L1-L1) · [feature-standards-auth 1–1행](https://github.com/rust-lang/crates.io-index/blob/866dcc269703607801fc412bfbe7a56d5aa0141d/fe/at/feature-standards-auth#L1-L1) | crates.io의 패키지 자체 인덱스 |
| [azens1995/java-spring-auth](https://github.com/azens1995/java-spring-auth) | [pom.xml 12–14행](https://github.com/azens1995/java-spring-auth/blob/239560cc34097df9ef1b653e9acbf5e15cdf9f36/pom.xml#L12-L14) | 다른 Maven 아티팩트의 이름 충돌 |
| [azens1995/java-spring-auth-features](https://github.com/azens1995/java-spring-auth-features) | [pom.xml 12–14행](https://github.com/azens1995/java-spring-auth-features/blob/e85baf03d61817f9543c7ea7d5ad93a65e5db2b5/pom.xml#L12-L14) | 다른 Maven 아티팩트의 이름 충돌 |
| [Cr2do/spring-boot-authentication](https://github.com/Cr2do/spring-boot-authentication) | [pom.xml 11–13행](https://github.com/Cr2do/spring-boot-authentication/blob/5013c747cd80df1f2e25b4b15ca46c094fbedb3c/pom.xml#L11-L13) | 다른 Maven 아티팩트의 이름 충돌 |
| [wavekanit/Java-Spring-Authen-System](https://github.com/wavekanit/Java-Spring-Authen-System) | [pom.xml 12–14행](https://github.com/wavekanit/Java-Spring-Authen-System/blob/dacdb1ccaf984970689fa735dbb226d4544bbd53/pom.xml#L12-L14) | 다른 Maven 아티팩트의 이름 충돌 |
| [Daniel112300/my-website](https://github.com/Daniel112300/my-website) | [app.py 32–33행](https://github.com/Daniel112300/my-website/blob/d32a982be172dc79bc04309164496b94eaa981f3/main_end/my-website-main/smart-energy/app.py#L32-L33) · [feature_auth.py 1–5행](https://github.com/Daniel112300/my-website/blob/d32a982be172dc79bc04309164496b94eaa981f3/main_end/my-website-main/smart-energy/feature_auth.py#L1-L5) · [requirements.txt 1–9행](https://github.com/Daniel112300/my-website/blob/d32a982be172dc79bc04309164496b94eaa981f3/main_end/my-website-main/smart-energy/requirements.txt#L1-L9) | 같은 저장소의 Flask 모듈 |
| [Shadow-linux/agent-loop](https://github.com/Shadow-linux/agent-loop) | [check-feature-context.py 21–30행](https://github.com/Shadow-linux/agent-loop/blob/48a8460b92130b20edd132ceb19884cf8e9c8145/scripts/check-feature-context.py#L21-L30) · [check-concept-foundation-trace.py 20–23행](https://github.com/Shadow-linux/agent-loop/blob/48a8460b92130b20edd132ceb19884cf8e9c8145/scripts/check-concept-foundation-trace.py#L20-L23) · [check-requirement-product-definition.py 22–25행](https://github.com/Shadow-linux/agent-loop/blob/48a8460b92130b20edd132ceb19884cf8e9c8145/scripts/check-requirement-product-definition.py#L22-L25) | feature_authority_support 부분문자열 충돌 |

Java 후보의 실제 좌표는 각각 `dev.eklak:java-spring-auth`, `dev.eklak:java-spring-auth-features`, `com.example:java-spring-authentication`, `com.wavekanit:Java-Spring-Authen-System`였다. 대상 `io.github.jongko54:java-spring-auth`와 다르다.

Daniel112300의 `feature_auth`는 같은 저장소의 Flask Blueprint 파일로 연결된다. Shadow-linux의 3개 검색 파일은 `feature_authority_support`라는 다른 모듈이다. 부분문자열 검색 결과를 대상 패키지 import로 인정하지 않았다. 이 판정은 해당 히트가 대상을 입증하지 못한다는 뜻이며 저장소 전체의 미사용 증명은 아니다.

자체 자료에는 선언과 API 호출이 있다. 원본의 [Go 예제 manifest](https://github.com/jongko54/feature-standards/blob/5119bad602dc6354824adf055c36f6922cdd115c/examples/core-go/go.mod#L5-L8)는 두 모듈을 직접 선언하고, [제품 예제 코드](https://github.com/jongko54/feature-standards/blob/5119bad602dc6354824adf055c36f6922cdd115c/examples/core-go/main.go#L135-L153)는 `policy.Decide`, `listing.ParseQuery`, `listing.Page`를 호출한다. 같은 소유자의 원본 예제이므로 외부 사용 수에 포함하지 않았다.

## 공개 의존성 그래프에서 관측한 값

| 출처 | 조회 범위 | 관측 결과 | 해석 한계 |
| --- | --- | --- | --- |
| [deps.dev GetDependents](https://docs.deps.dev/api/v3alpha/#getdependents) | npm·PyPI·Cargo·Maven 10개 패키지의 버전 23개 | 각 응답 direct·indirect·전체 dependent 모두 0, HTTP 200 | 공개 패키지 관계 수. 프로젝트 수가 아니며 버전별로 합산하지 않음 |
| [crates core](https://crates.io/api/v1/crates/feature-standards-core/reverse_dependencies?page=1&per_page=100) · [auth](https://crates.io/api/v1/crates/feature-standards-auth/reverse_dependencies?page=1&per_page=100) | 두 crate, page 1, per_page 100 | 각각 `meta.total=0`, 빈 목록 | crates.io 등록 패키지 관계만 관측 |
| [Go authorization](https://pkg.go.dev/github.com/jongko54/feature-standards/libraries/go/authorization?tab=importedby) · [listing](https://pkg.go.dev/github.com/jongko54/feature-standards/libraries/go/listing?tab=importedby) · [auth](https://pkg.go.dev/github.com/jongko54/feature-standards/implementations/go-net-http/auth?tab=importedby) | 실제 import 가능한 하위 패키지 3개 | 모두 알려진 importer 없음 표시 | 모듈 루트로 대체하지 않았으며 미색인 사용은 알 수 없음 |
| [GitHub Dependents](https://github.com/jongko54/feature-standards/network/dependents) | 기본 화면 + 노출된 패키지 선택 8개 | 모두 dependent 없음 화면, 다음 페이지 링크 없음 | PyPI·Maven 선택은 별도로 식별되지 않음. 같은 패키지명의 생태계도 모호함 |

deps.dev의 23개 버전은 prerelease가 아닌 게시 버전 18개, staging prerelease `0.0.0-stage` 4개, `0.0.0-bootstrap` 1개로 나누었다.

| 패키지 역할 | prerelease 아닌 게시 버전 | stage | bootstrap |
| --- | ---: | ---: | ---: |
| 컨텍스트 CLI | 5 | 1 | 1 |
| 앱 생성 CLI | 3 | 1 | 0 |
| React 인증 SDK | 3 | 1 | 0 |
| TypeScript core SDK | 1 | 1 | 0 |
| PyPI·Cargo·Maven SDK 합계 | 6 | 0 | 0 |
| 합계 | 18 | 4 | 1 |

Go 게시 버전 2개까지 포함한 레지스트리 버전은 총 25개다. [deps.dev 공식 범위 설명](https://docs.deps.dev/api/v3/#coverage)상 색인 대상과 시차가 있으므로 위 값은 전체 사용량이 아니다. GetDependents 지원 생태계에 Go는 없어, 이를 0으로 채우지 않고 pkg.go.dev 결과를 별도로 기록했다.

## 검색 범위와 남은 공백

GitHub connector를 먼저 사용해 패키지명·Go 경로·Java namespace와 Python/Rust import 후보를 조회했다. connector에는 plain string을 사용했다. 후보는 commit을 고정한 파일로 확인했다. 결과 상한이나 상태가 부족한 부분은 기존 인증 상태의 read-only `gh api` 공식 REST 조회로 보완했다.

- connector는 최초 broad query를 포함해 23개 고유 쿼리를 기록했다. `topn=100`이고 전체 결과 수·페이지·완전성 상태는 제공되지 않는다. `feature-standards`, `feature_auth`, `from feature_auth import` 같은 broad 쿼리는 상한에 도달해 전수 검색으로 취급하지 않았다.
- REST 17회는 원문 쿼리·HTTP/rate 헤더·page=1·per_page=100·total_count·incomplete_results를 보존했다. 반환 파일은 쿼리당 최대 4개라 추가 페이지는 없었다. 원본 대조군 2회는 모두 불완전 결과였다.
- connector의 React 인증 이름 검색 1회가 429를 반환했고 안내된 10초 뒤보다 늦게 재조회해 성공했다. grep.app은 429/challenge로 실패해 **미확인**으로 남겼다.
- 공개 웹의 정확한 패키지·namespace 검색은 레지스트리와 배포 목록 언급을 찾았다. NicheDB의 과거 검색 스니펫은 현재 첫 페이지에서 재현되지 않아 언급 후보로만 남겼다.
- 비공개 저장소, GitHub 밖의 소스, 미색인 파일·기본 브랜치 외 코드, 동적 설치, 일회성 npx/CLI, vendoring·이름 변경·복사 구현은 전체 수를 알 수 없다.
- 소스 연결이 발견돼도 실제 실행·운영 적용·AI 작성 여부·모델 자율 선택·활성 사용자·재사용률은 별도 증거가 필요하다. 해당 계측은 추가하지 않았다.

[GitHub 공식 검색 문서](https://docs.github.com/en/rest/search/search#search-code)는 검색 제한과 `incomplete_results`를 설명한다. 미확인 구간은 0으로 대체하지 않았다. 이후 외부 저장소의 정확한 manifest와 제품 API 호출이 확인되면 저장소 URL을 기준으로 이 목록에 추가할 수 있다.

검증 범위는 JSON 파싱, 패키지 12개·레지스트리 버전 25개·deps.dev 요청 23개의 수치 대조, 18/4/1 버전 분류, 후보 commit/file/line 및 링크·민감정보 검토다. 코드·계측·레지스트리·계정 설정은 변경하지 않았다.
