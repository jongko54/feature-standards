# Working agreements

- 기본 설명과 문서는 한국어로 작성한다. 코드 식별자와 계약의 오류 코드는 영어를 사용한다.
- 인증 통합·비교에는 `.agents/skills/integrate-auth/SKILL.md`를 사용한다. 스택·프로필이 정해졌으면 해당 소비 예제·공개 API 안내로 바로 이동하고, 선택이나 API가 불명확할 때만 `feature-standards.json` 또는 `tools/auth_catalog.py`를 조회한다. 단순 스타일 수정에는 인증 통합 절차를 추가하지 않는다. manifest 변경은 `tools/auth_catalog.py --check`로 경로·계약 연결을 검증한다.
- 권한·목록 통합에는 `skills/integrate-core/SKILL.md`를 사용한다. 세 기능의 선택은 `features/catalog.json`, 새 manifest 검증은 `tools/feature_catalog.py --check`를 따른다. 코어 패키지의 게시 상태는 `docs/core-release-0.1.0.json`의 registry·다운로드·소비자 검증 기록을 따르며 브라우저 권한 판정은 표시 보조로만 사용한다.
- `features/auth/specification.md`가 `browser-session-v1`의 기준이다. 계약 변경 시 명세, OpenAPI, 공통 테스트, 모든 서버 구현, React 클라이언트를 함께 확인한다.
- PostgreSQL `browser-session-v2`의 저장 형식·원자성·장애 동작은 `features/auth/postgres-session-v2.md`와 `features/auth/postgres/001_initial.sql`을 따른다. v1 계약은 별도로 유지한다.
- 가입·이메일 확인·비밀번호 재설정은 `features/auth/account-session-v3.md`와 `features/auth/postgres/002_accounts.sql`의 선택적 v3/schema 2를 따른다. 기본 v1/v2를 유지하고 계정 작업은 같은 트랜잭션의 `account_reserve`를 해싱보다 먼저 호출한다. 실행·메일 수신·Rust TLS 절차는 `docs/account-v3.md`를 확인한다.
- 보안용 난수와 비밀번호 해싱은 검증된 라이브러리를 사용한다. 암호 알고리즘을 새로 만들지 않는다.
- 구현별 자체 테스트와 `python3 tests/conformance.py --backend all`, 클라이언트 빌드 및 브라우저 테스트를 실행한다.
- PostgreSQL 변경에는 `tests/postgres_conformance.py --browser`, 계정 흐름 변경에는 `tests/account_conformance.py --browser`도 해당 도구 환경에서 실행한다. SMTP 변경은 `features/auth/mail-delivery-v1.md`와 `tests/mail_conformance.py`를 따른다. 테스트는 loopback SMTP만 사용하며 outbox·수신 파일은 민감 데이터로 취급한다. 실제 SMTP 실행은 지정한 서버·발신 주소·요청 범위에 한정하고 공개 수신함은 제공하지 않는다.
- 테스트를 통과한 범위와 운영 환경에 필요한 추가 작업을 구분한다. 공식 보안 인증 또는 보안 감사 완료라고 표현하지 않는다.
- 생성한 파일만 커밋한다. 시크릿, `.env`, 가상환경, `node_modules`, 테스트 결과물은 커밋하지 않는다.
- 에이전트는 지정된 디렉터리 안에서만 수정하고 Git 커밋·푸시는 주 에이전트가 수행한다.
