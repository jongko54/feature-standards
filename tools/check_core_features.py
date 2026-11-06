#!/usr/bin/env python3
"""Run real native feature/vector tests from a source checkout (never auth init)."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STACKS = ("python", "go", "java", "rust", "react")
FEATURES = ("authorization", "listing")


def command(stack, feature):
    env = os.environ.copy()
    cwd = ROOT
    if stack == "python":
        env["PYTHONPATH"] = str(ROOT / "libraries/python") + os.pathsep + env.get("PYTHONPATH", "")
        pattern = "test_*.py" if feature == "all" else f"test_{feature}.py"
        argv = [sys.executable, "-m", "unittest", "discover", "-s", "libraries/python/tests", "-p", pattern, "-v"]
    elif stack == "go":
        cwd = ROOT / "libraries/go"
        argv = ["go", "test", "-race", "./..." if feature == "all" else f"./{feature}"]
    elif stack == "java":
        argv = [str(ROOT / "implementations/java-spring/mvnw"), "-q", "-f", "libraries/java/pom.xml"]
        if feature != "all":
            argv.append(f"-Dtest=*{'Authorization' if feature == 'authorization' else 'Listing'}*")
        argv.append("test")
    elif stack == "rust":
        argv = ["cargo", "test", "--locked", "--manifest-path", "libraries/rust/Cargo.toml"]
        if feature != "all":
            argv.append(f"{feature}::")
    else:
        files = [ROOT / f"libraries/typescript/test/{f}.test.mjs" for f in FEATURES if feature in ("all", f)]
        argv = ["node", "--test", *map(str, files)]
    return argv, cwd, env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feature", choices=(*FEATURES, "all"), default="all")
    parser.add_argument("--stack", choices=(*STACKS, "all"), default="all")
    args = parser.parse_args()
    for stack in STACKS if args.stack == "all" else (args.stack,):
        argv, cwd, env = command(stack, args.feature)
        print(f"Core {args.feature} / {stack}", flush=True)
        subprocess.run(argv, cwd=cwd, env=env, check=True)
    print("Requested native core checks passed; HTTP, browser and registry evidence is separate.")


if __name__ == "__main__":
    main()
