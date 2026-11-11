# Security evidence baseline

## Goal and boundary

Add a reproducible, fail-closed security evidence pipeline for the existing five
language ecosystems. Preserve authentication, authorization and listing behavior.
This is a selected ASVS mapping and automated baseline, not ASVS certification,
an independent audit, a penetration test or a production-readiness guarantee.
Do not publish registry versions, change account permissions or deploy services.

## Approach

1. Map a selected subset of OWASP ASVS 5.0.0 requirements to contracts, source and
   named existing regression tests; retain gaps and deployment-owned controls.
   Pin the upstream CSV release and SHA-256. Mapping validates references and
   never treats a file's existence as a passing security test.
2. Pin OSV-Scanner, Semgrep CE and Gitleaks. Scan explicit tracked dependency
   manifests/lockfiles, application source and Git history/current tracked tree.
   Keep scanner errors distinct from findings. Never publish raw secret findings,
   scanner stdout, environment variables or local absolute paths.
3. Produce a JSON/Markdown source report and CycloneDX dependency inventory with
   commit, content hashes, tool versions, scope, exclusions and limitations. Fail
   the gate on findings, errors, malformed/empty coverage or missing tools.
4. Run on PRs, main pushes, a daily schedule and manual dispatch. Upload sanitized
   evidence even on failure. Require successful exact-main-commit security CI in
   the existing release verifier, and bind reviewed release artifact hashes to
   its verified source-CI/security-run receipt before publishing.
5. Run local real scans, report focused regression results and remaining gaps,
   push the changes and verify exact-ref remote workflows. Do not hide findings
   or weaken checks to obtain a green badge.

## Files and checks

- `security/`: policy, selected ASVS map, local static rules and rule fixtures.
- `tools/security_audit.py`, `tools/install_security_tools.py`: scoped scanner
  orchestration, sanitization, reports and checksum-verified tool setup.
- `tools/security_release.py`: source-run receipt and artifact digest binding.
- `tools/verify-release-ci.mjs`: require both exact-commit workflows.
- `tests/test_security_*.py`, `tools/verify-release-ci.test.mjs`: error/findings
  separation, zero-coverage rejection, secret redaction, inventory, source
  binding, unsafe paths, and mocked external API boundary failures.
- `.github/workflows/security.yml`, matching `ci/security.yml`, and existing
  publication workflows/templates: syntax, parity and safety checks.
- `SECURITY.md`, `docs/security.md`, root README: accurate public claims.

Run focused Python/Node tests, actual pinned scanner/rule-fixture executions,
existing repository Python discovery, catalog package checks and workflow lint.
Existing runtime suites remain in full CI; this change adds no runtime behavior.
Security database availability and newly disclosed dependency vulnerabilities are
external inputs; record failures/findings and block release rather than declaring
the source secure. Rollback is a normal reviewed revert, preserving receipts.
