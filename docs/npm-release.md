# React 인증 API npm 배포

패키지는 `@ugauga/feature-standards-react-auth`이며 ESM 루트와 `/api` export를 제공한다. npm 계정 `ugauga`의 scope를 사용한다. 기존 `@feature-standards` 조직이 없어 내부 checkout 이름을 실제 게시 가능한 이름으로 옮겼다. 인증 HTTP 계약과 API 함수 동작은 유지한다.

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

## 상태

현재 문서는 배포 후보의 준비·검증 절차를 기록한다. npm 게시 성공은 registry 확인 후 갱신한다.
