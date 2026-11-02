# SMTP outbox 전달 고도화

기존 v3의 외부 SMTP 연결 공백을 채운다. 공급자 독립 전송, optional sidecar migration, leased/fenced queue worker, 기존 local capture 조정과 CI·문서를 구현한다. 현재 SMTP 호스트·인증 설정은 없으므로 실제 공급자 발송은 설정을 기다리며, 전체 검증은 전용 PostgreSQL과 로컬 TLS SMTP 서버에서 수행한다.

1. 부모가 mail-delivery-v1 계약·003 확장 migration·capture 공존 규칙을 만든다.
2. SMTP 에이전트가 TLS/MIME/SMTPUTF8/오류 분류 전송과 실제 wire 검증을 구현한다. Queue 에이전트는 claim·fence·retry·CLI와 DB 회귀를 구현한다. 독립 에이전트가 잠금·외부 수락·DB ACK·민감 정보 경계를 검수한다.
3. 부모가 네 언어 계정 발급→SMTP→메일 링크 소비 통합과 CI·운영 예제를 연결한다.
4. 실제 검사·후속 리뷰 후 변경 파일만 commit/push하고 원격 ref·Actions를 확인한다.

에이전트는 지정 파일만 수정하고 Git은 부모만 수행한다. 운영 DB, 기존 사용자 메일함, 실제 수신자에는 자동 발송하지 않는다. SMTP 수락과 실제 수신함 도착을 구분하고, 불명확한 SMTP/DB 결과의 중복 가능성을 숨기지 않는다.
