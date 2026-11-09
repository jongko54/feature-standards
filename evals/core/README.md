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

## Candidate reading, discovery and transfer observations

The [2026-11-08 reading study](../../docs/validation-ai-reading-2026-11-08.md) preserves 24 fresh Codex exec sessions against the same clean source and local CLI 0.4.0 archive. Original independent HTTP outcomes are **23/24**, separately from corrected static evidence **24/24**. Compact guidance reduced paired input-token sums by 19.032% versus manual guidance, while uncached input increased by 16.927% and output by 12.933%. This is not a cost-saving guarantee or a registry-publication result. The [original sanitized summary](results/2026-11-08-reading-candidate-v1.json) retains every attempt; the [post-run audit](results/2026-11-08-reading-postrun-audit-v1.json) never overwrites it.

These entrypoints require an explicit local archive SHA-256, matching source commit, requested model, new private output directory and the available language toolchains:

```sh
uv run --frozen --project tools python tools/core_reading_eval.py \
  --artifact /absolute/path/feature-standards-0.4.0.tgz \
  --artifact-sha256 <sha256> --source-commit <40-character-commit> \
  --model gpt-6.1-sol --stack all --repeats 2 --timeout 600 \
  --output eval-results/reading-NEW
```

Use `tools/core_discovery_eval.py` with the same artifact/source/model/output flags for four observations without prescribed library reuse. It permits independent implementations and exact copies through the HTTP boundary, then reports copies and candidate API signals separately. A source review must connect each feature to the actual product routes. These are choices in a supplied checkout, not external adoption statistics.

Use `tools/core_transfer_eval.py --repeats 1` for eight separate observations comparing compact guidance with bundled `docs/ai-briefs/<stack>.md` on the fixed similar notes task. Both conditions must receive the same new archive including identical source and packaged briefs. The task changes route and permission labels, not the whole problem family; do not pool it with the original 24 sessions.

Use `tools/core_postgres_eval.py --stack python --repeats 1` for one separate Python source-candidate integration observation. It requires owned PostgreSQL binaries (`FEATURE_STANDARDS_LISTING_PG_BIN` when absent from PATH) and refuses external database configuration. The grader alone creates a private cluster, seeds rows and supplies a SELECT-only app role after the model finishes. It captures task bytes, hashes runtime fixture inputs and refuses changes. The HTTP checks cover the existing 143 assertions plus six checks at the 10,003-visible-row/offset-10,000 boundary. This is neither a token comparison nor a load test.

Fresh sessions do not equal internal API request counts. Raw usage includes cached input; reasoning output is not added twice. Tool-output inclusion, actual CLI argv, static public calls and HTTP behavior remain separate evidence tiers. Keep raw traces and generated programs private.

The completed 2026-11-08 follow-ups are separate datasets: [unprescribed discovery](results/2026-11-08-discovery-v1.json) with [route review](results/2026-11-08-discovery-route-audit-v1.json), the [eight-session notes pilot](results/2026-11-08-notes-brief-v1.json) with [per-language/output audit](results/2026-11-08-notes-brief-postrun-audit-v1.json), and the [original PostgreSQL attempt](results/2026-11-08-postgres-candidate-v1.json) with [two artifact-only diagnostics](results/2026-11-08-postgres-artifact-diagnostics-v1.json). The notes pilot passed 8/8 with paired input-token sums 71.442% lower under brief guidance; it has only one pair per backend. All four discovery programs implemented the three features independently. The PostgreSQL original stopped at a factory-alias checker false positive; after the narrow checker fix, one diagnostic failed for a missing offline build backend and a second passed 149 checks after preparing that cache. The original model failure stays unchanged. These phases total 37 fresh model sessions; diagnostics add zero.

## Unprescribed multi-model choice protocol

`tools/core_choice_eval.py` fixes Python/FastAPI, Go/net/http, Java/Spring Boot and Rust/Axum while leaving feature-library use optional. Two requested models, two fixed similar task variants and two repeats across the four backends produce 32 serial sessions. Dependency and prompt caches remain shared. The [protocol plan](../../docs/superpowers/plans/2026-11-10-adoption-observation.md) records the frozen source and artifact; model availability probes are separate from integration attempts.

```sh
uv run --frozen --project tools python tools/core_choice_eval.py run \
  --artifact /absolute/path/feature-standards-0.4.0.tgz \
  --artifact-sha256 <sha256> --source-commit <40-character-commit> \
  --models gpt-6.1-sol gpt-6-astra --stack all \
  --scenarios documents notes --repeats 2 --timeout 600 \
  --output eval-results/choice-NEW
```

Both task variants use the existing 143 HTTP assertions. All submitted attempts are retained, including failures after observable work starts. Prework infrastructure rejection and unknown starts have separate counts. No source review means unknown choice, not zero adoption. Imports and static call hints do not establish a product-route connection. Review each feature's build/start and handler path against the retained source, then supply file hashes and line evidence through `report --input eval-results/choice-NEW --reviews /private/path/reviews.json --output eval-results/choice-REVIEWED-NEW`. Reporting verifies the original result, trace, analysis and source hashes without rerunning or rewriting the programs.

These are observations inside a supplied checkout. They measure package/API reuse separately from HTTP correctness and do not measure internet discovery, use of the standards' ideas, external adoption or general token savings. The [public-project investigation](../../docs/adoption/2026-11-10-public-projects.md) is a separate source of evidence.

## Actual smoke on 2026-11-07

The [original eight-call smoke](results/2026-11-07-catalog-smoke-v1.json) requested `gpt-6.1-sol` with Codex CLI `0.167.0` and a 600-second per-trial limit. All token records were complete; the trace did not report the actual model identity. The exact executed runner is preserved at commit `6036df67f750a4fdd01eae82898ae0ec6f303827`, separately from implementation source `752e4e4` and published catalog `0.3.2`.

| Stack | Baseline outcome / elapsed seconds | Catalog outcome / elapsed seconds |
| --- | --- | --- |
| Python | PASS / 151.711 | cache guard failure / 235.964 |
| Go | PASS / 132.513 | PASS / 193.138 |
| Java | PASS / 259.552 | PASS / 241.540 |
| Rust | PASS / 236.942 | PASS / 270.930 |

The original outcome remains **7/8**. Python catalog generated a local `.uv-cache` containing tool-cache symlinks, which the original source guard rejected before any HTTP grading. Each passing program completed 143 assertions, including the original 19 auth checks. Catalog input token counts were higher in all four pairs, and elapsed time was higher in three. Shared caches, one observation per pair and the harness failure prevent a general efficiency claim. The new opt-in compact routing cards were **not measured** by this smoke.

After preserving that runner and the original failures, scoped corrections cover cache handling, valid import/dependency evidence and repeat-order alternation. The repeat-order bug did not affect this single-repeat schedule. A [separate artifact-only replay](results/2026-11-07-catalog-replay-v1.json), using [the bounded replay helper](replay_smoke.py), made **zero model calls** and applied one policy to all eight retained programs. It verified the original result/trace/reference/generated hashes before and after the full replay and restored only absent, trace-proven owned temporary roots. New private membership fixtures were exclusive; generated program bytes were not rewritten.

The replay passed **5/8** with all guards. Python catalog could not rebuild offline after its local cache was omitted. Both Go programs completed the 143 HTTP assertions but failed the strict generated-file hash guard after rebuilding; the changed files were not separately retained, so their cause is unproven and those outcomes remain failures. Python baseline, both Java programs and both Rust programs passed. Replay timings are separate restoration/build/grading measurements and do not replace original agent timings, tokens, wall time or the original 7/8 result.
