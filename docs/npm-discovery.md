# Find Feature Standards as jongko54

**`feature-standards` is the main package and product entry point.** It helps AI agents choose a feature, profile, and stack, find the shared contract and public API guidance, reuse the matching implementation, and run conformance explicitly. Authentication is the first available feature. The React adapter and authentication generator are companion components.

| Role | Package ID | Published npm version |
|---|---|---|
| Main feature catalog and explicit workflow CLI | `feature-standards` | `0.2.0` |
| Browser authentication API adapter | `@ugauga/feature-standards-react-auth` | `0.1.4` |
| Authentication application generator for four server stacks | `@ugauga/create-feature-auth` | `0.2.0` |

All three package manifests identify their author as [jongko54](https://github.com/jongko54), include the `jongko54` and `feature-standards` keywords, and contain the handle in their descriptions. Their package READMEs link the author. This metadata supports discovery; it does not change the package IDs or guarantee an npm search position.

Search the public registry with:

```sh
npm search jongko54
npm search 'keywords:jongko54'
```

The two authentication components use the npm account scope `ugauga`; `jongko54` is the GitHub author handle. The main package uses the unscoped name `feature-standards`. A source change does not update registry metadata, and a successful `npm pack` does not publish it.

## Use the source checkout

From the repository root, the main entry point is:

```sh
npm --prefix packages/feature-standards run build
node packages/feature-standards/src/cli.mjs list
node packages/feature-standards/src/cli.mjs context \
  --feature auth --stack python --profile browser-session-v1
```

The main package includes curated contracts, a manifest, and stack guides. `list` and `context` provide JSON guidance without executing commands. Published version `0.2.0` adds explicit `init` and `check` commands using a trusted source checkout and generated project. Server runtime libraries and executable harnesses require the source checkout or their separate distributions. See the [main package guide](../packages/feature-standards/README.md) and [AI integration guide](ai-integration.md).

The published main version was independently installed from the registry and all 15 contexts were checked. Its npm commands are:

```sh
npx feature-standards@0.2.0 list
npx feature-standards@0.2.0 context \
  --feature auth --stack react --profile browser-session-v3
```

## Verify publication and search separately

The initial namespace setup used `feature-standards@0.0.0-bootstrap` under the **`bootstrap`** dist-tag. This separate three-file archive contains only metadata, README, and license so the existing npm account could configure a GitHub trusted publisher. It has no CLI or runtime exports. The main package's public `latest` now points to `0.2.0`, with fresh registry installation and actual workflow execution verified. The release workflow keeps the bootstrap artifact separate from the normal package artifact and never publishes it automatically.

Inspect each actual tarball's name, version, author, keywords, description, and README before upload. After publishing, check the exact registry version and integrity, install it in a new project, then inspect `npm search jongko54` and the keyword query separately. Search indexing may differ from registry availability. Record the query date and observed package IDs instead of assuming an index update from the metadata patch.

On 2026-11-03, `npm search jongko54` returned `feature-standards@0.1.0`, `@ugauga/feature-standards-react-auth@0.1.4`, and `@ugauga/create-feature-auth@0.1.1` with their updated descriptions. The [release receipt](npm-product-release-2026-11-03.json) records this observation and the main package's independent registry installation. The [npm release record](npm-release.md) and [server release guide](server-releases.md) track their own publication evidence. Search position and future indexing are separate from this dated observation.

On 2026-11-04 KST the same public query returned `feature-standards@0.2.0`, `@ugauga/create-feature-auth@0.2.0`, and the existing browser adapter `0.1.4`. The [workflow release receipt](npm-workflow-release-2026-11-04.json) records exact public artifacts, anonymous fresh installation, and real installed workflow execution.
