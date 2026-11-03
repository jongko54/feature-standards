# React 인증 API npm 배포

패키지는 `@ugauga/feature-standards-react-auth`이며 ESM 루트와 `/api` export를 제공한다. npm 계정 `ugauga`의 scope를 사용한다. 현재 계정에서 기존 `@feature-standards` scope 조회가 404로 반환되어, 확인된 개인 scope로 내부 checkout 이름을 옮겼다. 인증 HTTP 계약과 API 함수 동작은 유지한다.

## 배포본

배포 파일은 `lib/api.js`, `lib/api.d.ts`, `README.md`, `LICENSE`, `package.json` 다섯 개다. `tsconfig.lib.json`은 API 모듈만 JavaScript·선언 파일로 빌드하며, Vite의 참조 화면 빌드와 별도로 동작한다. React·개발 도구는 devDependencies이고 배포 API에는 런타임 npm 의존성이 없다.

```sh
cd clients/react
npm ci
npm test
npm run build
npm run check:package
```

`check:package`는 실제 `npm pack`을 수행해 파일 목록을 확인하고 새 임시 프로젝트에 기본 npm install로 설치한다. 루트·`/api` import, 로그인/로그아웃 요청과 오류, TypeScript 선언을 검사한다. `prepack`이 라이브러리를 빌드하고 `prepublishOnly`가 단위·패키지 검사를 실행한다. CI도 패키지 검사를 수행한다.

파일 의존성을 쓰는 소비 예제는 새 이름으로 갱신했다. PostgreSQL의 실제 소비 앱 브라우저 3개(익명 거절, 로그인·복원·보호 API·로그아웃, 두 번째 사용자 분리)를 실행했다. 서버 계약·마이그레이션은 바꾸지 않았다.

게시 전 source commit을 만들고, 검증한 tarball을 `npm publish TARFILE --access public --tag latest`로 게시한다. npm이 요구하는 계정 인증·2FA는 사용자 계정에서 완료한다. 토큰을 저장소·CI 설정에 추가하지 않는다. 게시 후 registry의 version·dist integrity와 새 프로젝트 설치를 별도로 확인한다. 실제 게시 상태와 receipt는 아래에 기록한다.

## 0.1.1 — English documentation patch

The latest npm version is `0.1.1`. Both the project README and the package README are in English, and the package description has been refined. The registry README and description match the checked-in English source. [Verification receipt](npm-release-0.1.1.json).

- Source commit: `8c71e7c938bbef7d955ae870e90c55cfeff53f32`
- Tarball: 4,518 bytes, five files
- The registry tarball matches the reviewed artifact's SHA-512 integrity.
- A fresh registry installation passes root and `/api` ESM import and strict TypeScript checks.
- Runtime JavaScript, type declarations, and the license are byte-identical to `0.1.0`.

## 0.1.0 publication record

2026-11-03 KST, [npm 0.1.0](https://www.npmjs.com/package/@ugauga/feature-standards-react-auth) 공개와 `latest=0.1.0`을 확인했다. npm의 접수 성공 후 처리 시간이 있었으며, 실제 registry에 version·dist가 나타난 뒤 검증했다. [기계 판독 receipt](npm-release-0.1.0.json)를 함께 보관한다.

- 배포 source commit: `b39110b06343da741ab41c0a18ca5e4017f19c28`
- 배포 tarball: 4,782 bytes, 파일 5개
- registry dist integrity: `sha512-WVOPNTI7gpp/IZRf6Ylj3OZSpdBmR12xUNHSQZRsQNwkJ87/KYLN6qxun/06mkuWoGLoQOsjMeqZJWYA3Dc00A==`
- 인증 헤더 없이 metadata·tarball 다운로드 성공, 버전·원본 바이트 일치
- 검증한 tarball·registry dist·새 설치의 package-lock integrity 일치
- 별도 프로젝트에 실제 npm registry 버전 설치 성공
- 루트·`/api` ESM export 동일성과 로그인·로그아웃 요청·오류 처리 확인
- 설치된 선언 파일을 사용하는 TypeScript strict/NodeNext 검사 통과
- source commit의 [전체 CI 통과](https://github.com/jongko54/feature-standards/actions/runs/41476781454)

```sh
npm install @ugauga/feature-standards-react-auth
```

로컬 tarball 설치와 실제 registry 설치를 각각 확인했으며, 위 게시물은 API 클라이언트다. 참조 화면은 저장소에서 실행한다. 이후 버전은 기존 npm 버전을 덮어쓰지 않고 새 버전으로 게시한다.

## Automated releases with OIDC

`.github/workflows/publish-npm.yml` tests and packs the main `feature-standards` catalog and both authentication components. A manual dispatch only builds. Version tags `feature-standards-vX.Y.Z`, `npm-react-auth-vX.Y.Z`, and `npm-create-feature-auth-vX.Y.Z` select one artifact, and its metadata must match the exact tag. The publish job requires full main-branch CI to have succeeded for the same source commit. Node 24 and npm 12.2.1 support this trusted publishing flow.

Configure each existing package's npm trusted publisher with repository `jongko54/feature-standards`, workflow `publish-npm.yml`, environment `npm`, and publish permission. The CLI's first release requires ordinary npm authentication before its publisher can be connected. This account action requires npm 2FA; creating the workflow alone does not activate it.

```sh
npm exec --yes --package=node@24 --package=npm@12.2.1 -- npm trust github \
  @ugauga/feature-standards-react-auth --repo jongko54/feature-standards \
  --file publish-npm.yml --env npm --allow-publish --yes --browser=false
# After its first release, repeat for @ugauga/create-feature-auth.
```

No long-lived NPM_TOKEN is added. The job publishes the exact built tarball and verifies registry version, SHA-512 integrity, and a public tarball download. Confirm activation with `npm trust list PACKAGE --json` and an actual tagged release before reporting automatic publication as complete. See the [npm trust command](https://docs.npmjs.com/cli/v12/commands/npm-trust/) and [trusted publishing guide](https://docs.npmjs.com/trusted-publishers/).

## Prepared publisher-validation patches

The initial preparation targeted API `0.1.2` and CLI `0.1.1`; these versions are not declared published until registry receipts are recorded. The API patch adds the companion server-generation guide without changing JavaScript or type declarations. The CLI patch fixes generated provenance to read the installed package version rather than a duplicated `0.1.0` literal, with a regression that fails before the fix.

The first CLI `0.1.0` bootstrap can use the reviewed artifact from full-CI commit `eff0d9d6905de5d8729eef07771a5838ee36b1b3`. The package must exist before its npm trusted publisher is configured. Then the new version tags publish the prepared patches through OIDC after exact main source CI passes. Configure each publisher and complete its first successful OIDC publish promptly; npm currently requires validation within two days. Read the [official expiry and provenance guidance](https://docs.npmjs.com/trusted-publishers/#trusted-publisher-configuration-expiry). No existing publisher is revoked automatically.

## First OIDC attempts and path correction

The API `0.1.2` tag attempt reached the publication command but npm 12.2.1 interpreted `release/PACKAGE.tgz` as a GitHub shorthand and refused it with EALLOWGIT. This was a workflow path error, before registry authentication. A local no-upload reproduction failed with that relative argument and succeeded with an absolute archive path. The workflow now uses the same absolute tarball expression for its dry-run and actual publish steps. See the [official package-spec guidance](https://github.com/npm/cli/blob/latest/docs/lib/content/commands/npm-publish.md).

The failed0.1.2 tag remains immutable. The corrected API candidate is0.1.3; CLI remains0.1.1. The new main commit must pass full CI before the next API tag. No package version is assumed published from a failed workflow.

Python `0.2.0` reached PyPI OIDC token exchange, which rejected the valid GitHub token with `invalid-publisher` (no matching publisher). Register the documented pending publisher, then rerun the failed publishing job from its existing source/tag rather than replacing that tag.

The corrected API `0.1.3` [run](https://github.com/jongko54/feature-standards/actions/runs/41585652357) passed artifact dry-run and source CI but failed ENEEDAUTH after OIDC. npm's default log does not expose whether this was publisher matching, GitHub token issuance, or token exchange, so that attempt did not establish an active connection. Public latest was `0.1.1` at that attempt. The later authenticated setup and successful releases below supersede that state; no token is added to CI. [Attempt receipt](registry-attempts-2026-11-03.json).

## jongko54 discovery metadata

The next API candidate is `0.1.4`, and CLI remains `0.1.1`. Both set author `jongko54` with the GitHub profile URL, include `jongko54` and `feature-standards` keywords and the author handle in the description, and bundle README authorship links. Actual tarball manifests and SDK/CLI package consumer checks passed. The [discovery guide](npm-discovery.md) records queries and the separate publication/index-verification boundary.

## Main product package and publisher setup

The main product is `feature-standards@0.1.0`: curated cross-language contracts and a read-only JSON context selector. Authentication is its first currently available feature; the React adapter and generator retain their accurate component package names. Normal and three-file namespace bootstrap artifacts are built separately; see the [bootstrap and discovery policy](npm-discovery.md#verify-publication-and-search-separately).

After fresh account authentication on 2026-11-03, `npm trust list @ugauga/feature-standards-react-auth` returned no configurations. An authenticated `npm trust github` then created the publisher for `jongko54/feature-standards`, `publish-npm.yml`, environment `npm`, with publication permission. This confirms configuration creation, not a successful OIDC release. The exact-main-CI gate and a registry integrity receipt still apply to the next component release. No unrelated publisher was revoked.

## Verified component releases and delayed availability

The API `0.1.4` [OIDC release](https://github.com/jongko54/feature-standards/actions/runs/41643117218) succeeded from full-CI source `a85cc70a66035aa10059fddaa7b4b45a91e84d7c`. Public metadata, the downloaded tarball's SHA-512, a fresh registry install, and both root and `/api` imports were verified. The `keywords:jongko54` search returned this version on 2026-11-03.

CLI `0.1.0` was accepted using authenticated first-publication access. Its publisher was then configured, and the `0.1.1` [OIDC release](https://github.com/jongko54/feature-standards/actions/runs/41643117826) successfully uploaded the package from the same full-CI source. Its old two-minute public-availability check timed out. A later independent check verified `0.1.1` registry metadata, reviewed SHA-512, the public tarball, a fresh registry install, the installed binary, and generation of Python application glue. That check did not run the generated authentication server. The failed workflow is retained; the same immutable version is not republished.

npm now scans accepted packages before public installation. Its [official announcement](https://github.blog/changelog/2026-07-28-npm-publish-time-malware-scanning-and-dual-use-metadata/) describes typical delays around five minutes and sometimes fifteen minutes or longer. An accepted upload and a temporary public 404 therefore need separate handling; the delay alone does not establish that a particular package was blocked. The verifier now shares a bounded twenty-minute deadline across metadata and public tarball retrieval, limits individual requests to twenty seconds, and retries transient responses and genuine timeouts. Authentication failures and name/version/integrity mismatches still fail immediately. The publish job allows twenty-five minutes. Fake-clock regression tests cover availability after the previous two-minute cap, deadline exhaustion, and integrity/authentication failures without real sleeps or registry access.

## Verified main product release

`feature-standards@0.1.0` was published through [GitHub OIDC](https://github.com/jongko54/feature-standards/actions/runs/41646067225) from source `b4130b0dc6fd6e1408b35eed4d1ebf9189fb892a`, after [full source CI](https://github.com/jongko54/feature-standards/actions/runs/41644089439) passed. Both workflows succeeded. Public `latest` points to `0.1.0`; the separate setup version retains only its bootstrap role.

The actual 44-file artifact has 38 curated source documents with matching SHA-256 hashes and a clean source/snapshot provenance record. Registry SHA-512 and downloaded bytes matched the reviewed artifact. A fresh empty-cache registry installation passed the installed CLI, all 15 stack/profile contexts, and Node exports. `npm search jongko54` returned this main version and both current component versions. The [machine-readable receipt](npm-product-release-2026-11-03.json) records the exact evidence and limits. No backend runtime implementations are bundled in this main npm package, and these checks do not establish AI speed improvements.

## Verified 0.2.0 workflow release

Main `feature-standards@0.2.0` and generator `@ugauga/create-feature-auth@0.2.0` were published through GitHub OIDC from `2b64e5201d6ebe5029dcc67704a7f46d7b735b59`. The [full source CI](https://github.com/jongko54/feature-standards/actions/runs/41667686875), [main npm release](https://github.com/jongko54/feature-standards/actions/runs/41670228278), and [generator npm release](https://github.com/jongko54/feature-standards/actions/runs/41670228208) all succeeded. Public `latest` points to `0.2.0` for both packages; the browser adapter stays at `0.1.4`.

Anonymous fresh registry installation verified all 15 context choices and Node exports. The installed main CLI completed a real Python-v1 `init --check`; the installed generator completed a real Go-v2 check with an isolated database and confirmed cleanup. Both public tarball SHA-512 values matched their exact CI artifacts. The `jongko54` search returned these versions. The [release receipt](npm-workflow-release-2026-11-04.json) records this evidence, the 12-profile matrix, and public GitHub server-archive downloads. Formal Python/Java/Rust language-registry publication remains separate from those GitHub release assets.
