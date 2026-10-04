# Phase 8 — Bounded OpenAI request interpretation and grounded explanations

Branch: `codex/agent-integration`, based on the accepted Phase 7 merge
`0aa918ff3468a25e58ba543970855c51ab9342fa` into `codex/parallel-dispatch`.
The user instructed “proceed” after the Phase 7 Mac review. PR #1 is merged;
its historical draft flag and description could not be updated because the
GitHub connector lacks write permission. Git access completed the approved merge.

Phase 8 implementation, automated verification and live API validation pass.
**The Phase 8 checkpoint is accepted for progression to Phase 9 on October 4.**
The user authorized progression when the explanation passed completeness review,
then asked to fix the identified gaps. The revised explanation and independent
review now satisfy that condition. This records the current user's conditional
authorization; it does not invent another manual review or worker-owner sign-off.
Existing workers, their private configuration, accepted numerical processors and
the separate frontend are unchanged. The final HTML/UI demo remains Phase 9 work.

## API and workflow

This implementation uses the **OpenAI Responses API directly over the existing
pinned HTTPX dependency**. It does not use the separate OpenAI Agents API or
Agents SDK. The bounded workflow stays in Python; no new dependency is required.

Official documentation consulted October 4, 2026:

- [Function calling](https://developers.openai.com/api/docs/guides/function-calling):
  strict function schemas and a single tool selection per request.
- [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs):
  strict `text.format` JSON output, followed by application validation.
- [GPT-5.4 Mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini):
  an example model supporting Responses, function calling and structured outputs.
  `OPENAI_MODEL` is required and remains the operator's explicit choice.

The opt-in `backend.control.agent_main` entry point supports:

1. Reviewing retained original worker evidence with `--input`.
2. One new combined worker investigation only with the operator's `--execute`.

The model sees one operator-configured case and can request `investigate_case`
with that case ID and the supported `combined_environmental_review` investigation,
or `decline_request` with a bounded unsupported/clarification reason. Python binds
AOI, dates, resource basenames, threshold and worker destinations. Unknown tools,
extra arguments, different case IDs, duplicate JSON keys, malformed/refused/incomplete
responses and multiple calls fail validation. Model output cannot authorize a new
execution when the caller selected review mode. Natural-language interpretation
can still be wrong; bounded capabilities do not prove perfect understanding.

Saved evidence is rebuilt with the Phase 7 validation path and matched against
every configured request field before any model request. In execute mode, Python
calls the existing parallel coordinator once and records exact task IDs and the
independent results before explanation. The previous Control CLI remains usable
without model access.

The second model request selects 1–16 known fact IDs. Python renders their text,
measurements and references from the validated results. Arbitrary model prose or
numbers never become environmental conclusions. All eight available/unavailable
measurements, every rule outcome, time/coverage context and limitations remain
visible regardless of selected highlights. The full narrative has stable sections
for request/study area, combined observations, measurements, review conditions,
observation coverage, source products/methods and limitations. Source-specific
method facts are rendered locally from fixed processor templates and validated
evidence, outside the model-facing catalog. Optional radar threshold sensitivity
is checked against pixel counts, area and the central result before display; an
invalid sensitivity table stays unreported without removing the main measurement.
Rule references use ordinal indices to avoid sending arbitrary
policy labels/IDs to the model. The full deterministic source evidence remains in
the local report; raw worker payloads, resource URLs, infrastructure addresses,
errors, policy labels and credentials are excluded from the fact catalog.

The transport uses a fixed HTTPS origin, normal certificate verification,
`store:false`, no redirects/proxy environment, no automatic retries, a 30-second
total deadline per request, a 1,500-output-token cap, a 128 KiB request limit and a
256 KiB response limit. The standard run makes at most two model requests. API
failures produce static error codes and retain deterministic fallback explanations.
The application prompt is omitted by default. The explicit `--include-request`
option (or `run_agent(..., include_request=True)`) retains it in the local
explanation as quoted, untrusted user context. It is never treated as a measured
finding. Use this option when preparing a briefing that includes the original
request; inspect the text before sharing. Raw model responses and API keys are
never written into the result. The configured study-area label/bounds and replay
versus execution context are included independently of request retention.

## Private configuration

Use native Python 3.12 and the existing pinned requirements. Set these two values
privately in exported environment variables or an explicitly selected ignored file
such as `.env.phase8.local`:

```dotenv
OPENAI_API_KEY=<your-private-key>
OPENAI_MODEL=gpt-5.4-mini
```

Never commit the real key or put it in chat. The private file accepts only these
two assignments and comments; it performs no shell execution or interpolation.
No `.env` file is loaded automatically. Keep private-file permissions restricted
on each OS. The key is sent only in the Authorization header to the official API.
The request text and the compact environmental fact catalog are the API input.

## Retained-evidence command

Run from the repository root on Ryan's Mac (replace the interpreter with
`.\.venv\Scripts\python.exe` on Windows):

```sh
.venv/bin/python -m backend.control.agent_main --input outputs/debug/parallel-workers/physical-7bde416/result.json --config config/test_case.example.json --rules config/rules.example.json --env-file .env.phase8.local --request "Review the configured historical case and explain the evidence and demonstration conditions." --output outputs/debug/phase8/agent-review.json
```

The original requests determine resource names and task identity; the configured
AOI, scene window, reference time and requested event must match. No worker service
is contacted. This API-backed review does not reacquire data or repeat the accepted
physical-laptop checkpoint. The input's acquisition provenance remains necessary;
a replay does not independently authenticate arbitrary JSON evidence.

Add `--include-request` to the command above to include the original request in
the saved explanation. Phase 9 must escape all operator/request text when rendering
HTML, render every measurement independently of optional highlights, and attach
safe source-specific provenance from the retained report. Product labels and
resolvable references are already provided by Phase 8; raw source URLs, paths,
worker prose and credentials are not copied into its narrative.

Each CLI attempt has an ID in `<output>.phase8-attempt.json`. Pre-run evidence,
case or policy setup failure preserves an earlier output while marking the latest
attempt FAIL. Missing or invalid OpenAI settings instead save a new validated
deterministic fallback with an explicit configuration error. Compare IDs before
trusting old success. Writes are atomic and inputs, policies, case config,
private configuration and sidecars are protected from output aliases, including
hard links. Failed persistence stops subsequent actions.

## Optional new execution

With the worker URL/token variables already exported on Control, use:

```sh
.venv/bin/python -m backend.control.agent_main --execute --config config/test_case.example.json --rules config/rules.example.json --env-file .env.phase8.local --request "Investigate the configured historical case using rainfall, soil moisture, candidate water and terrain evidence." --gpm-resources 3B-HHR.MS.MRG.3IMERG.20211115-S000000-E002959.0000.V07B.HDF5 3B-HHR.MS.MRG.3IMERG.20211115-S003000-E005959.0030.V07B.HDF5 --smap-resource SMAP_L4_SM_gph_20211114T223000_Vv8010_001.h5 --output outputs/debug/phase8/new-investigation.json
```

This explicitly authorizes one combined worker dispatch. A declined or invalid
model plan submits nothing. No arbitrary worker paths, shell commands or extra
network tools are available. Existing worker authentication and limits still
apply. A timeout/interruption may leave a remote task running; inspect retained
task IDs before any manual retry. No worker restart is needed for Phase 8 review.

## Required live checkpoint

```sh
.venv/bin/python -m scripts.validate.validate_agent --input outputs/debug/parallel-workers/physical-7bde416/result.json --config config/test_case.example.json --rules config/rules.example.json --env-file .env.phase8.local --output outputs/debug/phase8/live-api.json
```

This makes **at most three actual API requests**: supported interpretation,
grounded fact selection, and an unsupported request which must be declined.
A shared request budget prevents an unexpected decision from expanding the check.
It verifies retained measurements, all rule outcomes, unchanged input bytes and
zero new worker dispatches. Partial failure retains completed evidence. A separate
attempt sidecar records setup/output failures without destroying an older report.
Use the user's actual private credentials; mocks are not a live pass.

A successful run returns `PASS / PENDING_USER`. The Phase 8 human review must check
whether the supported/unsupported decisions are appropriate, whether the grounded
highlights are useful, and whether mandatory scientific limitations remain clear.
Stop for that acceptance before merging Phase 8 or beginning Phase 9.

## Automated validation

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
git diff --check
```

Tests cover API failure categories and bounds, credential redaction, strict output
parsing, request/evidence binding, unsupported choices, explicit execution authority,
independent result preservation, input alias protection, stale-attempt handling,
partial evidence, deterministic fallback and unskippable scientific context.
Initial October 4 verification on macOS Python 3.12.14 (before completeness fixes):

- **PASS:** full suite, **1,171 passed**, zero failures/skips, 20.98 seconds.
  Log: `outputs/debug/phase8/pytest.log` (ignored local artifact).
- **PASS:** `python -m pip check` and `git diff --check`.
- **PASS:** independent implementation review and regression checks for the live
  validator's request budget and preservation on setup/output failures.
- **PASS:** a controlled simulated API timeout with the retained real Phase 6
  evidence kept every measurement and the four-triggered/one-not-triggered review.
  Artifact: `outputs/debug/phase8/offline-real-evidence-fallback.json`.
  This is an offline failure check, not a real API execution.
- **PASS:** authenticated live API checkpoint with `gpt-5.4-mini`, using the
  retained real Phase 6 evidence. All seven checks passed: supported request,
  known fact selection, unsupported rejection, zero worker dispatches, independent
  results preserved, all rule outcomes retained and exact measurements preserved.
  Input SHA-256 remained
  `493bc176185c05142e0511438bfa106deeef6a5515f225228b11fd3778ecc75d`.
  Artifacts: `outputs/debug/phase8/live-api.json` and `live-api-usage.json`.
  Three completed responses used **3,955 input / 161 output tokens**, estimated
  **$0.00369075 USD** at the linked model's standard text rates (billing is
  authoritative; cached input could cost less). The user approved the described
  historical evidence/prompt transmission after viewing its scope.
  The supported plan selected the configured combined investigation; the negative
  request was declined as `unsupported_location`. The model highlighted 16 known
  time/coverage/limitation facts; Python also retained every measurement and rule
  outcome in structured form. The completeness review below addresses the missing
  narrative measurements and context without modifying this historical checkpoint.

Existing third-party deprecation warnings remain (4,202 warnings in this full run).
Agent status `complete` describes the validated interpretation/explanation workflow;
source evidence may still be partial or unavailable and retains its own status.

The exact outbound request-body preview is
`outputs/debug/phase8/api-request-preview.json`. It excludes API credentials,
worker identities/addresses and raw source files. The provided `env.phase8.download`
is protected with owner-only permissions and a local Git exclude entry; it must
remain private. The actual checkpoint command on this Mac uses
`--env-file env.phase8.download`; other machines supply their own private settings.

## Explanation completeness review and accepted transition

The original narrative omitted available terrain/max-rainfall values and source
methods when the model selected only context facts. The local renderer now always
includes every measurement, every review condition and all required scientific
context. A concise combined summary states component availability and the counts
of demonstration outcomes, without assigning flood severity. The request and
configured area are distinguished from observed evidence. Source products,
processing methods, radar parameter sensitivity, false positives/negatives and
terrain limitations are unskippable. Optional sensitivity arithmetic, including
oversized inconsistent counts, cannot abort the otherwise valid explanation.

Final October 4 checks on macOS Python 3.12.14:

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
git diff --check
```

- **PASS:** **1,239 passed**, zero failures/skips, 19.74 seconds; 4,805 existing
  dependency deprecation warnings. Log:
  `outputs/debug/phase8/pytest-complete-explanation-full.log`.
  The first sandboxed run blocked four existing loopback HTTP tests; the complete
  rerun with local sockets permitted passed. No passing assertions were weakened.
- **PASS:** dependency and whitespace checks, independent code review and content
  review, including the optional-sensitivity overflow regression.
- **PASS:** nine checks on a local replay of the original real evidence and the
  actual live model selection: unchanged deterministic report, unchanged model
  fact catalog, every measurement visible, all rule outcomes visible, exact
  original request retained as context, area/bounds preserved, source/method
  context visible, unchanged input bytes and all source references resolvable.
  The request came from the retained outbound preview, not an invented substitute.
  The artifact still identifies this as a historical evidence review.
- **No additional API requests or worker dispatches.** The model-facing catalog,
  API prompts, schemas and transport are unchanged; the previous live check
  remains the API integration evidence. The new checks validate local rendering.

Review artifacts on Ryan's Mac (ignored, not committed):

- `outputs/debug/phase8/explanation-complete.txt` — revised human-readable output.
- `outputs/debug/phase8/explanation-complete.json` — the nine checks, source
  hashes, complete sections and resolvable references.
- `outputs/debug/phase8/complete-explanation-review.py` — repeatable local check:

```sh
.venv/bin/python -c "import runpy; runpy.run_path('outputs/debug/phase8/complete-explanation-review.py')"
```

The original `live-api.json`, `api-request-preview.json`, `explanation.txt` and
physical-worker evidence are preserved. Their historical pending status is not
rewritten. This acceptance permits the reviewed Phase 8 branch to merge into
`codex/parallel-dispatch` and a fresh `codex/briefing-integration` branch for Phase 9.
It does not claim that the final demo already exists. Phase 9 still must connect
the existing UI to real Control state, present safe exact source-resource detail,
escape all HTML text, verify the standalone download, run integration/browser
checks, and stop at its own human checkpoint.
