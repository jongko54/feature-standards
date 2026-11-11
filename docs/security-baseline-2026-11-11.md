# Security baseline: 2026-11-11

The security evidence pipeline is implemented and exercised. **The release gate
is blocked by known dependency matches.** This report does not claim the absence
of vulnerabilities, an ASVS assurance level or production readiness.

The real local scanner run assessed clean source commit
`f88ce701b24bfc70ae40ffb4a42275caf0829505`. The
[machine-readable receipt](security-baseline-2026-11-11.json) preserves tool
versions, counts, source tree, sanitized unique findings, scope and report hashes.
The [security workflow](../.github/workflows/security.yml) independently produces
fresh reports for later source commits; inspect each exact run rather than
treating this dated result as current indefinitely.

## Observed results

| Check | Actual result |
| --- | --- |
| ASVS reference map | 20 controls, 34 selected ASVS 5.0.0 requirements; upstream CSV hash/IDs verified separately |
| Dependency inventory | 1,102 package occurrences, 466 unique inventory components across Go, Maven, PyPI, crates.io and npm |
| Known dependency findings | **74 manifest occurrences / 29 unique advisory-ecosystem-package-version combinations**; gate failed |
| Limited static rules | 147 source files scanned; zero findings under the 12 local rules |
| Secret patterns | Reachable local Git refs and 536 current files scanned; zero remaining findings after exact reviewed public-digest exceptions |
| Actual scanner fixtures | All 12 static rules detected positive inputs across five languages; all five negative fixtures passed; a new synthetic secret was detected and a known public digest was ignored |
| Repository Python tests | 369 discovered: 336 passed, 33 environmental skips, zero failures |
| Source release-gate regressions | Five Node tests passed; functional CI alone, wrong commit, stale/failed/pending security evidence and invalid responses are rejected |
| Existing registry regressions | 25 Node tests including subtests passed |
| Main catalog regressions | 52 Node tests passed; fresh tarball install/26 contexts and separate bootstrap checks passed |
| Workflow and inventory validation | Actionlint 1.7.12, all checked-in workflow mirrors, local documentation links, Ruff, whitespace and official CycloneDX 1.6 schema validation passed |

The package smoke checks ran before the implementation commit and honestly
recorded dirty provenance. They did not publish packages or establish native
runtime/security outcomes for a new release. The source audit above ran after
the implementation commit with `sourceDirty: false`.

## Meaning of the findings

The unique matches include Go `golang.org/x/crypto`, resolver-selected Maven
Jackson/Tomcat/Spring/Log4j/PostgreSQL dependencies, Rust `ctutils`, and Python
`mcp`/`opentelemetry-api` from the new security-tool environment. They are not
29 independently demonstrated application exploits. Tooling dependencies and
declared/resolver-inferred consumer graphs must be separated from actual runtime
use before assigning product impact. The detailed IDs, versions, severities when
provided, source manifests and advisory links are in the JSON receipt.

No dependency-vulnerability ignore was added and no scanner error was relabeled
as a pass. The first secret scan's 13 matches were verified public SHA-256 content
digests in historical receipts. Only the exact reviewed values are exempted;
files and arbitrary hex-looking credentials remain scanned.

## Current maturity and next work

The project is a **functional beta with reproducible automated security
evidence**. It remains unsuitable for an unconditional secure/production-ready
claim while known dependency matches and explicit ASVS gaps remain unresolved.

Prioritize actual dependency-graph/reachability review, compatible patched
versions and regression validation. Then address password blocklists, cookie
prefix compatibility and product-specific field permissions. Review deployment
controls separately and obtain an independent assessment of a frozen release.

The new automated npm/PyPI/crates.io release gate requires successful exact-main
functional CI and security evidence no older than 72 hours, and records artifact
byte hashes before publishing. Manual Go/Maven or direct local publishing is
outside that gate. No registry version, account permission or deployed service
was changed by this work.

See [security methodology and limits](security.md) and
[the selected ASVS map](../security/asvs-map.json).
