# Release the three-feature source

The user requested publication after source implementation. Preserve existing auth releases and APIs. Publish main catalog 0.3.0 from the already verified `2a9490a` source. Prepare the new core 0.1.0 npm, Python, Rust, Java and versioned Go module distributions; no auth version bump is needed.

1. Require successful full source CI; publish the main CLI using its existing tag/OIDC workflow and verify public metadata plus the exact tarball.
2. Make core distributions self-contained: curated file lists, package README with usable imports, Rust packaged test fixtures checked against the canonical vectors, Maven license/sources/Javadoc and production signature support. Keep metadata `published: false` until a public receipt exists. Use explicit release metadata and build-only tests before external publication.
3. Build and test archives in fresh external consumers, run relevant native/catalog/workflow checks, commit/push preparation and require the same source commit's full CI. Release tags remain immutable.
4. Publish each prepared coordinate through available maintainer authentication. Existing npm CLI login has expired; the existing CLI publisher can still use OIDC. Cargo credentials and production GPG key are present. PyPI and new npm names require a first-publish credential or an exact new-project publisher configuration. Use logged-in registry UI where available; never print secrets or add them to source. If authentication requires the user, prepare and verify all artifacts first and provide the exact remaining step while continuing independent releases.
5. Verify public downloads, checksums and fresh registry consumers for each successful target. Record each registry independently and update discovery metadata/documents only from receipts. Creating a publisher or building a local archive is not publication. Do not claim new native HTTP implementations or AI speed measurements.

Rollout is additive: authentication packages are unchanged. Registry versions cannot be overwritten; inspect public state before retrying any accepted upload. Do not unpublish or move tags as rollback.
