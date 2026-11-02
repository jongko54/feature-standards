# 보안 범위

v1 메모리, v2 PostgreSQL과 v3 계정 생명주기는 동작을 비교하고 검증하는 실험적 참조 구현입니다. 보안 감사나 외부 인증을 받은 제품이 아닙니다. 계약 테스트 통과는 해당 입력·환경에서 관찰한 동작의 근거입니다. 기존 v2 로컬 결과는 [검증 기록](docs/validation-2026-11-02.md), v3 최종 검증과 원격 반영은 해당 실행 기록과 커밋의 Actions로 확인합니다.

## 저장소와 계정

- 기본 `AUTH_STORE=memory`는 환경 설정 사용자 한 명과 프로세스 메모리 세션·실패 기록을 사용합니다. 재시작·다중 인스턴스 사이에 상태를 공유하지 않습니다.
- `AUTH_STORE=postgres`는 [v2 계약](features/auth/postgres-session-v2.md)의 공통 DB 사용자·세션·실패 기록을 사용합니다. 원문 세션 토큰은 저장하지 않고 SHA-256 bytea만 저장합니다. CSRF 토큰은 독립 난수입니다.
- 비밀번호 PHC는 Argon2id v19, 64 MiB, 반복 3회, 병렬도 4, salt 16바이트, hash 32바이트를 요구합니다. 지원하지 않는 저장 해시와 DB 실패는 일반 `503 STORAGE_UNAVAILABLE`로 거절하며 새 쿠키를 발급하지 않습니다.
- DB 모드는 시작 시 연결과 선택한 프로필의 스키마를 검사합니다(v2=1, v3=2). 자동 DDL·seed·메모리 fallback을 제공하지 않습니다. `AUTH_DEMO=true`도 DB 사용자를 생성하거나 덮어쓰지 않습니다.
- 공개 데모 계정은 명시적인 `seed-demo --confirm-demo` 도구로만 준비하며 재실행은 기존 사용자와 비밀번호를 덮어쓰지 않습니다. v3의 [가입·확인·재설정 계약](features/auth/account-session-v3.md)은 별도로 명시한 입력·트랜잭션 규칙을 사용합니다. 역할 관리·MFA·비밀번호 blocklist 정책은 제공하지 않습니다.
- 비활성 사용자는 로그인·조회에서 거절합니다. 만료 전 저장 세션의 로그아웃에는 사용자 enabled 여부와 무관하게 정확한 CSRF가 필요합니다.
- v3의 generated enabled는 관리자 허용과 이메일 확인을 함께 요구합니다. 가입·확인·재설정은 자동 로그인하지 않으며 관리자의 비활성을 해제하지 않습니다. 신규·재설정 비밀번호는 Unicode scalar 15개 이상·UTF-8 1024byte 이하이고 기존 로그인 정책은 유지합니다.
- 계정 token 검증 테이블에는 SHA-256만 저장합니다. 확인은 24시간, reset은 15분 절대 만료·단일 사용입니다. reset은 비밀번호 교체·전체 사용자 세션 폐기·reset token 삭제를 한 트랜잭션으로 처리합니다. 로그인 사용자 FOR SHARE와 reset FOR UPDATE가 구 비밀번호의 지연 로그인 경합을 막습니다.
- mail_outbox에는 전달용 원문 capability가 들어 있습니다. [SMTP 전달 계약](features/auth/mail-delivery-v1.md)의 선택 워커는 짧은 claim·전송 직전 유효성 검사·fenced ACK·제한된 재시도를 사용합니다. 실제 SMTP 계정·발신 주소는 배포자가 설정하며 운영 발송을 자동 실행하지 않습니다. 공개 HTTP 수신함은 없습니다. 로컬 도구는 SMTP가 소유하지 않은 pending 테스트 메시지만 새 0600 파일로 캡처합니다. outbox와 수신 파일은 별도 민감 데이터로 접근 권한·암호화·보존 정책이 필요합니다. token 전체가 DB에서 항상 해시로만 저장된다고 주장하지 않습니다.

## 네트워크와 운영 한계

- rate limit은 실제 TCP peer 기준입니다. 전달 헤더를 신뢰하지 않으며 프록시 뒤에서는 사용자를 구분하지 못합니다. IPv4/IPv6 또는 다중 프록시 경로를 하나의 사용자 식별자로 통합하는 정책은 제공하지 않습니다.
- 공통 로컬 DB 검증은 loopback `sslmode=disable`을 사용합니다. Rust 원격 연결은 `sslmode=verify-full`, TLS 1.2 이상에서 인증서 체인과 hostname을 검증하며, 별도 PEM CA 또는 플랫폼 신뢰 루트를 사용합니다. 약한 모드·host override·TLS 거절 후 평문 재시도는 허용하지 않습니다. TLS fixture는 전용 로컬 CA로 성공·잘못된 CA·hostname·평문 서버 거절을 확인합니다.
- 다른 구현의 드라이버가 TLS 옵션을 제공하더라도 원격 운영 DB의 인증서·호스트 검증, 인증·최소 권한·접근 제어·백업·용량 검토가 완료되었다는 뜻은 아닙니다.
- 참조 서버는 인터넷에 직접 노출하는 운영 배포 설정을 제공하지 않습니다. HTTPS 종료, 신뢰 프록시, DDoS·요청 크기·연결 수 제한, 비밀 관리, 관측·로그 보존 정책은 별도 설계가 필요합니다.
- DB URL, 연결 오류 원문, 비밀번호, 원문 세션과 CSRF 토큰을 로그·이슈·테스트 아티팩트에 기록하지 마세요.
- SMTP는 STARTTLS 또는 직접 TLS에서 인증서 체인·호스트명과 TLS 1.2 이상을 요구하며 평문 fallback을 허용하지 않습니다. 인증 없는 숫자 loopback 평문은 별도 메일 데모에서만 허용합니다. 운영 워커의 DB 연결도 verify-full을 요구합니다. 수신자·SMTP 서버 원문 오류·capability를 로그에 저장하지 않습니다.
- DATA 250은 중계 서버 수락이며 실제 수신함 도착이 아닙니다. 수락 응답·DB ACK 유실과 lease 만료에서는 중복 전송이 가능합니다. Message-ID를 유지하는 at-least-once 방식이며 exactly-once를 주장하지 않습니다. 실제 제공자 인증·발신 domain·수신 주소와 SPF/DKIM/DMARC·발송 한도 설정은 [SMTP 안내](docs/smtp-delivery.md)를 따릅니다.

## 테스트 데이터와 제보

[v2 공통 harness](tests/postgres_conformance.py), [v3 harness](tests/account_conformance.py), [소비 앱 harness](tests/consumer_conformance.py)는 `feature_auth` 스키마를 초기화합니다. 외부 DB는 loopback·명시적 포트·ASCII `feature_standards_test*` 이름을 검사하며 작업 전용 DB에서만 실행합니다. fixture는 `sslmode=disable` 외 query와 값이 있는 `PG*` 환경도 거절합니다. 이는 앱의 TLS URI 정책과 다른 테스트 대상 보호 규칙입니다. 운영 DB와 기존 사용자 데이터에는 실행하지 마세요.

취약점은 저장소 소유자에게 비공개 채널로 먼저 제보해 주세요. 시크릿과 공격 가능한 상세 내용을 공개 이슈에 게시하지 마세요. 공개 전환 시 제보 경로를 별도로 정합니다.
