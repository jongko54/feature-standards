# Feature Standards

Reusable feature standards for AI-assisted development across languages: authentication, authorization, and pagination/sorting/filtering. Authentication has Python/FastAPI, Go/net/http, Java/Spring Boot, Rust/Axum, and React integrations. The new authorization and listing standards have framework-independent Python, Go, Java, Rust, and browser JavaScript/TypeScript libraries.

This main package distributes a curated contract snapshot, a read-only context selector, and explicit `init` / `check` entry points. It gives an AI the selected specification, OpenAPI, scenarios, schema SQL, public API guides, and integration guidance. Application generation delegates to an existing trusted source checkout; selected-profile checks execute the generated application's runner. The API implementations and conformance harnesses live in the [source repository](https://github.com/jongko54/feature-standards). The React runtime is a separate package.

## Use the CLI

Node.js 22.12+ is required. There are no runtime npm dependencies.

```sh
# The registry release is separate from this source snapshot.
npm install --save-dev feature-standards@0.3.2
npx feature-standards list
npx feature-standards context --feature auth --stack python --profile browser-session-v1
```

**This checkout is source version 0.3.2.** Its bundled core receipt verifies npm, Python, Rust, Java and Go `0.1.0` through public downloads and fresh consumers. Check actual registry availability before installing this CLI version; source readiness alone is not publication. Main 0.3.0 captured the earlier source-only core context, and 0.3.1 captured the first Python, Rust and Go core receipts. Publication fields describe this version's bundled evidence; they are not live registry queries.

`list` and `context` emit JSON. `context` requires `--stack`; `--feature` defaults to `auth`. The profile defaults to the selected feature's default in the table. Use `--help` for usage. Unknown commands, flags, stacks, features, and profiles fail without silently choosing a replacement.

| Feature | Profiles (first is the default) | Stacks |
| --- | --- | --- |
| `auth` | `browser-session-v1`, `browser-session-v2`, `browser-session-v3` | `python`, `go`, `java`, `rust`, `react` |
| `authorization` | `rbac-v1` | `python`, `go`, `java`, `rust`, `react` |
| `listing` | `offset-list-v1` | `python`, `go`, `java`, `rust`, `react` |

v1 uses memory sessions. v2 uses PostgreSQL sessions. v3 adds registration, email verification, and password reset. SMTP delivery is an optional v3 addon with separate configuration. React is a client stack; the other four stacks are backends. `list` and `context` perform no checks, migrations, dependency installation, generation, project edits, server startup, or model calls.

`rbac-v1` evaluates explicit tenant/owner grants against server-owned identities and resources. `offset-list-v1` strictly parses an allowlisted query and filters, sorts, and pages a bounded in-memory collection. The `react` selections refer to JavaScript/TypeScript helpers; browser authorization decisions are presentation advice and never replace server enforcement. Read the [core standards guide](https://github.com/jongko54/feature-standards/blob/main/docs/core-standards.md) for integration and conformance commands.

## Generate and check an application

The explicit workflow commands support `auth` only and require a trusted source checkout containing `@ugauga/create-feature-auth` version 0.2.0 or later. The source checkout is separate from this npm package. Requests to initialize `authorization` or `listing` fail before importing a generator or creating a target. Their contexts provide reusable API entrypoints and explicit source conformance commands. Existing targets, linked paths, unsupported selections, and older runners that only check memory v1 are refused.

```sh
feature-standards init --feature auth \
  --source /absolute/physical/path/to/feature-standards \
  --stack python --profile browser-session-v1 \
  --dest /absolute/physical/path/to/new-app

feature-standards check --project /absolute/physical/path/to/new-app
```

`init` creates a new application's glue and source-relative dependencies using the selected checkout's generator. It does not run builds or checks by default. Add `--check` to run the same selected-profile check immediately after creation. `check` explicitly executes trusted project code and its language toolchain; builds may download dependencies. These operations are not a sandbox for untrusted code. Neither command installs a server registry package, updates a project automatically, runs a production migration, or sends SMTP mail.

For v2 and v3 checks, explicitly provide `FEATURE_STANDARDS_TEST_DATABASE_URL` for a dedicated loopback test database whose name starts with `feature_standards_test`. The checker creates and drops its own uniquely named database and applies fixtures only there. It does not use inherited `AUTH_DATABASE_URL` as its test target and does not alter the supplied base database. The account profile also exercises registration, verification, password reset, and session revocation through that isolated fixture. See the [generator guide](https://github.com/jongko54/feature-standards/blob/main/docs/create-feature-auth.md) for requirements and exact limits.

Workflow results identify the actual stack and profile, passed checks, and whether an isolated database was used and cleaned up. The main CLI rejects mismatched profile or protocol receipts. Build output may precede the final JSON workflow result; `list` and `context` retain JSON-only output. A failed explicit check leaves the generated project available for inspection.

## Read the result

- `packagedDocuments` describes documents available inside this installed package. Each entry has an absolute `readPath`, a portable `packagePath`, an upstream `sourcePath` and `sourceUrl`, SHA-256, and a `sourceModified` flag. Read the selected API and consumer guides first, then the relevant contract sections.
- `sourceCheckout` describes runtime code and commands in a **separate trusted source checkout**. Its `checkoutPath`, `cwd`, and `argv` values are repository-relative guidance. They are not paths to API code bundled in this npm package. Commands have `scope: "source-checkout"` and `executed: false`. The existing backend generator is referenced as a source command with explicit placeholders; it is not included or invoked here.
- `optionalAddons` contains v3 mail references only when v3 is selected. It does not enable mail or execute SQL.
- `provenance` records the captured Git commit, repository dirty state, snapshot dirty state, and capture time. The full per-file inventory is in `snapshot/provenance.json`.

Source URLs point to the captured HEAD. If `sourceModified` is true, packaged bytes include local changes absent from that URL; use the recorded hash to identify those bytes. A dirty snapshot is not a claim that its content is committed upstream. Copied guides preserve upstream relative links, including some references to implementation code or tools that require the separate checkout. Live package publication is not checked by this tool: `sourceCheckout.packageMetadata` is captured catalog metadata, explicitly marked as unverified.

The package is a versioned snapshot, not an automatic update mechanism. Installing a new version does not migrate an application. This package does not establish a security certification or prove AI speed improvements.

## Use from Node.js

```js
import { listFeatures, getContext } from 'feature-standards';

const available = listFeatures();
const selected = getContext({
  feature: 'auth',
  stack: 'go',
  profile: 'browser-session-v2',
});

console.log(selected.packagedDocuments.specification.readPath);
console.log(selected.sourceCheckout.entrypoints);
```

Both selection exports synchronously read package-owned metadata. They do not search the caller's project or run returned commands. The explicit asynchronous workflow exports use the same contracts as the CLI:

```js
import { initFeature, checkProject } from 'feature-standards';

const project = await initFeature({
  feature: 'auth', source: '/trusted/physical/checkout', stack: 'go',
  profile: 'browser-session-v1', dest: '/physical/parent/new-app',
});
const receipt = await checkProject({ project: project.destination });
```

## Work from the repository

```sh
npm --prefix packages/feature-standards run build
node packages/feature-standards/src/cli.mjs list
node packages/feature-standards/src/cli.mjs context --feature auth --stack react --profile browser-session-v3
node packages/feature-standards/src/cli.mjs context --feature authorization --stack go
node packages/feature-standards/src/cli.mjs context --feature listing --stack react

npm --prefix packages/feature-standards test
npm --prefix packages/feature-standards run check:pack
```

`prepack` rebuilds `snapshot/` from an explicit positive file whitelist. Only the feature index and catalogs, contracts, schema SQL, selected guides, consumer READMEs, and integration skill references are copied. No implementation code, dependency trees, binaries, credentials, caches, model traces, or evaluation artifacts are bundled. The packed package includes the three runtime JavaScript files, its metadata, README, and MIT license. Its build/test scripts remain in the source repository.

`check:pack` packs the actual artifact, checks the exact file inventory and metadata, installs it into a fresh directory using an empty npm cache in offline mode, and runs the installed binary plus all 25 feature/stack/profile contexts and Node exports. It also checks the explicit workflow boundary against a synthetic trusted generator/runner fixture; this smoke check does not build or exercise native feature libraries or authentication backends. Actual library and generated backend/profile checks are separate. Local packing and offline installation are separate from verified npm publication.

Created by [jongko54](https://github.com/jongko54). [Source and issues](https://github.com/jongko54/feature-standards).
