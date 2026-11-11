# 세 기능 SDK starter 검증 — 2026-11-11

**Python·Go·Java·Rust에서 원본 CLI로 생성한 앱 4개와 실제 tarball에서 새로 설치한 CLI로 생성한 앱 4개, 총 8개가 실제 빌드·TCP HTTP·SDK 출처 검사를 통과했다.** 생성과 검사 전후 인증·코어 SDK 원본 파일 fingerprint도 유지됐다. [정제된 검증 기록](core-starter-validation-2026-11-11.json)에 결과를 남긴다.

## 실제 확인한 범위

| backend | source CLI 생성·검사 | fresh installed CLI 생성·검사 | SDK 출처 근거 |
| --- | --- | --- | --- |
| Python / FastAPI | PASS | PASS | 두 editable SDK의 실제 import 파일 경로 |
| Go / net/http | PASS | PASS | 빌드한 앱의 원본 module replace 경로 |
| Java / Spring Boot | PASS | PASS | 앱 내부 overlay의 sourceDirectory와 실제 실행 JAR의 SDK CodeSource |
| Rust / Axum | PASS | PASS | 생성 앱의 잠긴 Cargo dependency graph와 두 path manifest 경로 |

각 앱은 아래 12개 검사 범주를 수행했다. 범주는 개별 HTTP 요청 수와 다르다.

1. 선택된 memory/v1 health profile.
2. 인증·코어 SDK의 실제 의존성 출처.
3. 일반 start의 샘플 문서 접근 거부.
4. anonymous/forged session의 보호 경로 거부.
5. 로그인 후 profile과 제품 API에서 같은 세션 identity 사용.
6. 독립 세션.
7. Origin·세션 CSRF 거부.
8. owner·tenant 격리.
9. 가시성을 적용한 뒤 목록 total 계산.
10. typed filter, stable sort와 pagination.
11. 중복·비정규·잘못된 원본 query 거부.
12. 로그아웃 후 복사 cookie의 인증·제품 경로 재사용 거부.

원본 의존성의 소스/모듈/JAR 연결과 HTTP 동작을 함께 검증했다. 이 검사는 악성 생성 프로젝트를 판별하는 sandbox나 모든 SDK 호출을 계측한 인과 증명이 아니다. `check`는 사용자가 명시한 신뢰 코드와 컴파일러를 실행한다.

## 출처와 재현

- 구현 기준: [472a1fc](https://github.com/jongko54/feature-standards/tree/472a1fce5f46a07d5d0398038c11b2d40b396556).
- source candidate `feature-standards@0.4.0`; 새 registry 게시 없음.
- 실제 fresh-install tarball SHA-256: `59a5df1e73b05d321aa3298307a612790028167808598ca1283fbc1152b60d60`.
- 해당 archive provenance의 source commit은 위 구현 기준과 일치했고 sourceDirty/snapshotDirty는 모두 false였다.
- 로컬 macOS arm64에서 Node 25.6.1, npm 11.9.0, uv 0.11.11, Python 3.13, Go 1.26.4, JDK 21.0.13, Rust 1.93.1을 사용했다. JDK와 Python 선택은 프로세스별로 지정했다.

```sh
npm --prefix packages/feature-standards test
npm --prefix packages/feature-standards run check:pack
npm --prefix packages/feature-standards run check:bootstrap
npm --prefix packages/feature-standards run check:core-generated
npm --prefix packages/feature-standards run check:core-installed
```

`check:core-generated`는 source main CLI의 실제 init → check를 네 backend에서 실행한다. `check:core-installed`는 실제 npm tarball을 만들고, 새 디렉터리에 offline/ignore-scripts로 설치한 binary로 같은 네 실행을 반복한다. Node 패키지 설치와 별개로 native build는 공개 언어 의존성을 내려받을 수 있다. 테스트는 자신의 임시 앱만 정리한다.

## 보조 검증과 수정

- main Node 행동 검사 **52개 통과·실패 0개**. 기존 auth 선택·v1/v2/v3 receipt 경계, read-only context, 새 template/capability, metadata·경로·symlink·SDK 출처·환경 격리와 프로세스 출력 처리를 포함한다.
- 저장소 Python unit **357개 중 324개 통과·33개 환경 의존 제외·실패 0개**.
- tarball의 정확한 파일 inventory, 새 설치, 26 context, Node exports와 독립 bootstrap artifact 검사 통과.
- 신규 Python glue의 Ruff, Go/Rust format, Java XML·rendered TOML 구문, 문서 링크와 CI/template 일치 검사 통과.
- 작성자와 분리한 소스 리뷰 후 Python path dependency를 editable로 맞추고 JVM 옵션 환경 격리, stdout close 대기를 보완했다. 후손 프로세스의 늦은 출력이 누락되는 실제 실패와 JVM 옵션 미제거를 먼저 재현한 뒤 회귀 검사가 통과했다.
- Rust metadata의 offline cache 실패를 재현하고 `--locked`는 유지하면서 불필요한 offline 강제만 제거했다. 위 8개 최종 결과는 수정 후 고정 구현의 새 생성 앱으로 확인했다.

## 해석과 한계

기존 auth-only generator와 새 core template을 구분한다. 새 template은 memory/v1 + RBAC + bounded materialized listing만 지원한다. 일반 시작에서는 membership이 기본 거부이고 샘플 데이터가 노출되지 않는다. 실제 서비스의 현재 멤버십·문서 provider와 명시 정책은 애플리케이션 소유자가 연결한다. DB 세션, 계정 가입, 메일, 브라우저 UI, 정책 관리, 운영 배포는 이 새 starter 검사 범위가 아니다.

8개는 CLI로 SDK starter 생성을 명시한 기능 검증이다. AI가 자발적으로 SDK를 선택한 관측이나 외부 채택률이 아니다. AI 모델 세션은 추가하지 않았고 기존 [32회 SDK 안내 연구](adoption/2026-11-11-sdk-guidance.md)의 원본·실패·사용량은 바꾸지 않았다. 이번 변경으로 토큰이나 채택률이 개선됐는지는 별도 재실험이 필요하다.

서버 출처·동작·패키지 설치와 보안 감사·실제 고객 운영은 서로 다른 근거다. 이번 검증은 보안 인증이나 운영 안정성 보증이 아니다. 새 명령과 실행 조건은 [starter 안내](core-starter.md)를 따른다.
