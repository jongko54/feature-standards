---
name: integrate-auth
description: feature-standards 인증을 Python·Go·Java·Rust·React 프로젝트에 통합하거나 기존 인증을 계약과 비교할 때 사용한다. 단순 화면 스타일 수정에는 사용하지 않는다.
---

# 인증 표준 적용

기존 프로젝트의 지침·런타임·인증·dirty 상태와 요청 범위를 확인한다. 검토는 읽기 전용, 구현은 승인된 범위에서 진행한다. 기존 계정·데이터를 데모로 교체하지 않는다.

저장소 루트의 `feature-standards.json`에서 스택·프로필을 선택한다. `uv run --frozen --project tools python tools/auth_catalog.py --stack python --profile browser-session-v1`처럼 조회할 수 있다. 반환한 `read`, 공개 `entrypoints`, 패키지 의존성, `consumer`를 읽고 공개 API를 사용한다. 참조 저장소가 없으면 지정한 버전의 원본을 확인하고 경로·도구를 가정하지 않는다.

| 필요 | 선택과 추가 참조 |
|---|---|
| 단일 환경 설정 사용자·메모리 세션 | 기본 `browser-session-v1` |
| 공유 DB·다중 사용자·재시작 후 유지 | `browser-session-v2`, [PostgreSQL 참조](references/postgres.md) |
| 가입·이메일 확인·비밀번호 재설정 | `browser-session-v3`, [계정 참조](references/accounts.md) |
| SMTP 발송이 요청됨 | v3 + [메일 참조](references/mail.md) |

요청하지 않은 DB 이관·메일·배포를 추가하지 않는다. 선택한 명세·OpenAPI·스택 README만 우선 읽고 조건부 참조는 필요할 때 읽는다.

공통 불변식은 서버 세션 무효화, 절대 TTL, 정확한 Origin, 세션별 CSRF, Secure·HttpOnly 쿠키, 일반화된 오류와 peer IP 제한이다. 클라이언트는 같은 origin `/auth`를 사용하고 bearer token을 localStorage에 저장하지 않는다. 기존 API 경로를 유지해야 하면 어댑터와 회귀 검증을 둔다. Python은 `uvicorn --no-proxy-headers`를 사용한다.

선택한 소비 예제와 스택 검사를 실행한다. 대상 앱의 격리 fixture에 데모·TTL·rate 설정을 주입한 뒤 `python3 tests/conformance.py --base-url http://127.0.0.1:PORT`로 공통 HTTP를 확인하고, 실제 대상 화면은 그 프로젝트의 브라우저 검사로 확인한다. 참조 화면 통과가 대상 화면 검증을 대신하지 않는다. 운영 환경에 실패 시도·테스트 계정·초기화 harness를 보내지 않는다.

출처 URL·커밋, 프로필, 변경 지점, 실제 명령·결과와 미검증 범위를 남긴다. 로컬 패키지와 레지스트리 게시, 정적 맵과 실제 실행, 테스트와 보안 감사는 구분한다. 복사본과 path dependency는 자동 업데이트되지 않는다.
