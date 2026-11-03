# Cross-language feature catalog and product entry point

## Goal and boundaries

Present Feature Standards as shared feature contracts and reusable implementations for AI development across languages. Authentication is the first currently implemented feature. Preserve the existing React adapter and authentication generator as components, with no runtime contract changes or unmeasured speed claims.

## Milestones

1. Reframe the English README and AI/discovery/generator guides around feature → profile → stack → public API → reuse → conformance.
2. Add `packages/feature-standards`, a dependency-free, read-only npm CLI and Node API. `list` exposes available features; `context` selects one of five stacks and three profiles. Bundle only an explicit whitelist of canonical contracts and guides. Separate installed document paths from source-checkout runtime paths, and record source commit, dirty state, and document hashes. Reject unsupported or ambiguous selection arguments.
3. Integrate the main package into `tools/release_metadata.py`, main CI, and npm release workflows/templates. Bind `feature-standards-v0.1.0` to the real package version and retain the successful exact-main-CI requirement, selected-target dry run, and post-publication integrity check.
4. Verify the actual tarball with a fresh empty-cache offline install, installed CLI, all 15 contexts, Node exports, exact file inventory, author and discovery keywords. Independently review package boundaries and claims. Commit and push only these changes, then verify the remote ref and full CI.
5. Publish using the existing authenticated npm account and GitHub trusted publishing. New package names must exist before a trusted publisher can be configured. A separately built three-file `feature-standards@0.0.0-bootstrap` uses only the `bootstrap` dist-tag to establish the namespace; it contains no executable API. Inspect the CI artifact before authenticated publication. Configure the matching publisher, then publish the normal `0.1.0` artifact through the guarded tag workflow. Existing component packages retain their own names and release versions.

## Verification and rollout

Run `npm --prefix packages/feature-standards test`, `run check:pack`, and `run check:bootstrap`; release metadata unit tests; actionlint and workflow template comparisons; and `git diff --check`. Full CI establishes the exact committed integration state. Registry receipt, tarball integrity, fresh registry install and package search are separate checks; metadata does not guarantee search rank or indexing time.

No credentials or raw traces enter packages or Git. Authenticated account challenges require the user to complete npm's own browser flow; do not request secrets or reuse expired links. No additional approval is needed for the already authorized implementation, push, or publication. Failed immutable version tags stay intact. Do not unpublish existing versions as rollback; stop further publication and repair with a new version if required.
