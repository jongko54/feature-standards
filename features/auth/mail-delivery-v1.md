# Auth / mail-delivery-v1 — SMTP outbox 전달

기존 browser-session-v3 HTTP·schema 2를 유지하고 공유 outbox를 SMTP로 전달하는 선택 워커를 추가한다. 네 언어의 API 서버는 SMTP에 직접 연결하지 않는다. 실제 SMTP 설정과 운영 실행은 자동으로 만들지 않으며, 테스트는 작업 전용 PostgreSQL과 loopback SMTP에서만 실행한다.

## 데이터와 원자성

명시적 `003_mail_delivery.sql`은 schema_version=2를 바꾸지 않고 `mail_delivery_schema_version=1`과 `mail_delivery` sidecar를 추가한다. outbox_id FK CASCADE, stable delivery_id UUID, state(pending/leased/retry/delivered/failed/cancelled), attempts, next_attempt_at, claim_id UUID, lease_until, last_error_code를 보관한다. 기존 outbox와 새로 생성되는 outbox에 sidecar가 준비된다. 앱 시작 시 자동 migration은 없다.

claim은 짧은 DB 트랜잭션에서 outbox 행을 `FOR UPDATE SKIP LOCKED`로 먼저 잠그고, 별도 최신 statement로 sidecar를 잠가 상태·기한을 다시 검사한다. 잠금 순서는 outbox→sidecar이며 사용자는 잠그지 않는다. 기존 계정 연산의 user→token→outbox 순서와 역순으로 잠그면 안 된다. pending, 재시도 시각이 지난 retry, lease가 만료된 leased만 claim할 수 있다. DB clock_timestamp를 사용한다. claim_id를 새로 만들고 attempts를 증가시킨 뒤 commit한다.

전송 전에 사용자 admin_enabled, 확인/재설정 종류의 계정 상태, 현재 account_tokens의 hash·user·kind·만료, outbox token·만료 및 claim을 다시 확인한다. 이미 소비·교체·만료·관리자 차단된 capability는 전송하지 않고 cancelled 처리하며 원문을 지운다. 이 확인과 실제 이메일 수신 사이의 동시 상태 변경까지 막는다고 주장하지 않는다.

SMTP I/O는 DB 트랜잭션 밖에서 수행한다. DATA의 최종 250 응답을 받은 경우에만 ACK한다. ACK는 delivery_id·claim_id·leased 상태·현재 outbox token을 모두 비교한 뒤 parent.delivered_at을 설정하고 token을 제거한다. 다른 claim이나 재발급 메시지를 변경하지 않는다. 실패 ACK도 같은 fence를 사용한다. 성공 후 QUIT 오류는 이미 확인한 SMTP 수락을 취소하지 않는다.

4xx·연결/시간초과·TLS/인증 오류는 제한된 재시도 대상이고, 5xx·잘못된 주소·SMTPUTF8 미지원은 terminal 실패이다. 최대 시도 횟수 기본 5(1..20), 지연은 30×2^(attempts-1)초에서 3600초까지이다. terminal 실패/시도 초과/취소는 원문 capability를 지우고 delivered_at을 설정하지 않는다. 오류는 정해진 코드만 저장한다. 원문 서버 응답·주소·token·비밀번호·DB URL을 로그에 남기지 않는다.

SMTP가 수락했지만 연결이 끊기거나 DB ACK 결과가 불명확한 경우와, lease 중단·재시작·만료 경계에서는 중복 전송이 가능하다. 같은 delivery_id의 Message-ID를 재사용하는 at-least-once 전달이며 exactly-once나 실제 수신함 도착을 보장하지 않는다. socket timeout은 전체 전송 기한과 다르다. lease 기본값은 최소 300초이며 SMTP timeout에 맞춰 충분히 길게 잡고, stale worker의 DB ACK는 fence로 차단한다.

## SMTP와 메시지

설정은 `AUTH_SMTP_HOST`, `AUTH_SMTP_PORT`, `AUTH_SMTP_MODE=starttls|tls|plain-local`, `AUTH_SMTP_USERNAME`, `AUTH_SMTP_PASSWORD`, `AUTH_SMTP_FROM`, `AUTH_SMTP_CA_FILE`, `AUTH_SMTP_TIMEOUT_SECONDS`, `AUTH_MAIL_PUBLIC_ORIGIN`, `AUTH_MAIL_DEMO`이다. username/password는 함께 존재하거나 함께 없어야 한다. 기본 mode는 starttls, port는 587(tls는 465), timeout은 10초(1..30)이다. 비밀번호와 token은 repr에도 노출하지 않는다.

STARTTLS는 EHLO 후 TLS 승격과 승격 후 EHLO를 요구하며 지원되지 않으면 실패한다. 직접 TLS와 STARTTLS 모두 인증서 체인·호스트명 검증 및 TLS 1.2 이상을 사용한다. 인증은 TLS 후에만 한다. plain-local은 명시적 demo, 숫자 loopback 목적지, loopback HTTP origin에서만 허용하고 인증 정보를 허용하지 않는다. 원격 평문이나 TLS 검증 해제·fallback은 제공하지 않는다.

발신 주소와 단일 수신 주소는 mailbox 문법과 CR/LF를 검증한다. 한 개의 envelope recipient를 명시해 header 재파싱으로 수신자가 늘지 않게 한다. 국제화 수신자는 SMTPUTF8을 협상하며, 서버가 지원하지 않으면 임의로 ASCII 변환하지 않는다. Message-ID는 `<feature-standards.{delivery_id}@발신주소domain>`으로 고정한다. 신뢰 설정 origin의 `/verify-email#token=...` 또는 `/reset-password#token=...` 링크를 한국어 plain/html MIME에 넣고 HTML은 escape한다. 요청 Host나 임의 redirect는 사용하지 않는다.

## 운영 경계와 검증

`tools/mail_worker.py --once`는 최대 batch만 처리하고 종료하며, 일반 실행은 유한 poll 간격과 종료 신호를 처리한다. 작업용 DB에서만 사용하는 기존 `mail_capture.py`는 아직 SMTP 소유권이 없는 pending 메시지만 캡처한다. outbox 잠금 후 sidecar를 별도 statement로 확인하여 claim과 경쟁하지 않는다. retry/leased/terminal 메시지를 가져가지 않는다. 확장 migration이 없는 schema 2에서는 종전 캡처 동작을 유지한다.

SMTP 계정·발신 domain 검증·비밀 관리·실제 수신 주소·provider 제한과 운영 실행은 배포자가 설정한다. outbox와 수신 파일의 원문 capability는 계속 민감 데이터이다. 공통 HTTP 계약을 바꾸지 않고 공급자 독립 전송, CA/hostname/STARTTLS 거절, SMTPUTF8·단일 수신자·MIME, 4xx/5xx·수락 후 QUIT 오류, 다중 worker claim·만료 lease·fenced ACK·DB 장애·token 교체 및 실제 계정 흐름을 검증한다.
