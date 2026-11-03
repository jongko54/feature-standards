---
name: integrate-auth
description: feature-standards 인증을 Python·Go·Java·Rust·React 프로젝트에 통합하거나 기존 인증을 계약과 비교할 때 사용한다. 단순 화면 스타일 수정에는 사용하지 않는다.
---

# 인증 표준 적용

기존 프로젝트의 지침·런타임·인증·dirty 상태와 요청 범위를 확인한다. 검토는 읽기 전용, 구현은 승인된 범위에서 진행한다. 기존 계정·데이터를 데모로 교체하지 않는다.

스택·프로필이 정해졌으면 아래에서 해당 공개 API와 소비 예제로 바로 이동해 필요한 구간만 읽는다. 기본 v1 로그인·로그아웃 통합에 manifest나 모든 명세·구현을 먼저 읽을 필요는 없다. 참조 저장소가 없으면 지정한 버전의 원본을 확인하고 경로·도구를 가정하지 않는다.

| 스택 | 공개 API 안내 | 소비 예제 |
|---|---|---|
| Python | [FastAPI](../../implementations/python-fastapi/README.md#다른-python-프로젝트에서-사용) | [Python 앱](../../examples/consumer-python-react/app.py) |
| Go | [net/http](../../implementations/go-net-http/README.md#다른-go-프로젝트에서-사용하기) | [Go 앱](../../examples/consumer-go/README.md) |
| Java | [Spring](../../implementations/java-spring/README.md#라이브러리로-가져오기) | [Java 앱](../../examples/consumer-java/README.md) |
| Rust | [Axum](../../implementations/rust-axum/README.md#서비스-주입) | [Rust 앱](../../examples/consumer-rust/README.md) |
| React | [클라이언트 API](../../clients/react/README.md#login-restore-and-log-out) | [React 앱](../../examples/consumer-python-react/src/main.tsx) |

선택이나 공개 API가 불명확할 때만 루트의 `feature-standards.json` 또는 `uv run --frozen --project tools python tools/auth_catalog.py --stack python --profile browser-session-v1`을 조회한다. 반환한 선택의 경로·의존성·공개 `entrypoints`를 확인한다. 새 소비 앱의 골격이 필요하면 [명시적 소스 경로를 쓰는 생성기](../../docs/create-feature-auth.md)를 사용할 수 있다.

| 필요 | 선택과 추가 참조 |
|---|---|
| 단일 환경 설정 사용자·메모리 세션 | 기본 `browser-session-v1` |
| 공유 DB·다중 사용자·재시작 후 유지 | `browser-session-v2`, [PostgreSQL 참조](references/postgres.md) |
| 가입·이메일 확인·비밀번호 재설정 | `browser-session-v3`, [계정 참조](references/accounts.md) |
| SMTP 발송이 요청됨 | v3 + [메일 참조](references/mail.md) |

요청하지 않은 DB 이관·메일·배포를 추가하지 않는다. 프로필별 조건부 참조는 해당 기능이 필요할 때 읽는다. 응답·경로·오류·쿠키 계약을 바꾸거나 비교할 때는 해당 명세와 OpenAPI를 확인한다.

공통 불변식은 서버 세션 무효화, 절대 TTL, 정확한 Origin, 세션별 CSRF, Secure·HttpOnly 쿠키, 일반화된 오류와 peer IP 제한이다. 클라이언트는 같은 origin `/auth`를 사용하고 bearer token을 localStorage에 저장하지 않는다. 기존 API 경로를 유지해야 하면 어댑터와 회귀 검증을 둔다. Python은 `uvicorn --no-proxy-headers`를 사용한다.

선택한 소비 예제와 스택 검사를 실행한다. 대상 앱의 격리 fixture에 데모·TTL·rate 설정을 주입한 뒤 `python3 tests/conformance.py --base-url http://127.0.0.1:PORT`로 공통 HTTP를 확인하고, 실제 대상 화면은 그 프로젝트의 브라우저 검사로 확인한다. 참조 화면 통과가 대상 화면 검증을 대신하지 않는다. 운영 환경에 실패 시도·테스트 계정·초기화 harness를 보내지 않는다.

출처 URL·커밋, 프로필, 변경 지점, 실제 명령·결과와 미검증 범위를 남긴다. 로컬 패키지와 레지스트리 게시, 정적 맵과 실제 실행, 테스트와 보안 감사는 구분한다. 복사본과 path dependency는 자동 업데이트되지 않는다.
