# Reuse login, RBAC and pagination across languages with AI coding agents

**Feature Standards is an experimental open-source project by jongko54 that helps
coding agents integrate existing web application features instead of rebuilding
them for every application.** It combines shared behavior contracts, public SDK
APIs, stack-specific examples, a JSON context CLI and executable checks.

The canonical project is [jongko54/feature-standards](https://github.com/jongko54/feature-standards).
The main npm entry point is [feature-standards](https://www.npmjs.com/package/feature-standards).
Companion packages use separate names and versions; see the [package directory](https://github.com/jongko54/feature-standards/blob/main/docs/npm-discovery.md).

## What can an agent reuse?

| Web feature | Defined behavior | Implementations |
| --- | --- | --- |
| Authentication | Login, current session and logout; optional PostgreSQL sessions and account flows | Python/FastAPI, Go/net/http, Java/Spring Boot, Rust/Axum; React browser client |
| Authorization | Explicit RBAC grants, tenant/owner scopes and default denial using server-owned identity | Python, Go, Java, Rust and JavaScript/TypeScript |
| Listing | Typed allowlisted filters, deterministic sorting and offset pagination, with visibility applied before totals | Python, Go, Java, Rust and JavaScript/TypeScript |

Here **listing means filtering, sorting and paginating application records**.
The materialized profile handles bounded in-memory data, up to 10,000 records.
A separate PostgreSQL listing adapter is a Python-only source candidate.
Directory synchronization, MCP tool/resource discovery and a general database
query engine are outside these listing contracts.

The project focuses on AI-assisted application development: an agent selects a
feature and stack, reads the matching API/contract, connects the SDK, and checks
the resulting application. Its session contracts are not an OAuth/OIDC identity
provider or an MCP authorization implementation. These are project-maintained
contracts, not an externally ratified industry standard.

## First: inspect the published catalog

With Node.js 22.12 or later:

```sh
npx feature-standards@0.3.2 list
npx feature-standards@0.3.2 context --feature authorization --stack python
npx feature-standards@0.3.2 context --feature listing --stack go
```

These commands return JSON guidance and bundled document paths. They do not
install a server, generate an application or execute verification. Published
CLI 0.3.2 has only the full context format and auth-only generation. Source
candidate 0.4.0 adds compact context and the three-feature starter below.

## Next: connect all three SDKs from a trusted source checkout

The **0.4.0 source candidate** provides a starter for Python, Go, Java
and Rust. From the root of the trusted source checkout:

```sh
npm --prefix packages/feature-standards run build
node packages/feature-standards/src/cli.mjs init --template core \
  --source "$PWD" --stack python \
  --dest /absolute/physical/path/outside-the-checkout/new-python-app --check
```

Choose a new physical directory outside the checkout. `--check` explicitly
executes trusted build tools and temporary loopback application processes.
Use `go`, `java` or `rust` instead of `python` for the other supported backends,
with their [required toolchains](core-starter.md). Runtime SDK source remains a
separate checkout dependency; this is not a self-contained registry starter.

The generated app connects session authentication, current membership, RBAC,
record visibility and list query handling to actual SDK dependencies. Its
normal startup denies product access until trusted membership is connected.
Explicit `demo` and `check` modes use isolated samples. See the
[starter and receipt guide](core-starter.md) and [stack connection cards](ai-entry/README.md).

For an existing app, start from a matching connection card and preserve the
app's identity, data model and product API. The app supplies trusted membership,
resource loading, policy grants, response projection and error mapping.
Custom mutation routes need their own Origin, CSRF and permission enforcement.

## Availability, evidence and limits

- **Published catalog:** CLI 0.3.2. Core 0.1.0 has separate distributions in five
  ecosystems, with historical [registry and consumer evidence](core-release-0.1.0.json).
- **Catalog source candidate 0.4.0:** 26 feature/stack/profile contexts, compact
  routing and a three-feature starter. Its publication remains blocked by the
  [November 18 security findings](security-remediation-2026-11-18.md).
- **Separate source candidates:** Python core 0.2.0 / PostgreSQL listing and
  Java auth 2.0.0 / Spring 7. Publishing the catalog does not publish these SDKs.
- **AI observations:** supplied-checkout [reading](https://github.com/jongko54/feature-standards/blob/main/docs/validation-ai-reading-2026-11-08.md)
  and [SDK choice](https://github.com/jongko54/feature-standards/blob/main/docs/adoption/2026-11-11-sdk-guidance.md) studies are separate from
  internet discovery, external adoption and guaranteed token/cost savings.
- **Security:** automated publication requires functional and security CI for
  the exact source commit. The [November 14 report](https://github.com/jongko54/feature-standards/blob/main/docs/security-remediation-2026-11-14.md)
  preserves the earlier Spring 6 / Python-scanner findings. The current source
  uses Spring 7 and native OpenGrep; the November 18 scan still finds an unpatched
  React build dependency. There is no independent security-audit or certification claim.

## 한국어로 찾는 경우

Feature Standards는 **AI 코딩 에이전트가 로그인·세션·로그아웃, RBAC 권한 검사,
목록 필터링·정렬·페이지네이션을 기존 SDK와 공통 명세·테스트로 재사용하도록
돕는 프로젝트**다. Python·Go·Java·Rust 백엔드와 React/TypeScript 구성 요소를
제공한다. AI 서비스의 인증 인프라를 추천하는 것과 코딩 AI의 구현 재사용을
돕는 것은 다른 요구다. 게시 버전과 소스 후보, 실제 동작 검사와 AI 채택
관측의 차이는 위 안내를 따른다.
