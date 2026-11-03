# Find Feature Standards as jongko54

**`feature-standards` is the main package and product entry point.** It helps AI agents choose a feature, profile, and stack, find the shared contract and public API guidance, reuse the matching implementation, and run conformance explicitly. Authentication is the first available feature. The React adapter and authentication generator are companion components.

| Role | Package ID | Prepared version |
|---|---|---|
| Main feature catalog and JSON context CLI | `feature-standards` | `0.1.0` |
| Browser authentication API adapter | `@ugauga/feature-standards-react-auth` | `0.1.4` |
| Authentication application generator for four server stacks | `@ugauga/create-feature-auth` | `0.1.1` |

All three package manifests identify their author as [jongko54](https://github.com/jongko54), include the `jongko54` and `feature-standards` keywords, and contain the handle in their descriptions. Their package READMEs link the author. This metadata supports discovery; it does not change the package IDs or guarantee an npm search position.

Search the public registry with:

```sh
npm search jongko54
npm search 'keywords:jongko54'
```

The two authentication components use the npm account scope `ugauga`; `jongko54` is the GitHub author handle. The main package uses the unscoped name `feature-standards`. A source change does not update registry metadata, and a successful `npm pack` does not publish it.

## Use the source before publication is confirmed

From the repository root, the main entry point is:

```sh
npm --prefix packages/feature-standards run build
node packages/feature-standards/src/cli.mjs list
node packages/feature-standards/src/cli.mjs context \
  --feature auth --stack python --profile browser-session-v1
```

The main package includes curated contracts, a manifest, and stack guides. Its JSON output provides guidance and does not execute commands. Server runtime libraries and executable harnesses require the source checkout or their separate distributions. See the [main package guide](../packages/feature-standards/README.md) and [AI integration guide](ai-integration.md).

Only after the prepared main version is published and independently installed from the registry should its npm command be used:

```sh
npx feature-standards@0.1.0 list
npx feature-standards@0.1.0 context \
  --feature auth --stack react --profile browser-session-v3
```

## Verify publication and search separately

The initial namespace setup may publish `feature-standards@0.0.0-bootstrap` under the **`bootstrap`** dist-tag. This separate three-file archive contains only metadata, README, and license so the existing npm account can configure a GitHub trusted publisher. It has no CLI or runtime exports and is not the normal `latest` release. The complete catalog remains `0.1.0`; use it only after its registry publication and fresh installation are verified. The release workflow keeps the bootstrap artifact separate from the normal package artifact and never publishes it automatically.

Inspect each actual tarball's name, version, author, keywords, description, and README before upload. After publishing, check the exact registry version and integrity, install it in a new project, then inspect `npm search jongko54` and the keyword query separately. Search indexing may differ from registry availability. Record the query date and observed package IDs instead of assuming an index update from the metadata patch.

Earlier release work observed `web-embedding` in the `jongko54` query before these discovery updates. That is a historical observation, not the current search result. The [React npm release record](npm-release.md) and [server release guide](server-releases.md) track their own publication evidence. None of the prepared versions in the table is declared published or indexed by this guide alone.
