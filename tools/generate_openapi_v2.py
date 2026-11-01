"""Derive the PostgreSQL profile from v1 without silently overwriting v1."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "features/auth/openapi-v2.json"


def build_spec(v1: dict) -> dict:
    """Return the deterministic v2 extension; v1 remains an independent contract."""
    spec = copy.deepcopy(v1)
    spec["info"].update(
        title="Feature Standards: browser-session-v2",
        version="0.2.0",
        description=(
            "공통 PostgreSQL 사용자·세션·실패 기록을 사용하는 실험적 참조 규격. "
            "HTTP 입력 경계는 specification.md, 저장소·원자성·장애 동작은 "
            "postgres-session-v2.md가 기준이다. 운영 보안 감사 완료를 뜻하지 않는다."
        ),
    )
    spec["x-source-contract"] = "openapi.json"
    spec["x-scenario-manifest"] = "scenarios-v2.json"
    spec["tags"][1]["description"] = "PostgreSQL 연결과 schema version 1 준비 상태"
    user_id = spec["components"]["schemas"]["User"]["properties"]["id"]
    user_id.pop("const")
    user_id.update(
        minLength=1,
        maxLength=128,
        description="feature_auth.users.id 원본 문자열. 계정마다 다르며 정규화하지 않는다.",
        examples=["demo-user", "other-user"],
    )
    codes = spec["components"]["schemas"]["Error"]["properties"]["error"]["properties"][
        "code"
    ]["enum"]
    codes.append("STORAGE_UNAVAILABLE")
    spec["components"]["responses"]["StorageUnavailable"] = {
        "description": (
            "STORAGE_UNAVAILABLE. DB 연결·쿼리·커밋 실패 또는 지원하지 않는 저장 해시. "
            "URL·자격 증명·DB 오류 원문을 공개하지 않으며 Set-Cookie를 발급하지 않는다. "
            "메모리 fallback 또는 로그아웃 성공으로 처리하지 않는다."
        ),
        "headers": {
            "Cache-Control": {"$ref": "#/components/headers/NoStore"},
            "X-Content-Type-Options": {"$ref": "#/components/headers/NoSniff"},
        },
        "content": {
            "application/json": {
                "schema": {"$ref": "#/components/schemas/Error"},
                "example": {
                    "error": {
                        "code": "STORAGE_UNAVAILABLE",
                        "message": "STORAGE_UNAVAILABLE",
                    }
                },
            }
        },
    }
    for path, method in (
        ("/auth/login", "post"),
        ("/auth/me", "get"),
        ("/auth/logout", "post"),
        ("/healthz", "get"),
    ):
        spec["paths"][path][method]["responses"]["503"] = {
            "$ref": "#/components/responses/StorageUnavailable"
        }
    spec["paths"]["/auth/login"]["post"]["description"] = (
        "Origin 정확 일치 필수. DB의 정규화된 이메일과 enabled 사용자를 조회한다. "
        "실패 제한은 PostgreSQL inet peer와 공통 advisory transaction lock을 사용한다. "
        "실패 기록·성공 시 실패 제거·기존 요청 쿠키 세션 교체·새 세션 저장을 원자적으로 처리하고, "
        "COMMIT 성공 이후에만 사용자·독립 CSRF 토큰과 세션 쿠키를 반환한다."
    )
    spec["paths"]["/auth/me"]["get"]["description"] = (
        "SHA-256 토큰 해시와 enabled 사용자, DB 시각 기준 만료를 조회한다. "
        "세션에 연결된 사용자 원본 id와 이메일을 반환하며 절대 TTL을 연장하지 않는다."
    )
    logout = spec["paths"]["/auth/logout"]["post"]
    logout["description"] = (
        "Origin은 항상 필수이다. FOR UPDATE로 잠근 만료 전 저장 세션은 사용자 enabled 여부와 "
        "무관하게 정확히 한 개의 일치하는 X-CSRF-Token을 요구한다. 실패 시 403으로 세션을 유지한다. "
        "정확한 CSRF이면 삭제를 COMMIT한 뒤 204와 쿠키 제거를 반환한다. "
        "세션 누락·만료는 CSRF 없이 멱등 204이며 DB 실패는 503이다."
    )
    logout["parameters"][1]["description"] = (
        "만료 전 저장 세션에는 사용자 enabled 여부와 무관하게 필수. "
        "해당 세션에서 발급한 csrfToken 한 개를 상수 시간으로 비교한다."
    )
    health = spec["paths"]["/healthz"]["get"]
    health["summary"] = "PostgreSQL 저장소 준비 상태"
    health["description"] = (
        "연결과 schema version 1을 확인한다. 준비되었으면 browser-session-v2, "
        "저장소 실패이면 일반 503을 반환한다. 앱은 자동 DDL·seed를 수행하지 않는다."
    )
    health["responses"]["200"]["content"]["application/json"]["schema"]["properties"][
        "profile"
    ] = {"const": "browser-session-v2"}
    return spec


def serialized_spec() -> str:
    v1 = json.loads((ROOT / "features/auth/openapi.json").read_text())
    return json.dumps(build_spec(v1), ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Fail on generated-document drift"
    )
    args = parser.parse_args()
    generated = serialized_spec()
    if args.check:
        if not DESTINATION.exists() or DESTINATION.read_text() != generated:
            print("v2 OpenAPI drift: run python tools/generate_openapi_v2.py")
            return 1
        print("v2 OpenAPI matches the v1-derived generator.")
        return 0
    DESTINATION.write_text(generated)
    print("Generated features/auth/openapi-v2.json; v1 is unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
