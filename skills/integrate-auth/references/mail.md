# 선택 SMTP 전달

`features/auth/mail-delivery-v1.md`, `docs/smtp-delivery.md`를 읽는다. `003_mail_delivery.sql`은 계정 schema 2를 바꾸지 않는 독립 addon이다. `tools/mail_worker.py`를 별도로 실행하고 API 프로세스에서 직접 발송하지 않는다.

TLS·단일 수신자·SMTPUTF8·lease/claim fence·유한 재시도를 보존한다. 실제 호스트·발신 주소·인증은 지정한 배포 설정으로 주입하며 스킬이 발송 권한을 추가하지 않는다. SMTP 수락·DB ACK·실제 수신함 도착을 구분한다. ambiguous ACK·lease 경계는 at-least-once 중복을 허용한다. 캡처는 leased/retry 메시지를 가져가지 않는다.

`tools/check_mail_contract.py`는 정적 매핑이고 `tests/mail_conformance.py`는 네 언어의 로컬 TLS SMTP·캡처/claim 경합 실행이다. 테스트에는 loopback SMTP·작업 전용 DB만 쓰고 실제 수신자·운영 DB를 사용하지 않는다. outbox·수신 파일은 민감하게 취급한다.
