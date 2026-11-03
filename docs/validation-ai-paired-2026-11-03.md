# Paired AI integration validation — 2026-11-03

**24/24 actual Codex integrations passed; efficiency results were mixed.** Python, Go, Java and Rust each ran three baseline and three skill trials. Every consumer passed all 19 independent loopback HTTP checks, including wrong credentials, independent sessions, CSRF isolation, logout and old-cookie rejection.

Skill median input tokens decreased for Python, Java and Rust, but Go increased from **127,293 to 238,942**. Median total time decreased slightly for Python and Rust, while Java increased from **77.139 to 103.185 seconds** and Go also increased. These samples support v1 integration feasibility; they do not establish a general speed or token-saving gain. Wall time was not measured under isolated host conditions.

[Sanitized results](../evals/auth/results/2026-11-03-paired-v1.json) contain every trial and per-cell distributions. Previous smoke results are preserved and excluded from this sample.

## Medians by stack and condition

Each row has **n=3**. Total time includes the per-trial snapshot copy, CLI execution, builds and HTTP grading; the one-time freeze/setup is outside this timing. Agent time is the CLI interval, including its tool work, rather than pure model inference time. Token counts are CLI observations. Cached input is part of input, not an additional amount to add to it.

| Stack | Condition | Passed | Total seconds | Agent seconds | Commands | Input tokens | Cached input | Output tokens |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| python | baseline | 3/3 | 38.502 | 36.468 | 4 | 142,664 | 120,064 | 1,362 |
| python | skill | 3/3 | 36.739 | 34.806 | 5 | 119,323 | 105,216 | 1,265 |
| go | baseline | 3/3 | 42.782 | 41.268 | 6 | 127,293 | 110,208 | 1,430 |
| go | skill | 3/3 | 45.889 | 44.645 | 6 | 238,942 | 217,984 | 1,267 |
| java | baseline | 3/3 | 77.139 | 72.075 | 8 | 238,946 | 210,944 | 2,858 |
| java | skill | 3/3 | 103.185 | 80.266 | 8 | 237,144 | 212,224 | 4,001 |
| rust | baseline | 3/3 | 50.635 | 38.098 | 5 | 150,732 | 121,856 | 1,656 |
| rust | skill | 3/3 | 49.961 | 38.797 | 4 | 147,865 | 107,648 | 1,454 |

The JSON also retains min, p25, median, p75, max, sample counts, missing counts and individual runs. Time statistics include failed attempts when present; incomplete token totals are excluded rather than replaced with zero.

## Provenance and completeness

| Field | Captured value |
|---|---|
| Base commit | `aed5b418ce4883a08fa3488287d642ce35a30528` |
| Working tree at capture | `source_dirty=true` |
| Common source SHA-256 | `142626ee0fb7cc0b91f69fac3fd04c263b94975f0188b744a459197a076a9280` |
| Baseline snapshot SHA-256 | `e3865345b9810c8cf8f74bdbd10fab36a13c2122cce6db66640b1fd79c153376` |
| Skill snapshot SHA-256 | `142626ee0fb7cc0b91f69fac3fd04c263b94975f0188b744a459197a076a9280` |
| Runner SHA-256 | `a7d4ef2315b5e3fc0c79c01f718524ee6be5b37dc40760290fb18e31b6671026` |
| Task SHA-256 | `7b684daeefcd7fe9dd894a75c5c755714c8b3de9f1dff4f6c3aa5607069fa24f` |
| Requested model | `gpt-6.1-sol` |
| CLI | `codex-cli 0.166.0` |
| Profile / timeout | `browser-session-v1` / 600 seconds per trial |

The source was frozen once from a dirty checkout based on `aed5b418`, after the routing, generator and runtime API changes and before later documentation/license additions and Go publication-status bookkeeping in the manifest. It is **not the exact final Git tree**. All trials reused these frozen inputs. The base commit alone cannot reconstruct the uncommitted captured bytes; the hashes identify the retained local snapshots.

No trials failed. Reported model IDs are missing in **24/24** traces and remain `null`/`[]`; the requested ID is not substituted for an observed ID. Complete usage is missing in **0/24** runs. Source modification was recorded in **0/24** runs. Every result file was reconciled with the summary, every retained source snapshot hash was checked, and all median/quartile statistics were independently recomputed before publication. Raw traces, generated code, logs and host paths are not published here.

## Comparison and limits

Both conditions received the same current package code, public APIs, consumer examples and generator. Baseline used root instructions, root README and skill text from `2a18bbd50f142b2fc0a991fe0d40ccf7032476b9`, with new manifest/discovery references omitted; skill used the current routing. This compares documentation/context configurations, not package extraction or model internals.

Trials ran sequentially in Python → Go → Java → Rust order. Repeat 1 used baseline → skill, repeat 2 skill → baseline, and repeat 3 baseline → skill. Compiler, dependency and prompt caches were shared. Concurrent local v1/browser checks, Maven packaging, standalone crate tests and a Go module consumer also used the host; GitHub CI ran on separate hosts. **Wall-time deltas are descriptive, not controlled performance proof.** Input tokens and command counts remain direct CLI observations, with small-sample, cache and runtime-context limits.

With n=3 per cell, quartiles are descriptive and no statistical significance or universal model/language ranking is claimed. Explicit model selection does not verify a server-resolved model ID or immutable weights. Global/runtime instructions may remain despite ignoring user configuration; path references do not prove automatic skill selection or complete reading. No React, PostgreSQL v2, account v3 or mail model integration was measured. Separate DB/browser consumer checks are distinct evidence. This is not a security audit, production deployment validation or proof of a universal AI coding algorithm.

Observable follow-up work comes from executed commands and build files, without publishing model reasoning:

- Go skill trials 1 and 2 ran consumer lifecycle unit tests that returned nonzero before the independent grader passed. All three read the skill and selected Go guides/examples; none explicitly referenced the manifest. Fixture alignment and avoiding redundant exploratory validation are candidates for another controlled comparison. Both conditions had median six commands, so command count alone does not explain the input-token gap.
- All three Java skill build wrappers installed the reference library into a per-app Maven repository before packaging or verifying the consumer. Baseline grader build steps only packaged the consumer. Median total-minus-agent time was 27.451 seconds for skill versus 4.900 for baseline. Isolating upstream packaging/cache work is a concrete next experiment; the current measurements do not assign the full time difference to that work.

Invocation (a new output directory is required for a rerun):

```sh
uv run --frozen --project tools python tools/auth_eval.py \
  --stack all --condition both --model gpt-6.1-sol \
  --repeats 3 --timeout 600 --output eval-results/v1-paired-3-20261103
```
