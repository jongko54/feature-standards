"""Resolved Maven inventories fail closed without guessing or hiding packages."""

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from security_maven import (
    MAVEN_POMS,
    MavenInventoryError,
    create_inventory,
    dependency_bom,
    execute,
    maven_coverage,
    maven_environment,
    plugin_goal,
)


class ResolvedMavenTests(unittest.TestCase):
    def tree(self):
        return {
            "groupId": "example",
            "artifactId": "consumer",
            "version": "1.0.0",
            "type": "jar",
            "scope": "",
            "classifier": "",
            "children": [
                {
                    "groupId": "io.github.jongko54",
                    "artifactId": "java-spring-auth",
                    "version": "2.0.0",
                    "type": "jar",
                    "scope": "compile",
                    "classifier": "library",
                },
                {
                    "groupId": "org.example",
                    "artifactId": "test-helper",
                    "version": "4.0.0",
                    "type": "jar",
                    "scope": "test",
                    "children": [
                        {
                            "groupId": "org.example",
                            "artifactId": "transitive",
                            "version": "5.0.0",
                            "type": "jar",
                            "scope": "test",
                        }
                    ],
                },
                {
                    "groupId": "org.example",
                    "artifactId": "provided",
                    "version": "6.0.0",
                    "type": "jar",
                    "scope": "provided",
                },
            ],
        }

    def bom(self, tree):
        return dependency_bom(tree, ("example", "consumer", "1.0.0"))

    def test_source_candidate_classifier_and_transitive_tests_are_included(self):
        bom = self.bom(self.tree())
        self.assertEqual(len(bom["components"]), 4)
        source = next(
            row for row in bom["components"] if row["name"] == "java-spring-auth"
        )
        self.assertEqual(
            source["purl"],
            "pkg:maven/io.github.jongko54/java-spring-auth@2.0.0?classifier=library&type=jar",
        )
        transitive = next(
            row for row in bom["components"] if row["name"] == "transitive"
        )
        self.assertIn(
            {"name": "feature-standards:maven-scope", "value": "test"},
            transitive["properties"],
        )
        self.assertEqual(bom["metadata"]["component"]["version"], "1.0.0")
        self.assertEqual(len(bom["dependencies"]), 5)

    def test_unresolved_or_malformed_dependency_nodes_cannot_pass(self):
        for field, value in [
            ("version", "${unresolved}"),
            ("version", "[1.0,2.0)"),
            ("version", "LATEST"),
            ("version", "1.0-SNAPSHOT"),
            ("groupId", "outside/../../path"),
            ("scope", "unknown"),
            ("children", "not-a-list"),
            ("version", None),
        ]:
            with self.subTest(field=field, value=value):
                tree = self.tree()
                tree["children"][0][field] = value
                with self.assertRaises(MavenInventoryError):
                    self.bom(tree)

    def test_missing_identity_wrong_project_or_empty_tree_is_rejected(self):
        for tree in [
            {},
            {**self.tree(), "version": "9.9.9"},
            {**self.tree(), "children": []},
        ]:
            with self.assertRaises(MavenInventoryError):
                self.bom(tree)

    def test_duplicate_components_preserve_all_resolved_scopes(self):
        tree = self.tree()
        duplicate = copy.deepcopy(tree["children"][2])
        duplicate["scope"] = "runtime"
        tree["children"].append(duplicate)
        bom = self.bom(tree)
        self.assertEqual(len(bom["components"]), 4)
        provided = next(row for row in bom["components"] if row["name"] == "provided")
        self.assertEqual(
            {p["value"] for p in provided["properties"]}, {"provided", "runtime"}
        )

    def test_plugin_must_be_an_exact_official_coordinate_and_stable_pin(self):
        valid = {
            "coordinate": "org.apache.maven.plugins:maven-dependency-plugin",
            "version": "3.11.0",
        }
        self.assertEqual(
            plugin_goal(valid),
            "org.apache.maven.plugins:maven-dependency-plugin:3.11.0:tree",
        )
        for config in [
            {**valid, "coordinate": "untrusted:plugin"},
            {**valid, "version": "LATEST"},
            {**valid, "version": "[3.7,4.0)"},
        ]:
            with self.assertRaises(MavenInventoryError):
                plugin_goal(config)

    def test_no_application_publisher_or_jvm_injection_settings_are_inherited(self):
        env = maven_environment(
            Path("/private/work"),
            {
                "HOME": "/real/home",
                "PATH": "/bin",
                "JAVA_HOME": "/jdk",
                "GH_TOKEN": "private",
                "MVNW_PASSWORD": "private",
                "MAVEN_OPTS": "private",
                "JDK_JAVA_OPTIONS": "private",
                "AUTH_DATABASE_URL": "private",
                "MAVEN_USER_HOME": "/shared/cache",
            },
        )
        self.assertEqual(env["HOME"], "/real/home")
        self.assertEqual(env["JAVA_HOME"], "/jdk")
        self.assertEqual(env["MAVEN_USER_HOME"], "/private/work/maven-user")
        self.assertEqual(env["MAVEN_SKIP_RC"], "true")
        self.assertNotIn("private", env.values())

    def test_missing_executable_returns_sanitized_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            with self.assertRaisesRegex(
                MavenInventoryError, "^maven-resolution-failed$"
            ):
                execute(
                    [
                        str(work / "nonexistent-private-executable"),
                        "private-account-value",
                    ],
                    work,
                    {},
                    work / "private.log",
                )

    def test_missing_project_and_existing_or_source_workspace_are_rejected(self):
        plugin = {
            "coordinate": "org.apache.maven.plugins:maven-dependency-plugin",
            "version": "3.11.0",
        }
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "source"
            root.mkdir()
            with self.assertRaisesRegex(MavenInventoryError, "coverage-mismatch"):
                create_inventory(root, list(MAVEN_POMS[:-1]), [], base / "new", plugin)
            for work in [root / "unsafe", base]:
                with self.assertRaisesRegex(
                    MavenInventoryError, "workspace-must-be-new"
                ):
                    create_inventory(root, list(MAVEN_POMS), [], work, plugin)

    def test_source_path_escape_is_rejected(self):
        plugin = {
            "coordinate": "org.apache.maven.plugins:maven-dependency-plugin",
            "version": "3.11.0",
        }
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "source"
            root.mkdir()
            for index, path in enumerate(["../outside", "/absolute/pom.xml"]):
                with self.assertRaisesRegex(
                    MavenInventoryError, "unsafe-maven-source-path"
                ):
                    create_inventory(
                        root, list(MAVEN_POMS), [path], base / f"new-{index}", plugin
                    )

    def test_scanner_must_report_every_resolved_maven_identity_per_project(self):
        projects = [
            {
                "sourcePom": pom,
                "resolvedPackages": [
                    {"name": "example:library", "version": "1.0.0"},
                    {"name": "example:transitive-test", "version": "2.0.0"},
                ],
            }
            for pom in MAVEN_POMS
        ]
        inventory = [
            {**row, "source": project["sourcePom"], "ecosystem": "Maven"}
            for project in projects
            for row in project["resolvedPackages"]
        ]
        self.assertEqual(maven_coverage(inventory, projects)["status"], "passed")
        self.assertEqual(maven_coverage(inventory[:-1], projects)["status"], "error")
        changed = copy.deepcopy(inventory)
        changed[0]["version"] = "9.9.9"
        self.assertEqual(maven_coverage(changed, projects)["status"], "error")
        changed[0]["version"] = "1.0.0"
        changed[0]["ecosystem"] = "npm"
        self.assertEqual(maven_coverage(changed, projects)["status"], "error")
        with self.assertRaises(MavenInventoryError):
            maven_coverage(inventory, projects[:-1])

    def fixture_sources(self, root):
        files = []
        for pom in MAVEN_POMS:
            path = root / pom
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                '<project xmlns="http://maven.apache.org/POM/4.0.0"><groupId>example</groupId><artifactId>consumer</artifactId><version>1.0.0</version></project>'
            )
            files.append(pom)
        wrapper = "implementations/java-spring/mvnw"
        (root / wrapper).write_text("synthetic wrapper")
        return [*files, wrapper]

    def fake_maven(self, argv, cwd, env, log, *, tree=True):
        if "install" in argv:
            pom = Path(argv[argv.index("-f") + 1])
            index = list(MAVEN_POMS[:2]).index(pom.relative_to(cwd).as_posix())
            filename = (
                "consumer-1.0.0-library.jar" if index == 0 else "consumer-1.0.0.jar"
            )
            built = (
                pom.parent
                / "target"
                / ("auth-server-library.jar" if index == 0 else filename)
            )
            installed = (
                Path(env["MAVEN_USER_HOME"]).parent
                / "m2/example/consumer/1.0.0"
                / filename
            )
            for target in [built, installed]:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"synthetic built artifact")
        elif tree:
            output = next(
                value.split("=", 1)[1]
                for value in argv
                if value.startswith("-DoutputFile=")
            )
            Path(output).write_text(json.dumps(self.tree()))

    def test_generated_paths_and_aliases_use_the_same_canonical_private_path(self):
        plugin = {
            "coordinate": "org.apache.maven.plugins:maven-dependency-plugin",
            "version": "3.11.0",
        }
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "source"
            root.mkdir()
            files = self.fixture_sources(root)
            private = base / "private"
            private.mkdir()
            link = base / "alias"
            link.symlink_to(private, target_is_directory=True)
            work = link / "fresh"
            with patch("security_maven.execute", side_effect=self.fake_maven):
                sboms, aliases, evidence = create_inventory(
                    root, list(MAVEN_POMS), files, work, plugin
                )
            self.assertEqual(set(aliases), {str(path) for path in sboms})
            self.assertTrue(all(path == path.resolve() for path in sboms))
            self.assertTrue(all(path.is_file() for path in sboms))
            self.assertEqual(set(evidence["sourceInputHashes"]), set(files))
            self.assertEqual(len(evidence["localSourceArtifacts"]), 2)

    def test_failed_or_missing_tree_output_is_never_accepted(self):
        plugin = {
            "coordinate": "org.apache.maven.plugins:maven-dependency-plugin",
            "version": "3.11.0",
        }
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "source"
            root.mkdir()
            files = self.fixture_sources(root)
            with (
                patch(
                    "security_maven.execute",
                    side_effect=MavenInventoryError("maven-resolution-failed"),
                ),
                self.assertRaisesRegex(MavenInventoryError, "maven-resolution-failed"),
            ):
                create_inventory(root, list(MAVEN_POMS), files, base / "failed", plugin)
            with (
                patch(
                    "security_maven.execute",
                    side_effect=lambda *args: self.fake_maven(*args, tree=False),
                ),
                self.assertRaisesRegex(
                    MavenInventoryError, "invalid-maven-resolution-output"
                ),
            ):
                create_inventory(
                    root, list(MAVEN_POMS), files, base / "missing", plugin
                )


if __name__ == "__main__":
    unittest.main()
