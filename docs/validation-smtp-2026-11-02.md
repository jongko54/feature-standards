# SMTP 전달 확장 검증 기록

2026-11-02 macOS arm64, PostgreSQL 18.6과 Python 3.13.13 tools 환경에서 실행했다. SMTP 어댑터는 별도 Python 3.12 환경에서도 검증했다. 아래는 로컬 실행 결과이며 해당 커밋의 원격 Linux 결과는 [Actions](https://github.com/jongko54/feature-standards/actions)에서 별도로 확인한다.

## 실제 검사

| 범위 | 결과 |
|---|---|
| 설정·SMTP wire | 15 통과, Python 3.12·3.13 각각 확인 |
| PostgreSQL worker·lease·fence·실패 집계 | 19 통과 |
| 기존 캡처와 SMTP 소유권·migration 재실행 | 4 통과 |
| 네 언어 → 실제 TLS SMTP → 확인/재설정 및 경합 | 8 통과 |
| 기존 계정 SQL·private 파일·COMMIT 불명확 회귀 | 13 통과 |
| 실행기·fixture 일반 검사 | 17 통과 |

위 단위 범위를 함께 실행한 68개가 skip 없이 통과했다. SMTP 전용 범위는 선언된 46개(15+19+4+8)이고, 단순 정적 매핑과 실제 실행을 구분한다. PostgreSQL v2 회귀도 HTTP 76개·같은 React 32개·Secure 쿠키 4개·혼합 8개와 각 언어의 두 인스턴스·재시작 검사가 통과했다. 기존 v1/v3 전체 코드와 실행 이력은 [계정 확장 기록](validation-2026-11-02-accounts-v3.md)을 참고하며, 새 CI 정의는 기존 전체 matrix를 계속 실행한다.

실제 네 언어의 Unicode 이메일 가입 요청이 공통 outbox에 들어간 뒤 worker가 STARTTLS와 SMTPUTF8로 전달했다. 메모리 안의 SMTP MIME 메시지에서 확인·재설정 링크를 읽어 다른 언어의 API에서 소비했고, 재설정 뒤 모든 서버에서 기존 쿠키가 401이 됨을 확인했다. SMTP fixture는 numeric loopback에서만 수신하고 임시 CA로 인증서를 검증했다. 외부 중계 서버나 실제 사용자 메일함에는 접근하지 않았다.

## 실패·동시성 근거

- 신뢰 CA의 STARTTLS·직접 TLS와 TLS 뒤 AUTH 성공, 잘못된 CA·hostname·STARTTLS 미지원 거절, SMTPUTF8 미지원과 header/multiple-recipient 주입 거절을 확인했다.
- RCPT/DATA 4xx와 5xx, 소켓 timeout, DATA 수락 응답 유실, 알려진 DATA 수락 뒤 QUIT 오류를 실제 SMTP wire로 구분했다.
- retry는 같은 delivery ID·Message-ID를 유지하고, 아직 due가 아니면 전송하지 않았다. 영구 실패·시도 초과는 원문을 지우고 delivered_at을 성공처럼 설정하지 않았다.
- 두 SMTP worker가 경쟁해 실제 전송은 하나였다. 캡처와 SMTP worker의 barrier 경합을 6회 실행해 소비 합계가 항상 하나였다.
- SMTP DATA를 받은 상태에서 ACK를 멈춘 동안 Java API로 토큰을 재발급해도 계정 작업은 대기하지 않았다. 오래된 SMTP ACK는 fenced되었고 새 pending 메시지와 새 토큰이 보존됐다.
- DATA 뒤 연결을 끊은 모호한 결과는 같은 Message-ID·token으로 재시도했다. 서버가 두 번 DATA를 받은 사실과 클라이언트가 확인한 수락·DB ACK를 구분했다.
- claim COMMIT 실패 전에는 전송하지 않고, SMTP 수락 후 DB COMMIT 응답 유실은 SMTP 실패로 재분류하지 않았다. lease 회수와 stale ACK·재발급의 fence도 확인했다.

## 검수와 재현

독립 읽기 검수에서 Python 3.12 TLS hostname 초기화, Unicode mailbox 파싱, CI의 새 DB 선행 migration 누락과 실패 시 token assertion 출력 문제를 찾아 수정했다. 실제 wire·DB 회귀와 후속 소스 검수에서 미해결 P1/P2는 발견하지 못했다. 일반 코드는 주소·token·인증정보·원문 SMTP 진단을 로그에 남기지 않고 whitelist 코드·집계만 보관한다.

OpenAPI 기존 프로필 검사, 새 mail 시나리오/오류 코드 checker, Ruff·format, 두 workflow의 actionlint·byte 동일, 스킬 형식 검사와 문서 로컬 링크를 확인했다. CI 준비 도구는 별도 새 PostgreSQL의 13개 DB에서 두 번 실행해 schema 1·2/addon 1과 기존 비밀번호 해시 보존을 확인했다. setup 도구와 테스트는 task-owned 서버만 사용했다.

```sh
uv run --frozen --project tools python tools/check_contract.py
uv run --frozen --project tools python tools/check_mail_contract.py
# AUTH_MAIL_TEST_DATABASE_URL / AUTH_MAIL_CAPTURE_TEST_DATABASE_URL을 각각 다른 전용 DB로 설정:
uv run --frozen --project tools python -W error::ResourceWarning -m unittest discover -s tests -p test_smtp_transport.py -v
uv run --frozen --project tools python -m unittest discover -s tests -p test_mail_worker.py -v
uv run --frozen --project tools python -m unittest discover -s tests -p test_mail_capture_delivery.py -v
# 또 다른 전용 FEATURE_STANDARDS_TEST_DATABASE_URL 또는 PostgreSQL server binaries 사용:
uv run --frozen --project tools python tests/mail_conformance.py
```

실제 SMTP 호스트·발신 주소·인증정보가 없으므로 운영 제공자 연결·수신함 도착은 검증하지 않았다. 워커는 공급자 독립 코드와 설정 템플릿까지 제공한다. SMTP 수락은 수신함 도착이 아니며, lease·네트워크·DB ACK 경계의 중복을 허용하는 at-least-once이다. 테스트의 성공을 운영 메일 전달률·DNS 인증·exactly-once 보장으로 확대하지 않는다. 기존 Cargo 캐시 권한 경고는 있었지만 관련 빌드·검사는 exit 0이었고 전역 권한은 변경하지 않았다.
