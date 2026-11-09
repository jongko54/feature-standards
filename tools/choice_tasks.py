"""Neutral supplied-repository task variants with local HTTP path adaptation."""

from pathlib import Path

import auth_eval
import core_discovery_eval as discovery
import core_eval
from auth_eval import EvalError

SCENARIOS = ("documents", "notes")
NATIVE_CONTEXTS = {
    "python": "Python/FastAPI",
    "go": "Go/net/http",
    "java": "Java/Spring Boot",
    "rust": "Rust/Axum",
}
NEUTRAL_GUIDANCE = """
Generated source and configuration files must each be at most 2,000,000 bytes.
Keep dependency and build outputs in conventional .venv, .cache, target or bin directories.
The grader builds and starts the app independently; repeated full build loops are unnecessary.
Use normal online dependency resolution when packages are absent from local caches; do not force offline resolution.
"""


def validate_scenario(scenario):
    if scenario not in SCENARIOS:
        raise EvalError("unsupported-choice-scenario")


def prompt(stack, commit, tasks, scenario):
    validate_scenario(scenario)
    if stack not in auth_eval.STACKS:
        raise EvalError("unsupported-choice-stack")
    _, separator, body = discovery.prompt(stack, commit, tasks, "discovery").partition(
        "\n"
    )
    if not separator:
        raise EvalError("upstream-choice-task-shape-changed")
    text = (
        f"Build a {NATIVE_CONTEXTS[stack]} HTTP application in generated/. Choose your implementation approach.\n"
        + body
        + NEUTRAL_GUIDANCE
    )
    if scenario == "notes":
        text = text.replace("/api/documents", "/api/notes")
    return text


def product_path(scenario, path):
    validate_scenario(scenario)
    prefix = "/api/documents"
    if scenario == "notes" and (
        path == prefix or path.startswith((prefix + "/", prefix + "?"))
    ):
        return "/api/notes" + path[len(prefix) :]
    return path


def http_grade(scenario, port, origin, deadline, membership):
    validate_scenario(scenario)
    request = auth_eval.request

    def requester(port, method, path, *args, **kwargs):
        return request(port, method, product_path(scenario, path), *args, **kwargs)

    return core_eval.core_http_grade(
        port, origin, deadline, membership, requester=requester
    )


def contract_factory(scenario):
    validate_scenario(scenario)
    contract = core_eval.trial_contract()
    contract.profile = f"choice-{scenario}-http-v1"
    contract.prompt_builder = prompt
    contract.artifact_checker = discovery.boundary_check
    contract.http_grader = lambda generated, env, port, origin, deadline: http_grade(
        scenario, port, origin, deadline, Path(env["CORE_MEMBERSHIP_FILE"])
    )
    return contract
