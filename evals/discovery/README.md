# External discovery, supplied-URL reading and SDK selection

This protocol measures four separate conditions. It does not replace the
[supplied-source integration studies](../core/README.md).

| Stage | Information supplied | What can be observed |
| --- | --- | --- |
| `unbranded` | A generic web-feature request in Korean or English | Whether an official project is recommended without its name |
| `named` | Project name and author | Whether official sources are found and identified |
| `supplied_url` | Official repository URL | Whether retrieved official content supports the answer |
| `integration` | Trusted source checkout in a separate coding workspace | Reviewed source origins and independently executed HTTP checks |

Freeze [prompts.json](prompts.json) **before** running a model. Print one prompt:

```sh
python3 tools/discovery_observation.py prompt \
  --case web-features-ko --stage unbranded
```

Use `web-features-en` for English. Do not change wording after a failed result
and keep the same protocol ID. A deliberate wording change is a new protocol
version, with its own results. Do not give the unbranded model the local repo,
repository instructions, package archive, prior answers or this protocol file.

## Capture and review

Each observation starts in a **new conversation**. The same conversation's
followups are one observation, not repeated independent trials. Keep CLI,
web app and API interfaces separate, even under the same provider/model label.
Record the requested model and report the observed model only when available.
An unavailable identity remains `null`.

Raw responses, tool outputs, CLI stderr, generated applications and fixtures
belong in private, ignored working directories. Do not publish credentials,
account identifiers or raw reasoning. Preserve timeouts and authentication,
tool-approval, search, quota and infrastructure failures. They are not negative
recommendations. A CLI authentication failure is not a Gemini web-app result.

The input is a JSON array of records. Each record has exactly these fields:

```json
{
  "id": "trial-1",
  "provider": "provider-name",
  "interface": "cli",
  "requestedModel": "recorded-model-or-configured-default",
  "observedModel": null,
  "caseId": "web-features-ko",
  "stage": "unbranded",
  "sessionId": "recorded-session-or-new-process-id",
  "freshSession": true,
  "startedAt": "2026-11-16T13:00:00Z",
  "outcome": "blocked",
  "promptSha256": "REPLACE_WITH_SHA256_OF_THE_EXACT_PROMPT_UTF8_BYTES_WITHOUT_TRAILING_NEWLINE",
  "transcriptSha256": null,
  "review": null
}
```

Outcomes are `completed`, `blocked`, `timeout` and `error`. Completed records
need the retained transcript's SHA-256 and either `{"status":"pending"}` or a
review with exactly `status`, `mentioned`, `recommended`, `sourceUrls`,
`readEvidence` and `integrationEvidence`. Both flags are booleans and
`sourceUrls` is a list. `reviewed` means an external source review is complete;
do not use a model's self-assessment as that review.

- Mentioning the name is only `mentioned`. A recommendation with an official
  target URL is counted separately. A URL alone does not prove the page was read.
- Set `readEvidence` to `null` unless the reviewer retained actual official
  document output. Otherwise use `{"kind":"tool-output","sourceUrl":"...",
  "sha256":"..."}`. A tool-call counter or a model's claim is insufficient.
- Set `integrationEvidence` to `null` unless the integration stage has reviewed
  application source, dependency origins and passing independent HTTP checks.
  The object requires `httpPassed:true`, `httpReceiptSha256`,
  `originEvidenceSha256` and `appSourceSha256`. Copied/vendored SDK source is
  not an original external dependency connection.

The aggregator validates bookkeeping and evidence references. It **does not
fetch, inspect or attest the referenced artifacts**: independent source review
and actual runtime grading remain necessary. Tool output is not proof of model
understanding, and HTTP success alone is not proof of the SDK's code origin.

```sh
python3 tools/discovery_observation.py summarize --records /private/path/observations.json
```

It groups by provider, interface, requested model, prompt case and stage. Rates
use only reviewed, independent completed observations. Nonfresh conversations,
pending reviews, blocked runs, errors and timeouts remain visible. A denominator
of zero produces `null`, and stages with no observations remain unobserved.
Duplicate conversation IDs are rejected. Do not collapse the four stages into
one adoption or success percentage, or pool this dataset with older studies.

## Improving discovery without assuming success

Use [the product explainer](../../docs/what-is-feature-standards.md) for the
project's concrete role, supported behavior, public sources and version limits.
Link actual working examples and preserve dated experimental/security results.
Do not create fake users, external reviews, usage counts or backlinks.

Google's [AI search guidance](https://developers.google.com/search/docs/appearance/ai-features)
states that normal search fundamentals apply to AI Overviews/AI Mode and that
special AI text files or markup are not required. This is Google Search
guidance, not a guarantee about the Gemini app or CLI. Public readability,
search indexing, model recommendation and runtime adoption are separate states.

First capture a baseline, publish reviewable documentation changes through the
normal repository flow, then repeat the frozen questions in new conversations.
Record the actual measurement window and public source revision. Delayed
indexing and variable retrieval mean an immediate rerun is not a controlled
causal measurement of documentation changes.
