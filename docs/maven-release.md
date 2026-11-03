# Maven Central release preparation

The Java package is `io.github.jongko54:java-spring-auth:1.0.0`. Its reusable JAR has classifier `library`; the main artifact remains the executable reference server. Sources, Javadoc, the POM, and MIT license metadata are included. No Central publication is established by a local build.

## Check the signed bundle without uploading

Requirements: JDK 21+, Python 3.12+, GnuPG (`gpg` and `gpgconf`), and access to public Maven repositories for dependency downloads. From the repository root:

```sh
uv run --frozen --project tools python tools/check_maven_release.py
```

Set `JAVA_HOME` to a JDK 21 installation if needed. The command builds a temporary POM against the checkout's Java sources and resources. Build output, the wrapper distribution cache (`MAVEN_USER_HOME`), and the Maven artifact repository stay in a private temporary directory. It sets `MAVEN_SKIP_RC=true`, supplies blank user/global Maven settings and a small environment allowlist, and creates a synthetic, one-day signing key in a temporary GPG home. The existing `HOME` value is preserved while user Maven startup configuration is bypassed. It does not use the maintainer's signing key or registry credentials.

The temporary Central Publishing 0.12.0 configuration forces `skipUpload=true`, disables published-component queries, and replaces the Central endpoint with a loopback HTTP trap. The command requires zero trap requests. The [official plugin documentation](https://central.sonatype.org/publish/publish-portal-maven/#skipupload) distinguishes this bundle-only mode from `skipPublishing`, which omits artifacts and produces no bundle.

The checker verifies:

- The expected coordinate directory and required POM identity, license, developer, and SCM metadata.
- The POM, executable, library, sources, and Javadoc artifacts.
- Five detached GPG signatures and twenty MD5/SHA-1/SHA-256/SHA-512 artifact checksums.
- MIT notices in every JAR, actual source/Javadoc content, and a reusable library without `BOOT-INF`, the reference application, or its application settings.
- Unchanged source/POM fingerprints and no Central requests.

The JSON result explicitly reports `test_key_only=true` and `published=false`. The temporary key, signed fixture bundle, and GPG agent are removed afterward. The fixture bundle is not a production release artifact. A new signing key and signature timestamps can change its hash between runs. Public dependency reads mean this check is not an air-gapped build, and it is not a sandbox for untrusted build input.

## Complete the real publisher setup

1. Sign in to [Central Portal](https://central.sonatype.com/) with the intended GitHub account and verify access to namespace `io.github.jongko54`. GitHub-based namespace provisioning can simplify proof of ownership, but the local checker neither creates nor verifies that account. Follow the [namespace instructions](https://central.sonatype.org/register/namespace/).
2. Create a Central user token privately. Configure server ID `central` in a private Maven settings file using that token's username/password. Do not put those values in the repository, command line, issue, or CI log.
3. Select an existing approved production GPG signing key, or provision one separately under the maintainer's control. Make its public key discoverable according to [Central's signing requirements](https://central.sonatype.org/publish/requirements/gpg/). Keep the private key and passphrase outside the repository. The synthetic fixture key cannot replace this step.
4. Review the release commit, require successful full source CI, and ensure version `1.0.0` is available. Central versions are immutable. The local bundle check does not reserve a coordinate, authenticate an account, or prove Portal acceptance.

With that setup complete, this command performs the actual permanent upload and publication:

```sh
implementations/java-spring/mvnw \
  --settings /absolute/path/to/private-settings.xml \
  -f implementations/java-spring/pom.xml \
  -Pcentral-release -Dgpg.bestPractices=true \
  -Dgpg.keyname=YOUR_PRODUCTION_KEY_FINGERPRINT clean deploy
```

The checked-in release profile signs the artifacts and waits for Central to report publication. Keep its actual release output separate from the no-upload fixture result. After publication, verify the Central coordinate and install it in a new consumer without a local Maven install/cache override:

```xml
<dependency>
  <groupId>io.github.jongko54</groupId>
  <artifactId>java-spring-auth</artifactId>
  <version>1.0.0</version>
  <classifier>library</classifier>
</dependency>
```

The Java package namespace remains `dev.featurestandards.auth`. See the [official Central artifact requirements](https://central.sonatype.org/publish/requirements/) and [Apache Maven GPG plugin parameters](https://maven.apache.org/plugins/maven-gpg-plugin/sign-mojo.html) for the relevant metadata and signer settings.
