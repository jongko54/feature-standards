# 선행 프로젝트 조사

2026-10-28 공개 문서·명세·일부 소스 조사에 기반합니다. 레포 전체 보안 감사나 성능 평가가 아닙니다. 이 프로젝트는 아래 소스의 코드를 복사하지 않고 공통 계약과 검증 구성 방식을 참고했습니다.

| 프로젝트 | 참고한 점 |
|---|---|
| [RealWorld](https://github.com/realworld-apps/realworld) | 여러 구현이 같은 API와 공통 검증을 따르는 구조 |
| [Better Auth](https://github.com/better-auth/better-auth) / [Skills](https://github.com/better-auth/skills) | 인증 프레임워크와 AI 통합 지침의 배포 |
| [Spring Security Samples](https://github.com/spring-projects/spring-security-samples) | Java의 인증·세션·OAuth 예제 |
| [django-allauth](https://github.com/pennersr/django-allauth) | 계정 관리와 인증 통합. GitHub는 Codeberg 원본의 미러 |
| [SCS](https://github.com/alexedwards/scs) | Go 서버 저장 세션의 갱신·파기 |
| [axum-login](https://github.com/maxcountryman/axum-login) | Rust의 인증·권한·세션 미들웨어 |
| [NEBULA](https://github.com/nebula-token/nebula-token) | 기능별 단일 명세, 다중 언어 구현, 공통 동작 벡터 |

보안 동작은 [OWASP 세션 관리](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)와 [CSRF 방어](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)를 바탕으로 좁은 프로필로 정의했습니다. OAuth/OIDC 같은 외부 인증 표준의 새 구현을 제공하는 레포는 아닙니다.
