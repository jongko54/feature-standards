# Java·Rust 확장 검증 결과

2026-11-01 macOS arm64 로컬 환경에서 실행했다. 아래 결과는 이 변경의 소스와 계약을 대상으로 하며 GitHub Actions 실행 결과가 아니다. Java 21.0.13, Rust/Cargo 1.93.1, Node.js 25.6.1 및 Chromium을 사용했다.

| 서버 | 자체 테스트 | 동일 API 시나리오 | Secure 쿠키 검사 | 같은 React 브라우저 시나리오 |
|---|---:|---:|---|---:|
| Python / FastAPI | 38 통과 | 19 통과 | 통과 | 8 통과 |
| Go / net/http | 13 통과, race 검사 포함 | 19 통과 | 통과 | 8 통과 |
| Java / Spring | 58 통과 | 19 통과 | 통과 | 8 통과 |
| Rust / Axum | 10 통과 | 19 통과 | 통과 | 8 통과 |

공통 API 76개, 브라우저 32개와 별도의 Secure 쿠키 4개 검사가 통과했다. 브라우저 시나리오 중 실제 로그인·조회·새로고침·로그아웃·잘못된 자격 증명은 실제 서버를 사용한다. 일부 실패 UI 분기와 Unicode 입력 전달 사례는 요청 경계에서 응답을 주입한다. 실제 서버의 만료와 제한 동작은 API 시나리오와 구현별 테스트가 확인한다.

## 실행한 검증

```sh
python3 tests/conformance.py --backend all --browser
python3 -m unittest discover -s tests -p test_runner.py -v
uv run --frozen --project tools python tools/check_contract.py
uv run --frozen --project implementations/python-fastapi pytest implementations/python-fastapi/tests
uv run --frozen --project implementations/python-fastapi ruff check implementations/python-fastapi tests tools
go -C implementations/go-net-http test -race -count=1 ./...
implementations/java-spring/mvnw -q -f implementations/java-spring/pom.xml test
cargo test --locked --manifest-path implementations/rust-axum/Cargo.toml
```

React 단위 테스트 7개와 TypeScript/Vite 빌드, Rust fmt·clippy도 통과했다. 실행기 회귀 테스트는 11개이며 OpenAPI 3.1과 19개 API 시나리오 매핑도 유효했다. Java 패키징과 Rust 빌드는 공통 실행기가 수행했고 각 서버의 API·쿠키·브라우저 검사에서 산출물을 재사용했다.

전체 통합 명령에는 JDK의 `JAVA_HOME`·PATH를 설정했다. Cargo 산출물 선택 회귀를 확인하려고 기본과 다른 `CARGO_TARGET_DIR`과 `CARGO_BUILD_TARGET=aarch64-apple-darwin`도 지정했다. 실행기는 고정된 과거 바이너리 경로 대신 이번 Cargo 빌드가 보고한 실제 실행 파일을 사용했다.

## 리뷰와 한계

독립 읽기 전용 리뷰에서 Cargo 출력 경로와 실행 경로가 어긋날 수 있는 문제가 발견됐다. 해당 실패를 회귀 테스트로 확인한 뒤 실제 artifact 선택으로 수정했고 재검토에서 남은 P1/P2 이슈는 발견되지 않았다. 이는 보안 감사나 모든 입력·배포 환경의 검증을 뜻하지 않는다.

기존 Cargo 캐시의 일부 쓰기·자동 정리 권한 경고가 있었지만 관련 명령은 exit 0으로 끝났다. 전역 캐시 권한이나 시스템 설정은 변경하지 않았다. 테스트가 실행한 서버와 Vite 프로세스는 종료했다.

이 로컬 검증 시점에는 GitHub Actions가 비활성이었다. `ci/github-actions.yml`은 네 언어에 맞춰 확장하고 정적 검사한 템플릿이며, 이 기록은 Linux CI에서 실제 실행했다고 주장하지 않는다. 이후 원격 실행 결과는 해당 커밋의 Actions에서 별도로 확인한다. 단일 사용자·메모리 세션·분산 저장소 미제공이라는 참조 구현의 범위도 유지한다.
