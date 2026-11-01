# Feature Standards

**AI가 반복해서 구현하는 기능을 공통 명세·스택별 구현·동일한 검증 시나리오로 재사용합니다.**

첫 기능은 로그인·로그아웃·내 정보 조회를 제공하는 **`auth / browser-session-v1`** 입니다. Python과 Go 서버는 같은 HTTP 계약을 구현하고, 하나의 React 클라이언트가 양쪽에 연결됩니다.

> 현재 버전 `0.1.0`은 실험적 참조 구현입니다. 단일 환경 설정 사용자와 프로세스 메모리 세션을 사용합니다. 운영 사용자 저장소·분산 세션·보안 감사는 포함하지 않습니다.

## 제공 범위

| 구성 | 상태 | 역할 |
|---|---|---|
| [인증 명세](features/auth/specification.md) / [OpenAPI 3.1](features/auth/openapi.json) | 구현 기준 | 요청·응답·오류·보안·실패 동작 |
| [Python / FastAPI](implementations/python-fastapi) | 첫 참조 구현 | Argon2id, 세션, CSRF, 로그인 제한 |
| [Go / net/http](implementations/go-net-http) | 첫 참조 구현 | 동일 HTTP 계약 |
| [React / TypeScript](clients/react) | 공통 클라이언트 | 로그인, 복원, 상태 확인, 로그아웃, 오류·만료 UI |
| [공통 테스트](tests/conformance.py) | 두 서버에 동일 적용 | [19개 시나리오](features/auth/scenarios.json) + Secure 쿠키 확인 |
| [AI 적용 지침](skills/integrate-auth/SKILL.md) | 저장소와 함께 버전 관리 | 기존 프로젝트 조사·적용·검증 |
| Java / Spring, Rust / Axum | 후속 계획 | 아직 구현·지원하지 않음 |

## 빠르게 실행하기

필요 도구: Python 3.12 이상, [uv](https://docs.astral.sh/uv/), Go 1.26 이상, Node.js 22.12 이상, npm. 브라우저 테스트는 Node.js 24 LTS와 Chromium을 기준으로 합니다.

서버는 아래 두 구현 중 하나를 실행합니다. 데모 계정은 **`demo@example.com` / `correct-horse-battery-staple`** 이며 `AUTH_DEMO=true`에서만 활성화됩니다.

```sh
# 터미널 1: Python 서버 (http://127.0.0.1:8000)
cd implementations/python-fastapi
AUTH_DEMO=true AUTH_COOKIE_SECURE=false uv run --frozen uvicorn app:app --no-proxy-headers --host 127.0.0.1 --port 8000
```

```sh
# 또는 터미널 1: Go 서버 (http://127.0.0.1:8000)
cd implementations/go-net-http
AUTH_DEMO=true AUTH_COOKIE_SECURE=false go run .
```

```sh
# 터미널 2: 공통 React 화면
cd clients/react
npm ci
npm run dev
```

브라우저에서 **http://127.0.0.1:5173** 을 엽니다. Vite가 `/auth`를 서버로 프록시하므로 CORS 설정을 추가하지 않습니다. 다른 포트의 서버는 `AUTH_API_TARGET=http://127.0.0.1:다른포트 npm run dev`로 선택합니다. `localhost`와 `127.0.0.1`을 혼용하면 Origin이 달라집니다.

## 같은 기준으로 검증하기

저장소 루트에서 실행합니다. 계약 테스트는 임시 loopback 포트의 서버만 시작·종료합니다. 브라우저 검증에는 포트 5173이 비어 있어야 합니다.

```sh
uv sync --frozen --project implementations/python-fastapi
uv run --frozen --project implementations/python-fastapi pytest implementations/python-fastapi/tests
go -C implementations/go-net-http test -race ./...
uv run --frozen --project tools python tools/check_contract.py
python3 -m unittest discover -s tests -p test_runner.py -v
python3 tests/conformance.py --backend all
```

```sh
cd clients/react
npm ci
npm test
npm run build
npx playwright install chromium
cd ../..
python3 tests/conformance.py --backend all --browser
```

API 검증에는 로그인 성공·실패, 입력 경계, 로그인 CSRF, 쿠키 속성, 세션 교체, 복제한 쿠키 재사용, 잘못된 CSRF 이후 세션 유지, 독립 브라우저 세션, 로그아웃 멱등성, 절대 만료, peer IP 기반 제한이 포함됩니다. 브라우저 테스트는 양쪽 서버에 동일한 화면을 연결합니다. 실제 로그인·새로고침·로그아웃은 실제 서버를 호출하며, 일부 UI 오류 분기는 요청 경계에서 실패 응답을 주입합니다.

### GitHub Actions 상태

[CI 템플릿](ci/github-actions.yml)에 같은 검증 명령을 준비했습니다. 현재 저장소에는 자동 실행 워크플로가 활성화되어 있지 않습니다. 최초 게시에 사용한 GitHub 인증이 `workflow` 쓰기 권한을 갖지 않아 템플릿으로 보존했습니다. 워크플로 파일 쓰기가 허용된 환경에서 이 파일을 `.github/workflows/ci.yml`에 배치하면 push·PR 시 실행할 수 있습니다. 로컬 테스트 통과와 원격 CI 통과는 별개입니다.

## 표준을 관리하는 방식

1. **명세:** 성공과 실패 동작을 먼저 정의합니다. 이 저장소의 규약이며 공인 국제 표준으로 주장하지 않습니다.
2. **구현:** 각 스택의 구조와 라이브러리를 사용하면서 같은 외부 동작을 제공합니다.
3. **검증:** 구현 언어와 독립적인 테스트를 실행하고 규격 버전·검증 커밋·실행 결과를 기록합니다.
4. **적용:** AI가 대상 프로젝트를 조사한 뒤 필요한 부분을 통합하고 같은 검증을 실행합니다.
5. **유지:** 계약 변경은 명세·테스트·구현·적용 지침을 함께 변경합니다. [호환성 정책](docs/versioning.md)을 따릅니다.

## API와 배포 경계

| 요청 | 성공 | 대표 실패 |
|---|---|---|
| `POST /auth/login` | `200` + 세션 쿠키·사용자·CSRF 토큰 | `400`, `401`, `403`, `413`, `415`, `429` |
| `GET /auth/me` | `200` + 사용자·CSRF 토큰 | `401` |
| `POST /auth/logout` | 본문 없는 `204`, 서버 세션 삭제·쿠키 제거 | `403` |
| `GET /healthz` | `200` + 프로필·구현 이름 | — |

상태 변경에는 정확한 Origin이 필요하고, 유효한 세션의 로그아웃에는 해당 세션의 CSRF 토큰도 필요합니다. 쿠키의 `Secure` 기본값은 활성화이며, 명시적 로컬 데모에서만 해제할 수 있습니다. 설정값은 [명세](features/auth/specification.md)와 구현별 README를 확인합니다.

메모리 저장소는 재시작 시 초기화됩니다. reverse proxy 뒤에서는 peer IP가 프록시로 보입니다. 운영 적용에는 사용자 저장소, 공유 세션·실패 기록, 신뢰 프록시, HTTPS, 비밀 관리, 용량·관측·보안 검토가 추가로 필요합니다. 브라우저 세션 프로필은 모바일 bearer token 또는 교차 사이트 인증의 대체 규격이 아닙니다.

## 다음 기능

다음 단계는 이 계약을 통과하는 Java·Rust 구현입니다. 이후 회원가입·비밀번호 재설정·권한 관리·파일 업로드를 각각 독립된 명세와 테스트로 추가합니다. 구현되지 않은 기능은 지원 목록에 표시하지 않습니다.

참여 방법은 [CONTRIBUTING.md](CONTRIBUTING.md), 보안 범위는 [SECURITY.md](SECURITY.md), 비교한 선행 프로젝트는 [docs/research.md](docs/research.md)를 확인하세요. 라이선스는 [MIT](LICENSE)입니다.
