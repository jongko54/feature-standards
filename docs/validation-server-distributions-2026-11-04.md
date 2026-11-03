# Server distribution consumers — 2026-11-04 KST

Local Python, Java, and Rust distribution consumers passed using committed source `2a486ae11d8de95ee9eed8aef01f70e3b9a6b3bc`. The new checker was run from the working tree; unrelated CLI implementation work made the overall checkout dirty. It archived only committed server and consumer paths, verified those selected paths remained unchanged, and removed its own temporary library source copies before the consumer checks. No original source, database, SMTP account, registry account, or publisher setting was changed.

| Stack | Artifact | Consumer evidence | Artifact SHA-256 |
|---|---|---|---|
| Python | `feature-standards-python-auth` `0.2.0` wheel; sdist also built | Fresh external virtual environment; `feature_auth.create_app`, `current_user`, version identity, memory lifespan and health function passed after the private library source copy was deleted | `230d62022cf469909a66138ac1a17d8cdd2a60cab5de484f54228e407d473df4` |
| Java | `io.github.jongko54:java-spring-auth:1.0.0:jar:library` | Fresh private Maven repository and blank settings; 4 independent consumer tests passed, including the classloader's installed plain JAR, real loopback login/logout and safe store-error behavior | `323597957adcd6d70af7a551fafcea5d798aef5bf31074a117dd0c1873e06391` |
| Rust | `feature-standards-auth` `0.1.0` `.crate` | Normal `cargo package --locked` verification; external consumer compiled against the unpacked crate and passed its memory lifecycle test after the private library source copy was deleted | `8ee9bfde1dd9292380f23f191f0a58bbaad8d4cdf2d301ee88ab244dcf9648fc` |

The artifact hashes identify these local build results. They are not claimed to be public registry artifacts. The wheel's Python probe called the public health function within its real lifespan; it did not make an HTTP request. The Rust consumer used an in-process Axum router; Java used a real loopback server. No PostgreSQL or SMTP test was run by this checker. Cargo may use existing dependency download caches, but its output directory and consumer dependency on the unpacked crate were private to this run.

## Commands and fixture checks

```sh
uv run --frozen --project tools python tools/check_server_distributions.py --stack python
uv run --frozen --project tools python tools/check_server_distributions.py --stack java
uv run --frozen --project tools python tools/check_server_distributions.py --stack rust
uv run --frozen --project tools python -m unittest discover -s tests -p test_server_distributions.py -v
uv run --frozen --project implementations/python-fastapi ruff check tools/check_server_distributions.py tests/test_server_distributions.py
```

The local runs used Python `3.13.13`, Temurin JDK `21.0.13+9` through `JAVA_HOME`, Cargo/rustc `1.93.1`, and uv `0.11.11`. Seven focused fixture tests passed. They cover wrong wheel identity or missing public package, executable/reference application content masquerading as a reusable JAR, archive path/link escapes and duplicate members, rejection of unsupported stack selection before building, and stripping inherited runtime/publisher settings while preserving the real `HOME`. The wrong-wheel-version test first failed because the initial reader accepted `9.9.9` where `0.2.0` was expected, and passed after strict identity validation was added. Ruff check and formatting passed.

The Maven build used `install`, never `deploy`, and did not activate the `central-release` profile. Its wrapper cache, repository and settings were private, and `MAVEN_SKIP_RC=true` prevented user startup scripts from changing the fixture. The existing [Maven signed-bundle checker](maven-release.md) covers temporary test-key signing and no-upload bundle validation separately.

## Public registry observations

At `2026-11-03T15:36:55Z` (`2026-11-04 00:36:55 KST`), independent public HTTP lookups returned:

| Registry target | Result |
|---|---|
| PyPI JSON metadata for `feature-standards-python-auth` | HTTP 404 |
| Maven Central POM for `io.github.jongko54:java-spring-auth:1.0.0` | HTTP 404 |
| crates.io metadata for `feature-standards-auth` | HTTP 404 |
| Go proxy `implementations/go-net-http@v0.1.0` info | HTTP 200; prior external installation receipt remains in [Go release record](go-release-0.1.0.json) |

These are dated availability observations, not an account-permission diagnosis. They may change after the maintainer completes publication. Python needs the matching PyPI project/pending trusted publisher; Java needs Central namespace ownership, a private user token and a real signing key; Rust needs the crate's initial ownership/account setup and configured publishing authentication. The existing [server release guide](server-releases.md) names the exact repository, workflow and environment bindings. Local artifact success alone does not establish any of those account outcomes.
