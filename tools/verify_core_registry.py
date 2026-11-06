#!/usr/bin/env python3
"""Verify a public core release and fresh registry consumer. Never publishes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from check_core_distributions import JAVA_SMOKE, NODE_SMOKE, PYTHON_SMOKE

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.1.0"

RUST_SMOKE = """
use feature_standards_core::{authorization::{Grant,Policy,Principal,Resource},listing::{Schema,parse_query,page}};
use std::collections::BTreeMap;
fn main(){
 let policy=Policy::new(vec![Grant{role:"viewer".into(),permission:"documents:read".into(),scope:"owner".into()}]).unwrap();
 let principal=Principal{subject_id:"u1".into(),tenant_id:"t1".into(),roles:vec!["viewer".into()]};
 assert!(policy.decide(Some(&principal),"documents:read",&Resource{tenant_id:"t1".into(),owner_id:Some("u1".into())}).allowed);
 assert!(!policy.decide(Some(&principal),"documents:read",&Resource{tenant_id:"t2".into(),owner_id:Some("u1".into())}).allowed);
 let schema=Schema::new(BTreeMap::from([("id".into(),"string".into()),("score".into(),"integer".into())]),BTreeMap::new()).unwrap();
 let rows=vec![serde_json::json!({"id":"b","score":2}),serde_json::json!({"id":"a","score":2})];
 let result=page(&rows,&parse_query("sort=-score&limit=1",&schema).unwrap(),&schema).unwrap();
 assert_eq!(result["items"][0]["id"],"a");assert_eq!(result["total"],2);assert_eq!(result["nextOffset"],1);
 println!("Fresh crates.io public API consumer passed");
}
"""

GO_SMOKE = """
package main
import (
 "fmt"
 a "github.com/jongko54/feature-standards/libraries/go/authorization"
 l "github.com/jongko54/feature-standards/libraries/go/listing"
)
func main(){
 p,err:=a.NewPolicy([]a.Grant{{Role:"viewer",Permission:"documents:read",Scope:"owner"}});if err!=nil{panic(err)}
 owner:="u1";principal:=&a.Principal{SubjectID:owner,TenantID:"t1",Roles:[]string{"viewer"}}
 if !p.Decide(principal,"documents:read",a.Resource{TenantID:"t1",OwnerID:&owner}).Allowed{panic("owner allow")}
 if p.Decide(principal,"documents:read",a.Resource{TenantID:"t2",OwnerID:&owner}).Allowed{panic("tenant deny")}
 s,err:=l.NewSchema(map[string]string{"id":"string","score":"integer"},map[string]string{});if err!=nil{panic(err)}
 q,err:=l.ParseQuery("sort=-score&limit=1",s);if err!=nil{panic(err)}
 page,err:=l.Page([]map[string]any{{"id":"b","score":2},{"id":"a","score":2}},q,s);if err!=nil{panic(err)}
 if page.Items[0]["id"]!="a"||page.Total!=2||page.NextOffset==nil||*page.NextOffset!=1{panic("page")}
 fmt.Println("Fresh public Go module consumer passed")
}
"""


def get(url):
    if not url.startswith("https://"):
        raise ValueError("Public registry downloads require HTTPS")
    deadline = time.monotonic() + 240
    while True:
        try:
            with urlopen(
                Request(
                    url,
                    headers={
                        "User-Agent": "feature-standards-release/0.1 (https://github.com/jongko54/feature-standards)"
                    },
                ),
                timeout=20,
            ) as response:
                return response.read()
        except HTTPError as error:
            if (
                error.code not in (404, 429, 500, 502, 503, 504)
                or time.monotonic() >= deadline
            ):
                raise
            print(
                f"Waiting for public registry availability (HTTP {error.code})",
                flush=True,
            )
            time.sleep(5)


def run(argv, *, cwd, env, capture=False):
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
        "--target", choices=("python", "react", "rust", "java", "go"), required=True
    )
    parser.add_argument("--source-commit", required=True)
    parser.add_argument(
        "--expected-file",
        type=Path,
        help="Reviewed exact-source CI archive; required except for Go",
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-f0-9]{40}", args.source_commit):
        parser.error("Expected the exact reviewed source commit")
    if args.target != "go" and args.expected_file is None:
        parser.error("Reviewed artifact is required")
    if args.expected_file is not None:
        kind = "npm" if args.target == "react" else args.target
        check_name = f"checks-{kind}.json"
        check_file = args.expected_file.parent / check_name
        if not check_file.exists():
            check_file = args.expected_file.parent.parent / check_name
        checks = json.loads(check_file.read_text())
        assert (
            checks["sourceCommit"] == args.source_commit
            and checks["sourceDirty"] is False
        )
        local_sha = hashlib.sha256(args.expected_file.read_bytes()).hexdigest()
        assert any(
            entry["filename"] == args.expected_file.name
            and entry["sha256"] == local_sha
            for entry in checks["artifacts"]
        )
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
                "CARGO_",
                "GITHUB_",
                "GH_",
                "PYTHONPATH",
                "PYTHONHOME",
                "GOPROXY",
                "GOMODCACHE",
                "GOCACHE",
                "GOPRIVATE",
                "GONOSUMDB",
                "GONOPROXY",
                "GOSUMDB",
                "MAVEN_",
            )
        )
    }
    metadata_urls = {
        "python": f"https://pypi.org/pypi/feature-standards-core/{VERSION}/json",
        "react": f"https://registry.npmjs.org/@ugauga%2ffeature-standards-core/{VERSION}",
        "rust": f"https://crates.io/api/v1/crates/feature-standards-core/{VERSION}",
        "java": f"https://repo.maven.apache.org/maven2/io/github/jongko54/feature-standards-core/{VERSION}/feature-standards-core-{VERSION}.pom",
        "go": f"https://proxy.golang.org/github.com/jongko54/feature-standards/libraries/go/@v/v{VERSION}.info",
    }
    metadata_url = metadata_urls[args.target]
    metadata = get(metadata_url)
    value = None if args.target == "java" else json.loads(metadata)
    names = {
        "python": "feature-standards-core",
        "react": "@ugauga/feature-standards-core",
        "rust": "feature-standards-core",
        "java": f"io.github.jongko54:feature-standards-core:{VERSION}",
        "go": "github.com/jongko54/feature-standards/libraries/go",
    }
    if args.target == "python":
        assert value["info"]["version"] == VERSION
        artifact_info = next(
            file for file in value["urls"] if file["filename"].endswith(".whl")
        )
        artifact_url = artifact_info["url"]
    elif args.target == "react":
        assert value["name"] == names["react"] and value["version"] == VERSION
        artifact_url = value["dist"]["tarball"]
    elif args.target == "rust":
        assert value["version"]["num"] == VERSION
        artifact_url = f"https://static.crates.io/crates/feature-standards-core/feature-standards-core-{VERSION}.crate"
    elif args.target == "java":
        artifact_url = metadata_url.replace(".pom", ".jar")
    else:
        assert value["Version"] == "v" + VERSION
        assert value.get("Origin", {}).get("Hash") == args.source_commit, (
            "Go proxy resolved another source commit"
        )
        artifact_url = metadata_url.replace(".info", ".zip")
    archive = get(artifact_url)
    checksum = hashlib.sha256(archive).hexdigest()
    if args.expected_file is not None:
        assert archive == args.expected_file.read_bytes(), (
            "Public artifact differs from reviewed CI archive"
        )
    if args.target == "python":
        assert checksum == artifact_info["digests"]["sha256"]
    if args.target == "rust":
        assert checksum == value["version"]["checksum"]
    with tempfile.TemporaryDirectory(
        prefix=f"feature-standards-{args.target}-registry-"
    ) as folder:
        temporary = Path(folder)
        if args.target == "python":
            run(["uv", "venv", temporary / "venv"], cwd=temporary, env=env)
            python = temporary / "venv/bin/python"
            run(
                [
                    "uv",
                    "pip",
                    "install",
                    "--python",
                    python,
                    "--index-url",
                    "https://pypi.org/simple",
                    f"feature-standards-core=={VERSION}",
                ],
                cwd=temporary,
                env=env,
            )
            run([python, "-c", PYTHON_SMOKE, ROOT], cwd=temporary, env=env)
            run(
                [
                    python,
                    "-c",
                    "from importlib.metadata import distribution; assert distribution('feature-standards-core').read_text('direct_url.json') is None",
                ],
                cwd=temporary,
                env=env,
            )
        elif args.target == "react":
            (temporary / "package.json").write_text(
                '{"private":true,"type":"module"}\n'
            )
            (temporary / "empty.npmrc").write_text("")
            (temporary / "empty-global.npmrc").write_text("")
            env.update(
                NPM_CONFIG_USERCONFIG=str(temporary / "empty.npmrc"),
                NPM_CONFIG_GLOBALCONFIG=str(temporary / "empty-global.npmrc"),
                NPM_CONFIG_CACHE=str(temporary / "cache"),
            )
            run(
                [
                    "npm",
                    "install",
                    "--ignore-scripts",
                    "--no-audit",
                    "--no-fund",
                    "--registry",
                    "https://registry.npmjs.org/",
                    f"@ugauga/feature-standards-core@{VERSION}",
                ],
                cwd=temporary,
                env=env,
            )
            (temporary / "consumer.mjs").write_text(NODE_SMOKE)
            run(["node", "consumer.mjs", ROOT], cwd=temporary, env=env)
        elif args.target == "rust":
            (temporary / "src").mkdir()
            (temporary / "Cargo.toml").write_text(
                f'[package]\nname="core-registry-consumer"\nversion="0.1.0"\nedition="2024"\n[dependencies]\nfeature-standards-core="={VERSION}"\nserde_json="1.0"\n'
            )
            (temporary / "src/main.rs").write_text(RUST_SMOKE)
            env.update(
                CARGO_HOME=str(temporary / "cargo-home"),
                CARGO_TARGET_DIR=str(temporary / "target"),
            )
            run(["cargo", "run", "--quiet"], cwd=temporary, env=env)
            package = next(
                (temporary / "cargo-home/registry/src").glob(
                    f"*/feature-standards-core-{VERSION}"
                )
            )
            run(
                [
                    "cargo",
                    "test",
                    "--locked",
                    "--manifest-path",
                    package / "Cargo.toml",
                ],
                cwd=temporary,
                env=env,
            )
        elif args.target == "java":
            env["MAVEN_SKIP_RC"] = "true"
            (temporary / "settings.xml").write_text(
                '<settings xmlns="http://maven.apache.org/SETTINGS/1.2.0"/>'
            )
            sources = temporary / "src/main/java"
            sources.mkdir(parents=True)
            (sources / "Consumer.java").write_text(JAVA_SMOKE)
            (temporary / "pom.xml").write_text(
                f'<project xmlns="http://maven.apache.org/POM/4.0.0"><modelVersion>4.0.0</modelVersion><groupId>example</groupId><artifactId>core-consumer</artifactId><version>1.0.0</version><properties><maven.compiler.release>21</maven.compiler.release></properties><dependencies><dependency><groupId>io.github.jongko54</groupId><artifactId>feature-standards-core</artifactId><version>{VERSION}</version></dependency></dependencies><build><plugins><plugin><groupId>org.apache.maven.plugins</groupId><artifactId>maven-compiler-plugin</artifactId><version>3.14.1</version></plugin></plugins></build></project>'
            )
            run(
                [
                    ROOT / "implementations/java-spring/mvnw",
                    "-q",
                    "-s",
                    temporary / "settings.xml",
                    "-gs",
                    temporary / "settings.xml",
                    f"-Dmaven.repo.local={temporary}/repository",
                    "package",
                ],
                cwd=temporary,
                env=env,
            )
            dependency = (
                temporary
                / f"repository/io/github/jongko54/feature-standards-core/{VERSION}/feature-standards-core-{VERSION}.jar"
            )
            assert dependency.read_bytes() == archive
            java = (
                Path(env["JAVA_HOME"]) / "bin/java" if env.get("JAVA_HOME") else "java"
            )
            run(
                [
                    java,
                    "-cp",
                    os.pathsep.join(
                        [str(temporary / "target/classes"), str(dependency)]
                    ),
                    "Consumer",
                ],
                cwd=temporary,
                env=env,
            )
        else:
            (temporary / "go.mod").write_text(
                f"module example.com/core-consumer\n\ngo 1.26\n\nrequire github.com/jongko54/feature-standards/libraries/go v{VERSION}\n"
            )
            (temporary / "main.go").write_text(GO_SMOKE)
            env.update(
                GOPROXY="https://proxy.golang.org",
                GOSUMDB="sum.golang.org",
                GOPRIVATE="",
                GONOSUMDB="",
                GONOPROXY="",
                GOMODCACHE=str(temporary / "modules"),
                GOCACHE=str(temporary / "cache"),
            )
            run(["go", "mod", "tidy"], cwd=temporary, env=env)
            run(["go", "run", "."], cwd=temporary, env=env)
            downloaded = json.loads(
                run(
                    ["go", "mod", "download", "-json", f"{names['go']}@v{VERSION}"],
                    cwd=temporary,
                    env=env,
                    capture=True,
                ).stdout
            )
            assert (
                hashlib.sha256(Path(downloaded["Zip"]).read_bytes()).hexdigest()
                == checksum
            )
            run(["go", "test", "./..."], cwd=Path(downloaded["Dir"]), env=env)
    record = {
        "name": names[args.target],
        "version": VERSION,
        "sourceCommit": args.source_commit,
        "observedAt": datetime.now(UTC).isoformat(),
        "metadataUrl": metadata_url,
        "artifactUrl": artifact_url,
        "artifactSha256": checksum,
        "registryVerified": True,
        "publicDownloadVerified": True,
        "freshConsumerVerified": True,
    }
    if args.expected_file is not None:
        record["matchesReviewedArtifact"] = True
    else:
        record["versionedTagAndSourceVerified"] = True
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
