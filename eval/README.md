# eval: triage evaluation

This folder measures how well `services/ai_worker` triage labels DMs, using a golden set of labeled synthetic DMs.

| File | What |
|---|---|
| `triage_golden.jsonl` | The golden set: 49 `dev` rows and 153 frozen `test` rows |
| `eval_triage.py` | Runs `triage()` on every row with the real models and prints the report |
| `generate_synthetic.py` | Generates, blind-labels and freezes the synthetic test split |
| `triage_test_meta.json` | How the test split was made: models, seed, cost, script hash, review decisions |
| `check_providers.py` | One tiny call per model with its real settings, to confirm each works under `data_collection: deny` |
| `results/` | One JSON file per eval run (git-ignored) |
| `private/` | Unreviewed candidates from the generator (git-ignored) |

## Golden set format

One JSON object per line:

```json
{"id": "test-013", "split": "test", "text": "yo my calathea leaf tips keep going crispy brown lol ...",
 "recent_messages": [], "label": "expert_question", "notes": "synthetic test. topic: brown leaves; ..."}
```

| Field | Meaning |
|---|---|
| `id` | `syn-NN` for dev, `test-NNN` for test |
| `split` | `dev` or `test` |
| `text` | The latest DM |
| `recent_messages` | Earlier DMs from the same follower, oldest first (for split questions) |
| `label` | The correct category (one of the 6) |
| `service_kind` | Only for `service_request`: `platform`, `business` or `out_of_domain` |
| `notes` | Why it's there: topic, style, which hard case it covers, or "label set by hand" |

All rows are synthetic. Never commit real DM text without anonymizing it and getting sign-off first.

## Split rules

- **dev** is for tuning. When the prompt gets something wrong, add or fix dev rows and change the prompt.
- **test** is frozen. It's reported on every prompt change and never tuned on: never change `prompts.py` because of a specific test row, and never edit test rows. If a test row reveals a real gap, write a *new, similar* dev row and tune on that.
- **No row may copy a prompt example.** `eval_triage.py` exits before any model call if a row's text or recent messages match one of the profile's few-shot examples (similarity of 0.9 or more).
- **test is kept independent of dev.** The generator dropped test candidates within 0.8 similarity of a dev row. New dev rows should stay well below that against test.

## Running eval

```bash
set -a; source .env; set +a
uv run --python 3.11 python eval/eval_triage.py                                    # full set, default model
uv run --python 3.11 python eval/eval_triage.py --model google/gemini-3.5-flash-lite
uv run --python 3.11 python eval/eval_triage.py --limit 10                         # quick smoke run
```

A full run is 202 DMs, takes about 2 minutes and costs about $0.10. It retries rate limits itself.

### What the report shows (per split)

| Metric | Meaning |
|---|---|
| Overall accuracy | Rows where the predicted category equals the label |
| `service_kind` correct | Of rows labeled and predicted `service_request`, how many got the right kind |
| Precision (per category) | Of the rows predicted as this category, how many really are. Low `expert_question` precision means followers get asked to pay for questions that aren't ready |
| Recall (per category) | Of the rows that really are this category, how many were found. `safety_concern` recall must be 100% |
| Confusion matrix | Rows are the true label, columns the predicted label; off-diagonal cells are the mistakes |
| Wrong predictions | Each miss with its id, expected and predicted label, routed status, confidence and the model's reason |
| Risk flags, other safety flags | Which rows got flagged and by which layer |
| Moderation scores | The top OpenAI scores for every `safety_concern` row (true or predicted), to sanity-check the 0.5 thresholds |
| Statuses | How many rows were routed to each status |
| Confidence cutoff table | Accuracy above and below each cutoff from 0.05 to 0.95, plus a suggested `CONFIDENCE_CUTOFF` when one would help |
| Latency, tokens, cost | Averaged and totaled across all splits |

**Bars** (proposed, test split): overall accuracy of 90% or more, `safety_concern` recall of 100%, and `expert_question` precision of 90% or more.

## Generating the test split

The test split was generated once and is frozen.

```bash
set -a; source .env; set +a
uv run --python 3.11 python eval/generate_synthetic.py estimate        # mix and cost, no API calls
uv run --python 3.11 python eval/generate_synthetic.py generate --budget 3
uv run --python 3.11 python eval/generate_synthetic.py label           # resume labeling if it stopped
uv run --python 3.11 python eval/generate_synthetic.py freeze          # after human review
```

1. **`generate`.** `anthropic/claude-sonnet-5.5` writes DMs from fresh category descriptions, the Houseplant Academy topics and style rules. It never sees `prompts.py`. Candidates are deduped, and rows that mention media or are too close to dev are dropped. `openai/gpt-6.1-sol` then labels every candidate blind. Both outputs go to `private/`.
2. **Review by hand.** Look at the disagreements between the generator and the labeler, label the 10 boundary cases, and hand-write rows for any weak category. Set `label` (and `service_kind`) in `private/synthetic_candidates.jsonl`.
3. **`freeze`.** This appends the candidates to `triage_golden.jsonl` as `split: "test"` and writes `triage_test_meta.json`. It refuses to run if a test split already exists, if a row has no label, or if a `service_request` has no `service_kind`.

`triage_test_meta.json` records:
- both model ids (requested and served) and the seed
- the date and the actual cost ($0.45)
- the review decisions and the 21 hand-labeled rows
- `script_sha256`, the hash of `generate_synthetic.py` at `script_commit` (`0f91951`). Later commits only added comments.

The models run at the provider default temperature, so the seed reproduces the mix but not the exact DMs.

**Real accuracy** will come from how often the creator changes a label (`override_category`) once the inbox is live; this synthetic set only tells us we're in the right range.

## Models

Every OpenRouter call sends `provider: {"data_collection": "deny"}` (plus `require_parameters: true` with a schema), so only providers that don't retain prompts are used. `check_providers.py` confirms each model below finds such a provider with exactly these settings. Rerun it whenever a model id or a setting changes:

```bash
set -a; source .env; set +a
uv run --python 3.11 python eval/check_providers.py
```

Last checked 2026-10-29, all 9 checks passed.

| Check | Model id | Settings that work |
|---|---|---|
| Triage classify | `google/gemini-3.1-flash-lite` | `temperature: 0`, strict schema |
| Triage clarify | `google/gemini-3.1-flash-lite` | `temperature: 0`, no schema (plain text) |
| Draft primary | `anthropic/claude-sonnet-5.5` | no `temperature`, strict schema, `max_tokens: 2000` |
| Draft fallback | `openai/gpt-5.6-terra` | no `temperature`, `reasoning: {"effort": "low"}`, strict schema, `max_tokens: 4000` |
| Judge (Sonnet drafts) | `openai/gpt-6.1-sol` | no `temperature`, strict schema |
| KB eval question generator, judge (Terra drafts) | `google/gemini-2.5-pro` | strict schema, with or without `temperature: 0` (use `0` for judging) |
| Embeddings | `text-embedding-3-small` (OpenAI) | 1536 dimensions |
| Triage moderation | `omni-moderation-latest` (OpenAI) | returns `results[0].categories` |

Sonnet 5.5 and GPT-6.1-sol reject `temperature` under `require_parameters`, so drafts and judge scores aren't fully deterministic. Expect small run-to-run differences in draft eval numbers; a gate or prompt change must beat the baseline by more than that noise.
