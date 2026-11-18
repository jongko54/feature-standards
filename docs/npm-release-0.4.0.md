# feature-standards 0.4.0 게시 확인

2026-11-18에 main npm 패키지 **feature-standards 0.4.0**을 GitHub OIDC로
게시했다. 공개 버전·다운로드·새 registry 설치를 별도로 확인했다.
정제한 [게시 영수증](npm-release-0.4.0.json)이 실제 해시와 workflow 참조를 담는다.

- 릴리스 소스: `988d7a9ecbf0b62f728f7575ece2217aa61486bb`
- 태그: `feature-standards-v0.4.0`
- [기능 CI](https://github.com/jongko54/feature-standards/actions/runs/44317333610): 56단계 통과
- [보안 CI](https://github.com/jongko54/feature-standards/actions/runs/44317333598): 의존성 1,021개 항목·정적 소스 151개·시크릿 검사 통과, 발견 0건
- [게시 workflow](https://github.com/jongko54/feature-standards/actions/runs/44320618986): 성공

공개 tarball은 CI에서 검토한 192,322바이트 아카이브와 동일했다.
SHA-256은 `8ef56f30fe72a69fce5347a5968942e59226f60c5886a7706d9fad88e2620ab8`이다.
새 npm 캐시·빈 설정으로 공개 registry 버전을 설치해 전체 context 26개와
compact 카드 26개 및 문서 해시를 확인했다. 실제 Python core starter를 생성해
12개 HTTP·권한·목록·SDK 출처 검사를 통과했다. 이 starter 검증은 메모리
프로필이며 DB·SMTP·브라우저는 같은 릴리스 소스의 기능 CI와 구분한다.

```sh
npx feature-standards@0.4.0 list
npx feature-standards@0.4.0 context --feature authorization --stack python --compact
```

0.4.0은 compact 읽기 카드와 세 기능 starter를 제공한다. starter 실행에는
명시한 신뢰할 수 있는 소스 checkout이 필요하다. 각 언어의 runtime SDK는
별도 배포 단위다. npm의 provenance URL은 관측했지만 이 영수증에서 서명을
독립 검증하지는 않았다. 보안 결과는 해당 날짜·소스·선택한 도구 범위의 근거이며
독립 보안 감사나 인증이 아니다.
