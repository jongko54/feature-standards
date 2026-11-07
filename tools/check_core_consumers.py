#!/usr/bin/env python3
"""Run the real HTTP composition tests for the selected backend consumers."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STACKS = ("python", "go", "java", "rust")


def run(argv, *, cwd=ROOT, env=None):
    subprocess.run(list(map(str, argv)), cwd=cwd, env=env, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack", choices=(*STACKS, "all"), default="all")
    args = parser.parse_args()
    for stack in STACKS if args.stack == "all" else (args.stack,):
        print(f"Real HTTP core consumer: {stack}", flush=True)
        if stack == "python":
            run(
                [
                    "uv",
                    "run",
                    "--frozen",
                    "--project",
                    "examples/core-python",
                    "python",
                    "tests/core_consumer_conformance.py",
                ]
            )
        elif stack == "go":
            run(["go", "test", "-race", "./..."], cwd=ROOT / "examples/core-go")
            run(["go", "vet", "./..."], cwd=ROOT / "examples/core-go")
        elif stack == "java":
            with tempfile.TemporaryDirectory(prefix="core-http-maven-") as temporary:
                maven = [
                    ROOT / "implementations/java-spring/mvnw",
                    "-q",
                    f"-Dmaven.repo.local={temporary}/repository",
                ]
                for project in ("implementations/java-spring", "libraries/java"):
                    run(
                        [
                            *maven,
                            "-f",
                            ROOT / project / "pom.xml",
                            "-DskipTests",
                            "install",
                        ]
                    )
                run([*maven, "-f", ROOT / "examples/core-java/pom.xml", "test"])
        else:
            env = os.environ.copy()
            env.setdefault("CARGO_TARGET_DIR", str(ROOT / "examples/core-rust/target"))
            run(
                [
                    "cargo",
                    "test",
                    "--locked",
                    "--manifest-path",
                    ROOT / "examples/core-rust/Cargo.toml",
                ],
                env=env,
            )
            run(
                [
                    "cargo",
                    "fmt",
                    "--manifest-path",
                    ROOT / "examples/core-rust/Cargo.toml",
                    "--",
                    "--check",
                ],
                env=env,
            )
            run(
                [
                    "cargo",
                    "clippy",
                    "--locked",
                    "--manifest-path",
                    ROOT / "examples/core-rust/Cargo.toml",
                    "--all-targets",
                    "--",
                    "-D",
                    "warnings",
                ],
                env=env,
            )
    print(
        "Requested HTTP consumer tests passed; browser UI, DB profile and AI efficiency are separate checks."
    )


if __name__ == "__main__":
    main()
