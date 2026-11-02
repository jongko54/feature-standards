---
name: integrate-auth
description: 이 저장소의 메모리 v1, PostgreSQL v2 또는 계정 생명주기 v3 계약을 Python·Go·Java·Rust 서버와 React 프로젝트에 적용하고 공통 테스트로 검증한다. 기존 인증 흐름을 조사하거나 새로 통합할 때 사용한다.
---

# 브라우저 세션 인증 적용

이 스킬은 feature-standards 저장소와 함께 사용한다. 먼저 저장소 루트를 찾고 `features/auth/specification.md`, 대상 구현 README, `features/auth/openapi.json`을 읽는다. 스킬만 별도로 설치되어 참조 파일이 없으면 사용자가 지정한 저장소나 버전의 원본을 확인한다. 경로와 실행 도구를 임의로 가정하지 않는다.

메모리 `browser-session-v1`이 기본이다. 공유 DB·다중 사용자·재시작 후 세션 유지가 필요하면 `features/auth/postgres-session-v2.md`, `features/auth/openapi-v2.json`, `docs/postgres-v2.md`를 읽고 승인 범위에서 PostgreSQL v2를 선택한다. 저장소 변경을 단순 화면 수정에 자동 추가하지 않는다.

가입·이메일 확인·비밀번호 재설정이 범위에 포함되면 `features/auth/account-session-v3.md`, `features/auth/openapi-v3.json`, `docs/account-v3.md`의 v3를 사용한다. `AUTH_STORE=postgres AUTH_ACCOUNT_LIFECYCLE=true`와 명시적 schema 2 이관이 필요하다. 기존 로그인 화면만 바꾸는 요청에 v3 이관을 추가하지 않는다. React 계정 화면은 개발·빌드 시 `VITE_AUTH_ACCOUNT_LIFECYCLE=true`로 선택한다.

대상 프로젝트의 지침·런타임·기존 인증·세션 저장소·프록시·배포 origin·dirty 상태를 읽는다. 기존 인증 검토 요청은 읽기 전용으로 비교 결과를 제시한다. 구현 요청이면 기존 구조와 사용자 데이터를 보존하고 승인된 범위에서 통합·검증한다. 기존 계정 체계를 데모 계정으로 바꾸지 않는다.

핵심 계약은 서버 측 세션 무효화, 절대 TTL, 정확한 Origin 검증, 세션별 CSRF, 쿠키 속성, 일반화된 자격 증명 오류와 peer IP 실패 제한이다. 클라이언트는 같은 origin의 `/auth`를 호출하며 토큰을 localStorage에 저장하지 않는다. Python은 `uvicorn --no-proxy-headers`를 사용한다. API 경로나 기존 인터페이스를 유지해야 하면 명시적 어댑터로 매핑하고 테스트한다.

v1은 단일 사용자·메모리 저장소이고 v2/v3는 공통 PostgreSQL의 사용자·세션·실패 기록을 공유한다. 앱은 자동 DDL·seed·메모리 fallback을 하지 않는다. 명시적 도구와 기존 사용자 저장소의 관계를 확인하며, 데모 seed를 실제 계정 프로비저닝으로 사용하지 않는다. Rust 원격 DB는 `sslmode=verify-full`로 TLS 1.2 이상·인증서 체인·hostname을 검증한다. `sslrootcert`가 없으면 플랫폼 루트, 있으면 지정 PEM CA를 사용하며 평문 재시도는 없다. 명시적 loopback `sslmode=disable`은 유지한다. 신뢰 프록시·운영 정책은 별도 범위다. 새 시크릿·DB 마이그레이션·기존 세션 일괄 폐기·운영 배포가 필요하면 그 영향을 구체화하고 기존 승인 범위를 확인한다. 이 스킬은 배포·커밋·푸시 권한을 추가하지 않는다.

v3 계정 작업은 같은 트랜잭션에서 `account_reserve`를 해싱보다 먼저 실행하고, 허용된 요청만 PHC와 token을 만들어 `account_apply`에 전달한다. 이관된 `enabled`는 관리자 허용과 이메일 확인의 DB 불변식이며 확인·재설정이 관리자 차단을 해제하면 안 된다. `mail_outbox`는 원문 capability를 가지므로 인증용 token 해시 테이블과 구분한다. `tools/mail_capture.py`는 검사된 로컬 테스트 DB에서 새 mode 0600 파일로만 수신하고 외부 메일을 발송하지 않는다. 수신 파일을 로그·이슈·CI artifact로 노출하지 않는다.

Python은 `feature-standards-python-auth`를 설치하고 `feature_auth.create_app`, `current_user`를 사용한다. React API 모듈은 `@feature-standards/react-auth/api`에서 가져온다. 실제 의존성 설정과 보호 API 예제는 `examples/consumer-python-react/`를 참고하며 설치 경로·원본 커밋을 기록한다. PyPI·npm에 게시된 패키지라고 가정하지 않는다.

검증은 `tests/conformance.py`의 같은 시나리오를 사용한다. 이 저장소 참조 구현의 검증은 `python3 tests/conformance.py --backend all --browser`이다. 대상 앱은 격리된 테스트 환경에서 데모 fixture와 테스트 TTL/rate 설정을 주입하고 `--base-url`로 API 테스트를 실행한다. 대상 앱의 실제 화면은 그 프로젝트의 브라우저 테스트로 따로 검증한다. 참조 클라이언트의 테스트가 대상 앱의 화면 검증을 대신하지 않는다. 운영 서버에 테스트 계정을 만들거나 부하·실패 시도를 보내지 않는다. 실제 사용자 저장소에서는 대상 프로젝트 테스트도 함께 실행한다.

v2에는 `uv run --frozen --project tools python tests/postgres_conformance.py --browser`와 `tests/consumer_conformance.py`의 소비 앱 검증을 추가한다. 두 harness는 `feature_auth` 스키마를 재생성하므로 작업 전용 임시 DB만 사용한다. 외부 fixture URI는 loopback·명시적 포트·ASCII `feature_standards_test*` DB명·단일 sslmode=disable만 허용하고 값이 있는 `PG*` 환경은 거절한다. 대상 앱·운영 DB에 이 초기화 harness를 실행하지 않는다. 정적 계약·시나리오 매핑 검사는 `tools/check_contract.py`이며 실제 API·브라우저 실행 결과와 구분한다.

v3는 `uv run --frozen --project tools python tests/account_conformance.py --browser`로 실제 API·언어 간 계정 상태·로그인/reset 경합과 로컬 수신 링크를 이용한 화면 흐름을 검증한다. 같은 테스트 DB 제한과 초기화 경계가 적용된다. `clients/react/playwright.accounts.config.ts`는 기존 v1/v2 브라우저 검사와 분리된 계정 흐름 설정이다. 원격 Rust TLS 변경은 `implementations/rust-axum/tests/postgres_tls.py`의 전용 SSL PostgreSQL fixture로 체인·hostname·평문 다운그레이드 거절을 확인한다.

결과에 계약 버전, 통합한 출처 커밋, 변경 지점, 실제 검증 명령과 결과, 미검증 범위를 남긴다. 테스트 통과를 보안 감사나 운영 준비 완료로 확대하지 않는다. 복사본은 자동 업데이트되지 않으므로 다음 변경은 원본 커밋 diff와 회귀 검증으로 반영한다.
