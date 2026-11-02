"""Derive the opt-in account profile from v2; existing profiles remain unchanged."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "features/auth/openapi-v3.json"
ACCOUNT_PATHS = {
    "/auth/register": ("register", "Register", "가입 요청을 접수한다"),
    "/auth/email-verification/request": (
        "requestEmailVerification",
        "AccountEmail",
        "이메일 확인 메시지를 요청한다",
    ),
    "/auth/email-verification/confirm": (
        "confirmEmailVerification",
        "AccountToken",
        "이메일 확인 토큰을 한 번 사용한다",
    ),
    "/auth/password-reset/request": (
        "requestPasswordReset",
        "AccountEmail",
        "비밀번호 재설정 메시지를 요청한다",
    ),
    "/auth/password-reset/confirm": (
        "confirmPasswordReset",
        "ResetPassword",
        "비밀번호와 모든 기존 세션을 교체한다",
    ),
}


def build_spec(v2: dict) -> dict:
    spec = copy.deepcopy(v2)
    spec["info"].update(
        title="Feature Standards: browser-session-v3",
        version="0.3.0",
        description=(
            "명시적 schema 2의 선택적 계정 생명주기 참조 규격. "
            "account-session-v3.md가 가입·이메일 확인·비밀번호 재설정·outbox의 기준이다. "
            "기존 v1/v2는 별도 프로필과 스키마에서 유지한다."
        ),
    )
    spec["x-source-contract"] = "openapi-v2.json"
    spec["x-scenario-manifest"] = "scenarios-v3.json"
    spec["x-database-schema-version"] = 2
    spec["x-required-config"] = {
        "AUTH_STORE": "postgres",
        "AUTH_ACCOUNT_LIFECYCLE": "true",
    }
    spec["tags"].append(
        {
            "name": "accounts",
            "description": "명시적 계정 생명주기; 자동 로그인과 외부 메일 발송 없음",
        }
    )
    schemas = spec["components"]["schemas"]
    schemas["Error"]["properties"]["error"]["properties"]["code"]["enum"].append(
        "INVALID_TOKEN"
    )
    email = {
        "type": "string",
        "minLength": 1,
        "description": (
            "양끝 ASCII 공백 제거·ASCII A-Z 소문자화 후 @ 필수·UTF-8 254byte 이하. "
            "정규화 후 U+0000..U+0020 또는 U+007F가 남으면 거절한다."
        ),
    }
    password = {
        "type": "string",
        "minLength": 15,
        "maxLength": 1024,
        "writeOnly": True,
        "description": "Unicode scalar 15개 이상, UTF-8 1024byte 이하. 공백과 NUL을 보존한다. 기존 로그인 규칙은 유지한다.",
    }
    token = {
        "type": "string",
        "minLength": 43,
        "maxLength": 43,
        "pattern": "^[A-Za-z0-9_-]{43}$",
        "writeOnly": True,
        "description": "32byte 난수의 base64url no-padding capability. 로그·영구 브라우저 저장소에 기록하지 않는다.",
    }
    for name, properties in {
        "Register": {"email": email, "password": password},
        "AccountEmail": {"email": email},
        "AccountToken": {"token": token},
        "ResetPassword": {"token": token, "password": password},
    }.items():
        schemas[name] = {
            "type": "object",
            "additionalProperties": False,
            "required": list(properties),
            "properties": copy.deepcopy(properties),
        }
    schemas["AccountAccepted"] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["status"],
        "properties": {"status": {"type": "string", "const": "accepted"}},
    }
    headers = {
        "Cache-Control": {"$ref": "#/components/headers/NoStore"},
        "X-Content-Type-Options": {"$ref": "#/components/headers/NoSniff"},
    }
    spec["components"]["responses"]["AccountBadRequest"] = {
        "description": (
            "INVALID_REQUEST: JSON·UTF-8·추가/중복 키·필드 정책 오류. "
            "INVALID_TOKEN: 올바른 형식의 토큰이 없거나 만료·재사용·종류 불일치·관리자 비활성이다."
        ),
        "headers": copy.deepcopy(headers),
        "content": {
            "application/json": {"schema": {"$ref": "#/components/schemas/Error"}}
        },
    }
    rate = copy.deepcopy(v2["paths"]["/auth/login"]["post"]["responses"]["429"])
    rate["description"] = (
        "RATE_LIMITED. 실제 TCP peer+action 기준 60초 10회. 계정 존재 여부와 관계없이 같은 정책이다."
    )
    for path, (operation_id, schema, summary) in ACCOUNT_PATHS.items():
        confirm = path.endswith("/confirm")
        success = {
            "description": (
                "COMMIT 후 본문 없는 완료. 자동 로그인·Set-Cookie 없음."
                if confirm
                else "동일한 일반 접수. 기존/없는/비활성 계정 정보를 드러내지 않고 Set-Cookie를 발급하지 않는다."
            ),
            "headers": copy.deepcopy(headers),
        }
        if not confirm:
            success["content"] = {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/AccountAccepted"}
                }
            }
        responses = {
            "204" if confirm else "202": success,
            "400": {"$ref": "#/components/responses/AccountBadRequest"},
            "403": {"$ref": "#/components/responses/OriginDenied"},
            "405": {"$ref": "#/components/responses/MethodNotAllowed"},
            "413": {"$ref": "#/components/responses/TooLarge"},
            "415": {"$ref": "#/components/responses/UnsupportedMediaType"},
            "429": copy.deepcopy(rate),
            "503": {"$ref": "#/components/responses/StorageUnavailable"},
        }
        spec["paths"][path] = {
            "post": {
                "operationId": operation_id,
                "tags": ["accounts"],
                "summary": summary,
                "description": (
                    "AUTH_ACCOUNT_LIFECYCLE=true 선택 시만 제공. 정확한 Origin·엄격 JSON·최대 4096byte가 필수이다. "
                    "동일 이메일/종류 메일 발급은 60초 cooldown이며 HTTP 응답은 동일하다. "
                    "확인 토큰 24시간, reset 토큰 15분 절대 만료·단일 사용이다. "
                    "reset은 PHC 교체·전체 사용자 세션·reset 토큰 삭제를 원자적으로 commit한다. "
                    "관리자 비활성은 확인/재설정으로 해제하지 않는다. 토큰·링크를 HTTP로 반환하지 않는다."
                ),
                "security": [],
                "parameters": [{"$ref": "#/components/parameters/Origin"}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": f"#/components/schemas/{schema}"}
                        }
                    },
                },
                "responses": responses,
            }
        }
    spec["paths"]["/auth/login"]["post"]["description"] += (
        " v3는 generated enabled로 이메일 확인·관리자 허용을 함께 검사한다. "
        "사용자 FOR SHARE 잠금을 PHC 검증부터 새 세션 commit까지 유지해 reset과 직렬화한다."
    )
    spec["paths"]["/auth/me"]["get"]["description"] += (
        " v3의 generated enabled가 이메일 미확인·관리자 비활성을 차단한다."
    )
    health = spec["paths"]["/healthz"]["get"]
    health["description"] = (
        "DB 연결과 schema version 2를 확인한다. 앱은 자동 DDL·seed를 하지 않는다."
    )
    health["responses"]["200"]["content"]["application/json"]["schema"]["properties"][
        "profile"
    ] = {"const": "browser-session-v3"}
    return spec


def serialized_spec() -> str:
    v2 = json.loads((ROOT / "features/auth/openapi-v2.json").read_text())
    return json.dumps(build_spec(v2), ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Fail on generated-document drift"
    )
    args = parser.parse_args()
    generated = serialized_spec()
    if args.check:
        if not DESTINATION.exists() or DESTINATION.read_text() != generated:
            print("v3 OpenAPI drift: run python tools/generate_openapi_v3.py")
            return 1
        print("v3 OpenAPI matches the v2-derived generator.")
        return 0
    DESTINATION.write_text(generated)
    print("Generated features/auth/openapi-v3.json; v1/v2 are unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
