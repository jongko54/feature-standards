"""Regressions for the local process harness, independent of auth servers."""

import contextlib
import io
import json
import socket
import subprocess
import unittest
from unittest.mock import Mock, patch

import conformance
from conformance import require_free_port


class PortProbeTests(unittest.TestCase):
    def test_detects_an_active_listener(self):
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            with self.assertRaises(RuntimeError):
                require_free_port(listener.getsockname()[1])

    def test_allows_a_port_after_its_server_closed(self):
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            listener.listen(1)
            with socket.create_connection(("127.0.0.1", port)) as client:
                accepted, _ = listener.accept()
                # The server closes first, leaving its endpoint in TIME_WAIT.
                accepted.close()
                self.assertEqual(client.recv(1), b"")
        require_free_port(port)


class BackendRunnerTests(unittest.TestCase):
    rust_binary = "/test/cargo-target/debug/feature-standards-auth"

    @contextlib.contextmanager
    def process_boundaries(self):
        """Keep the real runner orchestration while replacing processes and HTTP."""
        process = Mock(pid=1234567)
        process.poll.return_value = None
        process.wait.return_value = 0
        response = (200, {"set-cookie": "fs_session=test; Secure"}, b"{}")
        cargo_output = json.dumps(
            {
                "reason": "compiler-artifact",
                "target": {"name": "feature-standards-auth", "kind": ["bin"]},
                "executable": self.rust_binary,
            }
        )
        with (
            patch.dict(
                "conformance.os.environ",
                {"PATH": "/test/bin", "JAVA_HOME": "/test/jdk"},
                clear=True,
            ),
            patch(
                "conformance.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, stdout=cargo_output),
            ) as builds,
            patch("conformance.subprocess.Popen", return_value=process) as launches,
            patch("conformance.os.killpg"),
            patch("conformance.Client.request", return_value=response),
            patch("conformance.run_contract", return_value=True),
            patch("conformance.require_free_port"),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            yield builds, launches

    def run_cli(self, *arguments):
        with patch("sys.argv", ["conformance.py", *arguments]):
            return conformance.main()

    def auth_launches(self, launches):
        return [
            call
            for call in launches.call_args_list
            if call.kwargs["cwd"] != conformance.ROOT / "clients/react"
        ]

    def test_all_selects_each_backend_in_order(self):
        with self.process_boundaries() as (_, launches):
            self.assertEqual(self.run_cli("--backend", "all"), 0)
            self.assertEqual(
                [call.kwargs["cwd"].name for call in self.auth_launches(launches)],
                [
                    "python-fastapi",
                    "python-fastapi",
                    "go-net-http",
                    "go-net-http",
                    "java-spring",
                    "java-spring",
                    "rust-axum",
                    "rust-axum",
                ],
            )

    def test_individual_backend_build_and_start_commands(self):
        for backend, directory in [
            ("python", "python-fastapi"),
            ("go", "go-net-http"),
            ("java", "java-spring"),
            ("rust", "rust-axum"),
        ]:
            with (
                self.subTest(backend=backend),
                self.process_boundaries() as (builds, launches),
            ):
                self.assertEqual(self.run_cli("--backend", backend), 0)
                auth = self.auth_launches(launches)
                self.assertEqual(len(auth), 2)
                self.assertTrue(
                    all(
                        call.kwargs["cwd"]
                        == conformance.ROOT / "implementations" / directory
                        for call in auth
                    )
                )
                command = auth[0].args[0]
                if backend == "python":
                    builds.assert_not_called()
                    self.assertEqual(
                        command,
                        [
                            "uv",
                            "run",
                            "--frozen",
                            "uvicorn",
                            "app:app",
                            "--no-proxy-headers",
                            "--host",
                            "127.0.0.1",
                            "--port",
                            auth[0].kwargs["env"]["AUTH_PORT"],
                        ],
                    )
                else:
                    builds.assert_called_once()
                    build = builds.call_args
                    self.assertEqual(build.kwargs["cwd"], auth[0].kwargs["cwd"])
                    self.assertTrue(build.kwargs["check"])
                    if backend == "go":
                        self.assertEqual(build.args[0][:3], ["go", "build", "-o"])
                        self.assertEqual(build.args[0][-1], ".")
                        self.assertEqual(command, [build.args[0][3]])
                    elif backend == "java":
                        self.assertEqual(
                            build.args[0], ["./mvnw", "-q", "-DskipTests", "package"]
                        )
                        self.assertEqual(
                            command,
                            ["/test/jdk/bin/java", "-jar", "target/auth-server.jar"],
                        )
                    else:
                        self.assertEqual(
                            build.args[0],
                            [
                                "cargo",
                                "build",
                                "--locked",
                                "--bin",
                                "feature-standards-auth",
                                "--message-format=json-render-diagnostics",
                            ],
                        )
                        self.assertEqual(command, [self.rust_binary])

    def test_java_uses_path_when_java_home_is_absent(self):
        with self.process_boundaries() as (_, launches):
            with patch.dict(
                "conformance.os.environ", {"PATH": "/test/bin"}, clear=True
            ):
                self.assertEqual(self.run_cli("--backend", "java"), 0)
            self.assertEqual(
                self.auth_launches(launches)[0].args[0],
                ["java", "-jar", "target/auth-server.jar"],
            )

    def test_rust_executes_reported_artifact_with_external_cargo_configuration(self):
        executable = "/external/cargo-target/x86_64-unknown-linux-gnu/debug/feature-standards-auth"
        output = "\n".join(
            [
                json.dumps(
                    {
                        "reason": "compiler-artifact",
                        "target": {"name": "dependency", "kind": ["lib"]},
                        "executable": None,
                    }
                ),
                json.dumps(
                    {
                        "reason": "compiler-artifact",
                        "target": {"name": "another-binary", "kind": ["bin"]},
                        "executable": "/external/cargo-target/debug/another-binary",
                    }
                ),
                json.dumps(
                    {
                        "reason": "compiler-artifact",
                        "target": {"name": "feature-standards-auth", "kind": ["bin"]},
                        "executable": executable,
                    }
                ),
                json.dumps({"reason": "build-finished", "success": True}),
            ]
        )
        with self.process_boundaries() as (builds, launches):
            builds.return_value = subprocess.CompletedProcess([], 0, stdout=output)
            with patch.dict(
                "conformance.os.environ",
                {
                    "CARGO_TARGET_DIR": "/external/cargo-target",
                    "CARGO_BUILD_TARGET": "x86_64-unknown-linux-gnu",
                },
            ):
                self.assertEqual(self.run_cli("--backend", "rust", "--browser"), 0)
            self.assertEqual(
                [call.args[0] for call in self.auth_launches(launches)],
                [[executable], [executable], [executable]],
            )
            build = builds.call_args_list[0]
            self.assertIn("--message-format=json-render-diagnostics", build.args[0])
            self.assertEqual(build.kwargs["stdout"], subprocess.PIPE)
            self.assertTrue(build.kwargs["text"])
            self.assertIsNone(
                build.kwargs.get("stderr"), "Compiler diagnostics must reach stderr"
            )

    def test_rust_refuses_to_launch_without_reported_binary_artifact(self):
        with self.process_boundaries() as (builds, launches):
            builds.return_value = subprocess.CompletedProcess(
                [], 0, stdout=json.dumps({"reason": "build-finished", "success": True})
            )
            with self.assertRaisesRegex(RuntimeError, "artifact"):
                self.run_cli("--backend", "rust")
            launches.assert_not_called()

    def test_build_is_reused_for_contract_secure_cookie_and_browser(self):
        for backend in ["go", "java", "rust"]:
            with (
                self.subTest(backend=backend),
                self.process_boundaries() as (builds, launches),
            ):
                self.assertEqual(self.run_cli("--backend", backend, "--browser"), 0)
                build_commands = [
                    call.args[0]
                    for call in builds.call_args_list
                    if call.args[0][0] != "npm"
                ]
                self.assertEqual(len(build_commands), 1)
                auth = self.auth_launches(launches)
                self.assertEqual(len(auth), 3)
                self.assertTrue(all(call.args[0] == auth[0].args[0] for call in auth))
                self.assertEqual(
                    [call.kwargs["env"]["AUTH_SESSION_TTL_SECONDS"] for call in auth],
                    ["3", "3", "1800"],
                )
                self.assertEqual(
                    [call.kwargs["env"]["AUTH_COOKIE_SECURE"] for call in auth],
                    ["false", "true", "false"],
                )

    def test_build_cache_does_not_cross_invocations(self):
        with self.process_boundaries() as (builds, _):
            self.assertEqual(self.run_cli("--backend", "go"), 0)
            self.assertEqual(self.run_cli("--backend", "go"), 0)
            self.assertEqual(builds.call_count, 2)

    def test_unknown_backend_is_rejected_without_building_or_launching(self):
        with self.process_boundaries() as (builds, launches):
            with (
                self.assertRaisesRegex(ValueError, "backend"),
                conformance.server("jvaa"),
            ):
                self.fail("An unknown backend must not start a server")
            builds.assert_not_called()
            launches.assert_not_called()
            with self.assertRaises(SystemExit) as error:
                self.run_cli("--backend", "jvaa")
            self.assertEqual(error.exception.code, 2)

    def test_build_failure_is_reported_without_launching(self):
        for backend in ["go", "rust"]:
            with (
                self.subTest(backend=backend),
                self.process_boundaries() as (builds, launches),
            ):
                builds.side_effect = subprocess.CalledProcessError(
                    1, [backend, "build"]
                )
                with self.assertRaises(subprocess.CalledProcessError):
                    self.run_cli("--backend", backend)
                launches.assert_not_called()


if __name__ == "__main__":
    unittest.main()
