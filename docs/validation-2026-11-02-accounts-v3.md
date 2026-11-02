# 계정 생명주기 v3·Rust TLS 검증 기록

2026-11-02 macOS arm64에서 실행했다. PostgreSQL 18.6, Python 3.13.13, Go 1.26.4, Temurin Java 21.0.13, Rust 1.93.1, Node.js 25.6.1과 Chromium을 사용했다. 아래 결과는 로컬 실행이며, 원격 Linux 결과는 해당 커밋의 [Actions](https://github.com/jongko54/feature-standards/actions)에서 별도로 확인한다.

## 실제 실행 범위

| 범위 | 결과 |
|---|---|
| 메모리 v1 동일 HTTP / 같은 React | HTTP 76, 브라우저 32, Secure 쿠키 4 통과 |
| PostgreSQL v2 동일 HTTP / 같은 React | HTTP 76, 브라우저 32, Secure 쿠키 4 통과 |
| v2 혼합 언어 / 두 인스턴스 / 재시작 | 혼합 8, 각 언어 두 인스턴스·재시작 모두 통과 |
| v3 기존 HTTP 계약 | 19 × 4 = 76 통과 |
| v3 계정 HTTP | 10 × 4 = 40 통과 |
| v3 혼합 언어·동시성·장애·재시작 | 10 통과 |
| v3 실제 계정 React 흐름 | 3 × 4 = 12 통과 |
| 계정 SQL·마이그레이션·로컬 수신 파일 | 실제 DB 검사 13 통과 |
| Rust TLS 경계 | 실제 TLS 검사 1 통과: 신뢰 CA·암호화 성공 / 다른 CA·hostname·평문 서버 거절 |
| 별도 Python+React 소비 앱 | 브라우저 3 통과 |

가입→미확인 로그인 거절→메일 확인→로그인→비밀번호 재설정을 여러 언어에 걸쳐 수행했다. 동시 확인·동시 재설정은 정확히 하나의 요청만 성공했다. 테스트용 PostgreSQL 잠금으로 구 비밀번호 로그인을 세션 발급 직전에 멈춘 뒤 재설정을 경쟁시켜, 네 언어 모두 재설정이 기다리고 최종적으로 그 로그인 쿠키도 거절되는 것을 확인했다.

중복 가입은 기존 비밀번호를 바꾸지 않는다. 관리자 비활성·미확인 상태를 확인/재설정이 덮어쓰지 않는다. 토큰 종류·만료·단일 사용, 이메일 cooldown, 언어 간 공유 peer 제한, DB 장애 후 토큰 보존·복구, deferred COMMIT 실패의 rollback을 확인했다. 신규 pending 계정은 DB의 generated enabled가 false여서 이전 enabled 조회 방식으로도 로그인할 수 없다.

브라우저 계정 검사는 공개 메일함 endpoint나 메일 API mock을 쓰지 않는다. 실제 DB outbox를 private 로컬 파일로 캡처해 얻은 링크로 확인·재설정을 수행하고, 이전 세션 쿠키의 401을 확인했다. URL fragment를 주소에서 지우고 자동으로 확인하지 않는 동작, 링크 재사용 거절, 모바일 390px 입력 오류·가로 넘침을 확인했다. 모바일 화면도 렌더링해 검토했다. 기존 v1/v2의 일부 오류 UI·Unicode 제출 검사는 종전처럼 응답을 주입하며, 모든 브라우저 분기가 실제 서버 장애라는 주장은 하지 않는다.

## 자체 검사와 검수

- Python: 실제 schema 1·2 검사 포함 99개 통과, Ruff·format 통과.
- Go: 실제 schema 1·2를 포함한 race·vet 통과.
- Java: 실제 schema 1·2를 포함해 88개 통과(skip 0), 실행 jar 패키징 성공.
- Rust: 일반 24개와 별도 v2 DB·v3 DB·TLS 각 1개 통과, fmt·clippy·build 성공.
- React API 단위 검사 8개와 TypeScript/Vite 빌드 통과. 소비 앱에는 현재 소스의 Python wheel을 새 작업 캐시에서 다시 빌드·설치하고 account_lifecycle 지원 import를 확인했다.
- 실행기/fixture 일반 검사 17개 통과. opt-in SQL 13개는 전용 URL을 제공한 별도 실행에서 통과했다.
- OpenAPI 3.1 세 프로필, v2/v3 생성 drift와 실제 소스 매핑, workflow actionlint와 템플릿 byte 동일, 스킬 형식 검사 통과.

독립 검수에서 두 P2를 재현해 수정했다. 첫째, 제한된 요청도 해싱하던 순서를 같은 트랜잭션의 reserve→허용 시 hash/apply로 바꿨다. 네 언어에서 소진된 요청은 해싱 없이 429를 반환하고 중복 횟수 증가도 없음을 확인했다. 둘째, 메일 캡처의 fsync 이후 COMMIT 응답이 유실된 경우 파일을 삭제하지 않도록 했다. 실제 DB 커밋 성공 후 클라이언트 예외를 주입한 검사에서 private 파일이 보존되고 재시도는 0개였다. 후속 독립 읽기 검수에서 미해결 P1/P2를 발견하지 못했다.

## 재현 명령과 한계

도구 체인, 양쪽 React 의존성과 Chromium을 준비한다. 계정 전체 검사는 작업 전용 DB 또는 `FEATURE_STANDARDS_PG_BIN`의 PostgreSQL 서버 바이너리를 사용한다. TLS fixture는 `FEATURE_STANDARDS_TLS_PG_BIN`의 SSL 지원 서버 바이너리와 openssl이 필요하다.

```sh
uv run --frozen --project tools python tools/check_contract.py
uv run --frozen --project tools python tests/account_conformance.py --browser
# AUTH_ACCOUNT_TEST_DATABASE_URL에 다른 작업 전용 SQL DB를 지정한 상태에서:
uv run --frozen --project tools python -m unittest discover -s tests -p test_account_store.py -v
python3 implementations/rust-axum/tests/postgres_tls.py
python3 tests/conformance.py --backend all --browser
uv run --frozen --project tools python tests/postgres_conformance.py --browser
uv run --frozen --project tools python tests/consumer_conformance.py
```

이 기록은 로컬 CA의 TLS 경계 검증이며 실제 인터넷 운영 DB 접속을 뜻하지 않는다. 외부 SMTP 발송, 역할 관리, MFA, 운영 배포, 패키지 레지스트리 게시는 하지 않았다. 인증용 account_tokens는 해시만 보관하지만 outbox·수신 파일에는 민감한 원문 capability가 있으므로 운영 역할 분리·암호화·보존 정책이 필요하다. 새 비밀번호 최소 길이 정책은 포함하되 유출 비밀번호 blocklist는 제공하지 않는다. 기존 Cargo 캐시 권한 경고는 있었으나 검증 명령은 exit 0이었고 전역 권한을 바꾸지 않았다.
