#!/usr/bin/env python3
"""Build core archives and exercise their public APIs outside the checkout. No uploads."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from release_metadata import metadata

ROOT = Path(__file__).resolve().parents[1]

PYTHON_SMOKE = """
from feature_standards import Grant, Policy, Principal, Resource, ListingSchema, parse_query, page
from feature_standards import __file__ as module_path
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
assert not pathlib.Path(module_path).is_relative_to(root)
for case in json.loads((root/'features/authorization/scenarios.json').read_text())['cases']:
    try:
        policy = Policy([Grant(**g) for g in case['grants']])
        p=case['principal']; r=case['resource']
        result=policy.decide(None if p is None else Principal(p['subjectId'],p['tenantId'],p['roles']),case['permission'],Resource(r['tenantId'],r.get('ownerId')))
        actual={'allowed':result.allowed,'code':result.code}
    except ValueError as exc:
        actual={'error':exc.code}
    assert actual==case['expected'],case['id']
for case in json.loads((root/'features/listing/scenarios.json').read_text())['cases']:
    try:
        s=case['schema']; schema=ListingSchema(s['sortFields'],s['filterFields'])
        actual=page(case['items'],parse_query(case['query'],schema),schema)
    except ValueError as exc:
        actual={'error':exc.code}
    assert actual==case['expected'],case['id']
print('Installed Python wheel: 76 vectors passed')
"""

NODE_SMOKE = """
import {Grant,Policy,Principal,Resource,createListingSchema,parseListQuery,listPage} from '@ugauga/feature-standards-core';
import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const root=process.argv[2];
for(const c of JSON.parse(readFileSync(`${root}/features/authorization/scenarios.json`)).cases){
 let actual;
 try {const policy=new Policy(c.grants.map(g=>new Grant(g.role,g.permission,g.scope)));const p=c.principal,r=c.resource;
 actual=policy.decide(p===null?null:new Principal(p.subjectId,p.tenantId,p.roles),c.permission,new Resource(r.tenantId,r.ownerId));}
 catch(error){actual={error:error.code};}
 assert.deepEqual(actual,c.expected,c.id);
}
for(const c of JSON.parse(readFileSync(`${root}/features/listing/scenarios.json`)).cases){
 let actual;try{const schema=createListingSchema(c.schema);actual=listPage(c.items,parseListQuery(c.query,schema),schema);}
 catch(error){actual={error:error.code};}
 assert.deepEqual(actual,c.expected,c.id);
}
console.log('Installed npm tarball: 76 vectors passed');
"""

JAVA_SMOKE = """
import dev.featurestandards.core.authorization.*;
import dev.featurestandards.core.listing.Listing;
import java.util.*;
class Consumer {
 public static void main(String[] args) {
  var policy=new AuthorizationPolicy(List.of(new Grant("viewer","documents:read","owner")));
  var principal=new Principal("u1","t1",List.of("viewer"));
  if(!policy.decide(principal,"documents:read",new Resource("t1","u1")).allowed())throw new AssertionError();
  if(policy.decide(principal,"documents:read",new Resource("t2","u1")).allowed())throw new AssertionError();
  var schema=new Listing.Schema(Map.of("id","string","score","integer"),Map.of());
  List<Map<String,Object>> rows=List.of(Map.of("id","b","score",2),Map.of("id","a","score",2));
  var result=Listing.page(rows,Listing.parseQuery("sort=-score&limit=1",schema),schema);
  if(!result.items().getFirst().get("id").equals("a")||result.total()!=2||result.nextOffset()!=1)throw new AssertionError();
  System.out.println("Independent plain Java JAR consumer passed");
 }
}
"""


def run(argv, *, cwd=ROOT, env=None, capture=False):
    return subprocess.run(
        list(map(str, argv)),
        cwd=cwd,
        env=env,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        choices=("python", "npm", "rust", "java", "go", "all"),
        default="all",
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Local build preflight only; cannot serve as a clean release receipt",
    )
    args = parser.parse_args()
    dirty = bool(run(["git", "status", "--porcelain"], capture=True).stdout.strip())
    if dirty and not args.allow_dirty:
        raise ValueError(
            "Clean source is required; --allow-dirty is only a local preflight"
        )
    source_commit = run(["git", "rev-parse", "HEAD"], capture=True).stdout.strip()
    output = args.out_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    targets = (
        ("python", "npm", "rust", "java", "go")
        if args.target == "all"
        else (args.target,)
    )
    # Consumers intentionally have no inherited publisher or runtime credentials.
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(
            (
                "AUTH_",
                "NPM_",
                "NODE_AUTH_",
                "TWINE_",
                "PYPI_",
                "CARGO_REGISTRY_",
                "GITHUB_",
                "GH_",
                "PYTHONPATH",
                "PYTHONHOME",
            )
        )
    }
    artifacts = []
    with tempfile.TemporaryDirectory(
        prefix="feature-standards-core-consumer-"
    ) as folder:
        temporary = Path(folder)
        if "python" in targets:
            run(
                [
                    "uv",
                    "build",
                    "--project",
                    "libraries/python",
                    "--out-dir",
                    output / "python",
                ]
            )
            details = metadata("python-core")
            stem = details["name"].replace("-", "_") + "-" + details["version"]
            wheel = output / "python" / f"{stem}-py3-none-any.whl"
            artifacts.extend([wheel, output / "python" / f"{stem}.tar.gz"])
            run(["uv", "venv", temporary / "venv"], env=env)
            python = temporary / "venv/bin/python"
            run(
                ["uv", "pip", "install", "--python", python, "--no-index", wheel],
                cwd=temporary,
                env=env,
            )
            run([python, "-c", PYTHON_SMOKE, ROOT], cwd=temporary, env=env)
            if (
                ROOT / "libraries/python/feature_standards/postgres_listing.py"
            ).exists():
                run(
                    [
                        python,
                        "-c",
                        "import importlib.util; from feature_standards.listing import ListingSchema; from feature_standards.postgres_listing import PostgresListing, VisibilityScope; assert importlib.util.find_spec('psycopg') is None; PostgresListing(schema=ListingSchema({'id':'string'}, {}), table=('public','documents'), columns={'id':'id'}, tenant_column='tenant_id', owner_column='owner_id'); VisibilityScope('tenant-a', 'user-1'); print('Installed optional PostgreSQL API configures without the driver')",
                    ],
                    cwd=temporary,
                    env=env,
                )
        if "npm" in targets:
            records = json.loads(
                run(
                    ["npm", "pack", "--pack-destination", output, "--json"],
                    cwd=ROOT / "libraries/typescript",
                    capture=True,
                ).stdout
            )
            archive = output / records[0]["filename"]
            artifacts.append(archive)
            project = temporary / "node"
            project.mkdir()
            (project / "package.json").write_text('{"private":true,"type":"module"}\n')
            run(
                [
                    "npm",
                    "install",
                    "--ignore-scripts",
                    "--no-audit",
                    "--no-fund",
                    archive,
                ],
                cwd=project,
                env=env,
            )
            (project / "consumer.mjs").write_text(NODE_SMOKE)
            run(["node", "consumer.mjs", ROOT], cwd=project, env=env)
        if "rust" in targets:
            package_env = os.environ.copy()
            package_env["CARGO_TARGET_DIR"] = str(temporary / "rust-package-target")
            argv = [
                "cargo",
                "package",
                "--locked",
                "--registry",
                "crates-io",
                "--manifest-path",
                "libraries/rust/Cargo.toml",
            ]
            if args.allow_dirty:
                argv.append("--allow-dirty")
            run(argv, env=package_env)
            details = metadata("rust-core")
            stem = details["name"] + "-" + details["version"]
            archive = temporary / f"rust-package-target/package/{stem}.crate"
            destination = output / archive.name
            shutil.copyfile(archive, destination)
            # A stale shorter archive must not retain bytes from an earlier build.
            gzip.decompress(destination.read_bytes())
            artifacts.append(destination)
            extracted = temporary / "rust"
            extracted.mkdir()
            shutil.unpack_archive(str(destination), str(extracted), "gztar")
            manifest = extracted / stem / "Cargo.toml"
            run(
                ["cargo", "test", "--locked", "--manifest-path", manifest],
                cwd=temporary,
                env=env,
            )
        if "java" in targets:
            run(
                [
                    ROOT / "implementations/java-spring/mvnw",
                    "-q",
                    "-f",
                    "libraries/java/pom.xml",
                    "package",
                ]
            )
            details = metadata("java-core")
            stem = details["name"].split(":")[1] + "-" + details["version"]
            jar = ROOT / f"libraries/java/target/{stem}.jar"
            with zipfile.ZipFile(jar) as content:
                assert "META-INF/LICENSE" in content.namelist()
                assert not any(
                    name.startswith("BOOT-INF/") for name in content.namelist()
                )
            for artifact in (
                jar,
                jar.with_name(f"{stem}-sources.jar"),
                jar.with_name(f"{stem}-javadoc.jar"),
            ):
                destination = output / artifact.name
                shutil.copyfile(artifact, destination)
                artifacts.append(destination)
            (temporary / "Consumer.java").write_text(JAVA_SMOKE)
            java = (
                Path(env["JAVA_HOME"]) / "bin/java" if env.get("JAVA_HOME") else "java"
            )
            run([java, "--class-path", jar, "Consumer.java"], cwd=temporary, env=env)
        if "go" in targets:
            project = temporary / "go"
            shutil.copytree(ROOT / "libraries/go", project)
            run(["go", "test", "-race", "./..."], cwd=project, env=env)
    record = {
        "schemaVersion": 1,
        "published": False,
        "sourceCommit": source_commit,
        "sourceDirty": dirty,
        "targets": list(targets),
        "artifacts": [
            {
                "filename": artifact.name,
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            }
            for artifact in artifacts
        ],
    }
    (output / f"checks-{args.target}.json").write_text(
        json.dumps(record, indent=2) + "\n"
    )
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
