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

`.github/workflows/publish-npm.yml` tests and packs both npm packages. A manual dispatch only builds. Version tags `npm-react-auth-vX.Y.Z` and `npm-create-feature-auth-vX.Y.Z` select one artifact, and its metadata must match the exact tag. The publish job requires full main-branch CI to have succeeded for the same source commit. Node 24 and npm 12.2.1 support this trusted publishing flow.

Configure each existing package's npm trusted publisher with repository `jongko54/feature-standards`, workflow `publish-npm.yml`, environment `npm`, and publish permission. The CLI's first release requires ordinary npm authentication before its publisher can be connected. This account action requires npm 2FA; creating the workflow alone does not activate it.

```sh
npm exec --yes --package=node@24 --package=npm@12.2.1 -- npm trust github \
  @ugauga/feature-standards-react-auth --repo jongko54/feature-standards \
  --file publish-npm.yml --env npm --allow-publish --yes --browser=false
# After its first release, repeat for @ugauga/create-feature-auth.
```

No long-lived NPM_TOKEN is added. The job publishes the exact built tarball and verifies registry version, SHA-512 integrity, and a public tarball download. Confirm activation with `npm trust list PACKAGE --json` and an actual tagged release before reporting automatic publication as complete. See the [npm trust command](https://docs.npmjs.com/cli/v12/commands/npm-trust/) and [trusted publishing guide](https://docs.npmjs.com/trusted-publishers/).

## Prepared publisher-validation patches

The checkout prepares API `0.1.2` and CLI `0.1.1`; these versions are not declared published until registry receipts are recorded. The API patch adds the companion server-generation guide without changing JavaScript or type declarations. The CLI patch fixes generated provenance to read the installed package version rather than a duplicated `0.1.0` literal, with a regression that fails before the fix.

The first CLI `0.1.0` bootstrap can use the reviewed artifact from full-CI commit `eff0d9d6905de5d8729eef07771a5838ee36b1b3`. The package must exist before its npm trusted publisher is configured. Then the new version tags publish the prepared patches through OIDC after exact main source CI passes. Configure each publisher and complete its first successful OIDC publish promptly; npm currently requires validation within two days. Read the [official expiry and provenance guidance](https://docs.npmjs.com/trusted-publishers/#trusted-publisher-configuration-expiry). No existing publisher is revoked automatically.
