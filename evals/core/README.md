# Three-feature catalog integration evaluation

This evaluator compares two entrypoint instructions for real generated applications:

- **baseline:** start from the frozen README, public library guides and consumer examples.
- **catalog:** explicitly run the published CLI's `list` and selected auth/authorization/listing `context` commands first.

Both receive the **same implementation source**, frozen from Git commit `752e4e498e0647684c57b6e2ec749da99eaa4b79`, and the **same available `feature-standards@0.3.2` archive**. Baseline may independently discover and use that catalog. This evaluates entrypoint guidance, not catalog availability, automatic skill activation, model internals or a universal AI coding algorithm.

The public npm metadata and downloaded bytes must match the reviewed release receipt's SHA-256 and SHA-512 integrity before any trial begins. The archive is unpacked as `catalog/package`, with path/link/size/duplicate checks and no `node_modules`. Both conditions use one identical template. Live checkout edits, new unpublished adapter APIs, Git history, environment files, build caches, logs, `.agents` auto-discovery links and old model traces are not copied into it. Reference source files are read-only and fingerprinted before/after each run.

## Run

From the repository root, with the existing authenticated Codex CLI and Python/Go/JDK21/Rust/Node toolchains:

```sh
mkdir -p eval-results
uv run --frozen --project tools python tools/core_eval.py \
  --stack all --condition both --model gpt-6.1-sol \
  --repeats 1 --timeout 600 \
  --output eval-results/core-catalog-smoke-NEW
```

`--model` is required; the evaluator never chooses or replaces it. The smoke example retains the historical benchmark identifier. Requested and trace-reported model identities are separate; an absent reported identity remains unknown. The CLI receives `exec --json --ignore-user-config --ephemeral --sandbox workspace-write` with approval policy never. No account or CLI configuration is changed. Generated programs do not inherit the model API key or `CODEX_HOME`.

Choose `--stack python|go|java|rust|all`, `--condition baseline|catalog|both`, `--repeats 1..10`, and `--timeout 1..600`. The output path must be new and private, with an existing parent and no symlink ancestors. Each trial reserves approximately one third of its deadline for builds and independent HTTP grading. Pair order alternates across both stack positions and repeats; the recorded sequence is authoritative.

## Outcome checks

The task imports the existing memory-session authentication library and both core libraries. It preserves `/api/profile` for the original 19 independent authentication lifecycle checks and adds document list/detail routes. The grader checks real loopback HTTP behavior:

- anonymous/forged sessions, real login, session CSRF isolation and logout/old-cookie rejection;
- tenant/owner isolation and generic denial for missing or inaccessible resources;
- authorization visibility before totals, typed filters, stable ID ties, pages and invalid raw query strings;
- matching current subject, membership revocation/recovery and inability of forged role/tenant/subject headers to restore access;
- generic membership-provider failure, security response headers and omission of private file paths/provider details.

After the model finishes, the grader creates a private, previously nonexistent membership JSON file and provides its path through `CORE_MEMBERSHIP_FILE`. The generated application must read it on every authenticated product request. The grader changes valid roles, revoked roles, mismatched subject, unavailable state and invalid JSON between requests. There is no public provider-control endpoint in the task. This is an internal trusted provider fixture, not a production membership store.

Static checks additionally require public auth/core imports and calls, source provenance and rejection of exact implementation-file copies. Python uses AST call evidence; other stacks use import/dependency and symbol evidence. These checks are incomplete anti-copy evidence, not a proof that no logic was duplicated or that a program cannot game the grader.

## Evidence and limits

The implementation follows OpenAI's [captured trace + artifacts + independent checks evaluation guidance](https://developers.openai.com/blog/eval-skills). It reuses the existing auth evaluator's process-tree timeout cleanup, run-command/path validation, private outputs, trace parsing and missing-token handling. Deterministic fake-CLI and intentionally broken-server tests verify the harness; they are not model performance results.

Private run outputs include every success/failure, source/catalog/task/runner hashes, requested and reported model identities, CLI version, sequence, timing, commands and usage completeness. Raw traces, generated source, membership fixtures and process logs stay under the ignored `eval-results/` directory. Output roots use mode `0700`; traces, logs and result JSON use `0600`. Publish only sanitized summary fields.

The fixed requested model and source do not prove immutable server weights. Compiler/dependency/prompt caches are shared, and concurrent local work is not isolated. Wall time includes setup, agent work, build and grading, not pure inference. File fingerprints exclude generated/build/cache directories and establish source-byte preservation; they do not establish an OS security boundary for arbitrary generated programs. Global runtime instructions may still exist despite disabled user configuration.

A single repeat gives **n=1 per stack/condition**. It can expose integration failures and verify that the harness runs; it cannot establish a general speed/token improvement, statistical significance, production readiness, browser UI correctness, DB-listing support or a security audit. Future efficiency claims need repeated controlled comparisons with the same recorded configuration.
