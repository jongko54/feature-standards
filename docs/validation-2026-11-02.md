# PostgreSQL v2·패키지 재사용 검증 기록

2026-11-02 macOS arm64에서 실행했다. PostgreSQL 18.6, Python 3.13.13, uv 0.11.11, Go 1.26.4, Temurin Java 21.0.13, Rust 1.93.1, Node.js 25.6.1과 Chromium을 사용했다. 아래 표는 로컬 실행 결과다. 해당 커밋의 [GitHub Actions](https://github.com/jongko54/feature-standards/actions)는 별도로 확인한다.

## 공통 검증

| 프로필·범위 | 실제 결과 |
|---|---|
| 메모리 v1, 네 서버 동일 API | 19 × 4 = 76 통과 |
| 메모리 v1, 같은 React 화면 | 8 × 4 = 32 통과 |
| 메모리 v1, Secure 쿠키 | 4 통과 |
| PostgreSQL v2, 네 서버 동일 API | 19 × 4 = 76 통과 |
| PostgreSQL v2, 같은 React 화면 | 8 × 4 = 32 통과 |
| PostgreSQL v2, Secure 쿠키 | 4 통과 |
| 같은 DB의 혼합 언어 시나리오 | 8 통과 |
| 같은 언어 두 인스턴스의 세션 조회·폐기 | Python·Go·Java·Rust 모두 통과 |
| 프로세스 재시작 후 사용자·CSRF 유지 | Python·Go·Java·Rust 모두 통과 |
| 별도 Python+React 소비 앱 | 실제 Chromium 3 통과 |

혼합 언어 검사는 교차 세션 조회·폐기·회전, 두 사용자 분리, 실제 Unicode 계정 로그인, SHA-256 세션 저장 형식, 공유 실패 제한, 동시 실패의 정확한 횟수, 비활성 사용자·CSRF·만료, DB 연결 절단·복구, 비정상 PHC의 일반 503을 확인했다. DB 장애 때 `/healthz`와 세 인증 엔드포인트가 503·no-store·nosniff를 반환하며 쿠키를 발급하지 않는 것도 확인했다.

브라우저의 정상 로그인·조회·새로고침·로그아웃은 실제 서버를 호출한다. Unicode 입력 제출과 CSRF 거절·401·네트워크·429 UI 분기 일부는 요청 경계에서 응답을 주입한다. 실제 Unicode DB 계정은 혼합 언어 HTTP 검사에서 별도로 확인했다.

## 자체 검사와 소비 경계

- Python: 실제 PostgreSQL을 포함해 73개 통과, Ruff 통과, wheel 빌드 성공.
- Go: 실제 PostgreSQL을 포함한 `go test -race ./...`와 `go vet ./...` 통과.
- Java: 실제 PostgreSQL을 포함해 73개 통과, 실행 jar 패키징 성공.
- Rust: 일반 테스트 18개와 별도 실제 PostgreSQL 테스트 1개 통과, fmt·clippy 통과.
- React: API 단위 테스트 7개, TypeScript·Vite 빌드 통과. 소비 앱도 별도 TypeScript·Vite 빌드 통과.
- 공통 실행기·DB 대상 보호 검사 17개 통과. 두 OpenAPI 3.1 검증, 시나리오 소스 매핑과 v2 생성 drift 검사 통과.
- GitHub Actions 정의와 템플릿의 actionlint 및 byte 동일 검사 통과. DB 준비 도구를 전용 DB에서 두 번 실행해 기존 비밀번호 해시가 유지되는 것을 확인했다.
- 저장소 AI 적용 스킬의 형식 검사 통과. 이는 에이전트의 모든 판단을 검증했다는 의미는 아니다.

소비 앱은 인증 코드를 복사하지 않는다. uv가 빌드·설치한 `feature_auth`를 소비 프로젝트의 `.venv/.../site-packages`에서 import하는 것을 확인했다. React는 npm file dependency의 공개 `./api` export를 가져온다. `/api/profile`의 비인증 거절, 로그인·복원, 두 번째 사용자, 로그아웃 후 원본 쿠키 재사용 거절이 통과했다. PyPI·npm 게시나 실제 서비스 배포는 하지 않았다.

## 재현 명령

네 도구 체인과 React/소비 앱 의존성·Chromium을 준비한다. Java에는 `JAVA_HOME`을 설정했다. PostgreSQL 서버 바이너리 경로는 `FEATURE_STANDARDS_PG_BIN`으로 지정했다.

```sh
uv run --frozen --project tools python tools/check_contract.py
uv run --frozen --project tools python tools/generate_openapi_v2.py --check
uv run --frozen --project tools python -m unittest discover -s tests -p 'test_*.py' -v
python3 tests/conformance.py --backend all --browser
uv run --frozen --project tools python tests/postgres_conformance.py --browser
uv run --frozen --project tools python tests/consumer_conformance.py
```

구현별 PostgreSQL 자체 검사는 서로 분리한 `AUTH_TEST_DATABASE_URL`을 사용했다. CI의 동일 DB 준비와 명령은 [워크플로](../.github/workflows/ci.yml)를 따른다. v2 최종 공통 검사와 소비 앱은 각각 자동 생성한 임시 PostgreSQL 클러스터에서도 실행했고, 하네스가 소유 서버를 종료했다. 공통 PG 도구는 운영 DB에 접근하지 않았다.

## 독립 검수와 수정

독립 리뷰에서 테스트 URI의 query·환경 설정이 DB 대상 검사를 우회할 수 있는 문제를 찾았다. 실제 연결 없이 실패 회귀를 만든 뒤, fixture를 명시적인 숫자 loopback·포트·ASCII 테스트 DB명으로 정규화하고 query·환경 경로를 제한했다. 자동 DB 생성도 첫 subprocess·admin 연결 전에 검사한다.

Java의 비활성 사용자 로그아웃은 만료 전 세션에 CSRF를 요구하도록 다른 구현과 맞췄다. Rust는 DB가 응답을 보내지 않을 때 취소된 요청의 드라이버 태스크·소켓이 남는 문제를 실제 TCP mock에서 재현하고, 요청 범위 연결 소유자가 태스크를 종료하도록 수정했다. 타임아웃·요청 취소·SET 오류의 EOF 회귀 3개가 원본에서 실패하고 수정 후 통과했다. 후속 읽기 전용 검수에서 미해결된 P1/P2는 발견하지 못했다.

이는 운영 보안 감사나 모든 장애의 증명이 아니다. Rust의 원격 DB·TLS, 신뢰 프록시, 계정 생성·이메일 검증·비밀번호 재설정·권한 관리는 제공하지 않는다. 기존 전역 Cargo 캐시의 일부 쓰기·자동 정리 권한 경고는 있었으나 관련 검증 명령은 exit 0이었다. 전역 권한은 변경하지 않았다.
