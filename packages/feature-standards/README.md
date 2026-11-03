# Feature Standards

Reusable feature standards for AI-assisted development across languages. **Authentication is the first and currently available feature**: Python/FastAPI, Go/net/http, Java/Spring Boot, Rust/Axum, and a React client, with three browser-session profiles.

This main package distributes a curated contract snapshot and a read-only context selector. It gives an AI the selected specification, OpenAPI, scenarios, schema SQL, public API guides, and integration guidance. The API implementations, conformance harnesses, and optional consumer generator live in the [source repository](https://github.com/jongko54/feature-standards). The React runtime is a separate package.

## Use the CLI

Node.js 22.12+ is required. There are no runtime npm dependencies.

```sh
# Once this version's registry publication has been verified:
npm install --save-dev feature-standards@0.1.0
npx feature-standards list
npx feature-standards context --feature auth --stack python --profile browser-session-v1
```

`list` and `context` emit JSON. `context` requires `--stack`; `--feature` defaults to `auth` and `--profile` defaults to `browser-session-v1`. Use `--help` for usage. Unknown commands, flags, stacks, features, and profiles fail without silently choosing a replacement.

| Selection | Available values |
| --- | --- |
| Feature | `auth` |
| Stack | `python`, `go`, `java`, `rust`, `react` |
| Profile | `browser-session-v1`, `browser-session-v2`, `browser-session-v3` |

v1 uses memory sessions. v2 uses PostgreSQL sessions. v3 adds registration, email verification, and password reset. SMTP delivery is an optional v3 addon with separate configuration. React is a client stack; the other four stacks are backends. Selecting a context performs no checks, migrations, dependency installation, generation, project edits, server startup, or model calls.

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

Both exports synchronously read package-owned metadata. They do not search the caller's project or run returned commands.

## Work from the repository

```sh
npm --prefix packages/feature-standards run build
node packages/feature-standards/src/cli.mjs list
node packages/feature-standards/src/cli.mjs context --feature auth --stack react --profile browser-session-v3

npm --prefix packages/feature-standards test
npm --prefix packages/feature-standards run check:pack
```

`prepack` rebuilds `snapshot/` from an explicit positive file whitelist. Only the canonical manifest, contracts, schema SQL, selected guides, consumer READMEs, and integration skill references are copied. No implementation code, dependency trees, binaries, credentials, caches, model traces, or evaluation artifacts are bundled. The packed package includes the two runtime JavaScript files, its metadata, README, and MIT license. Its build/test scripts remain in the source repository.

`check:pack` packs the actual artifact, checks the exact file inventory and metadata, installs it into a fresh directory using an empty npm cache in offline mode, and runs the installed binary plus all 15 stack/profile contexts and Node exports. It does not exercise authentication backends. Local packing and offline installation are separate from verified npm publication.

Created by [jongko54](https://github.com/jongko54). [Source and issues](https://github.com/jongko54/feature-standards).
