# Contributing

Put specifications, OpenAPI, and scenarios in `features/<feature>/`, and implementations with dependency locks in `implementations/<stack>/`. A client must work with every compatible server profile. Reuse an existing public package through a thin consumer before implementing another authentication system.

For a new language, extend the common runner's build/start adapter and run the same contract tests. Do not relax assertions for one implementation. Internal architecture can follow language conventions.

For a contract change, describe its trigger and before/after behavior, affected profiles and clients, new failure scenarios, and compatibility impact. Preserve older profile defaults. Migrations and demo seeding remain explicit operations.

Run relevant checks using the root README and `.github/workflows/ci.yml`. Update matching `ci/` templates when active workflows change. CLI changes require package tests and real generated-app checks; DB consumer changes require `tests/consumer_profiles.py --browser` with disposable databases.

For AI contributions, record the contract/profile, public APIs reused, and checks actually executed. Instruction inspection is not a model benchmark, and a local test is not a registry publication. Keep raw model traces, credentials, session tokens, and mail payloads out of commits and CI artifacts. Verify sources and preserve license notices for imported code.

Release tags must match package versions and point to a commit whose full main-branch CI has passed. See [npm releases](docs/npm-release.md) and [server releases](docs/server-releases.md). Report security issues through the [private reporting policy](SECURITY.md).
