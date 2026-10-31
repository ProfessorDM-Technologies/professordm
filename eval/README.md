# eval: triage and knowledge base evaluation

This folder measures how well `services/ai_worker` triage labels DMs, using a golden set of labeled synthetic DMs, how well knowledge base search finds the right guide (see [Knowledge base retrieval eval](#knowledge-base-retrieval-eval)), and how well drafts stay grounded in the guides (see [Draft eval](#draft-eval)).

| File | What |
|---|---|
| `triage_golden.jsonl` | The golden set: 49 `dev` rows and 153 frozen `test` rows |
| `eval_triage.py` | Runs `triage()` on every row with the real models and prints the report |
| `generate_synthetic.py` | Generates, blind-labels and freezes the synthetic test split |
| `triage_test_meta.json` | How the test split was made: models, seed, cost, script hash, review decisions |
| `check_providers.py` | One tiny call per model with its real settings, to confirm each works under `data_collection: deny` |
| `eval_retrieval.py` | Knowledge base retrieval eval: guide-level hit@3, hit@5 and MRR, offline or live |
| `eval_draft.py` | Draft eval: automatic checks, coverage, abstention, an LLM judge for grounding, cost and latency; also tunes the draft gate |
| `generate_kb_eval.py` | Generates, validates and freezes the question sets for the knowledge base evals |
| `kb_eval_common.py` | Shared by the knowledge base evals: offline search, split rule, metrics, query embedding cache |
| `results/` | One JSON file per eval run (git-ignored) |
| `private/` | Unreviewed candidates, the knowledge base golden sets and the query embedding cache (git-ignored) |

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

## Knowledge base retrieval eval

Checks that a follower's question finds the guide that answers it (spec `docs/plans/kb-draft-implementation-spec.md`, sections 9.1 and 14.7). Every file with questions taken from the guides lives in `private/`, because the repo is public.

| File | What |
|---|---|
| `private/retrieval_golden.jsonl` | Frozen messy rows (and Arun's rows once they arrive) |
| `private/kb_candidates_<set>.jsonl` | Generator candidates for hand review, plus a `.meta.json` with model, seed, cost and filter stats |
| `private/query_embeddings.json` | Query vectors keyed by the sha256 of the query text (never the text), so reruns don't pay again |
| `results/retrieval-<timestamp>.json` | One file per run: settings, metrics, and per row the expected and ranked guide ids (no text) |

### Rows

Three origins, all scored the same way:

| Origin | Where it comes from | Id |
|---|---|---|
| `variant` | The held-out question variants of every guide, rebuilt at eval time with `chunk.split_variants` from `services/ai_worker/ingest/private/docs/*.json`. Never stored, so they can't drift from what the cards leave out | `<hpa_id>:v<i>`, `i` = index in the guide's full variant list |
| `messy` | Messy Instagram-style questions from `generate_kb_eval.py`, reviewed by hand | `ret-NNN` |
| `arun` | Arun's independently written queries (SCRUM-91), appended to `retrieval_golden.jsonl` by hand. Test only: a missing split becomes `test`, `dev` is rejected | any other prefix, for example `arun-01` |

```json
{"id": "ret-004", "split": "test", "query": "...", "expected_hpa_ids": ["HPA-FUND-0002"], "origin": "messy", "notes": "..."}
```

`expected_hpa_ids` lists every guide that answers the question (1 to 3 after review). A row is a hit at k when any of them is in the top k.

### Split rule

`split = "dev"` when `int(sha256(id).hexdigest(), 16) % 10 < 3`, else `"test"` (`kb_eval_common.split_for`). About 30% dev, the same for every machine and every run. Tune on dev only (chunking constants, cards); test is reported, never tuned on.

### Metrics and bar

The search returns ranked chunks. The guide ranking is each `hpa_id` at its first occurrence. Per origin and split the report shows n, hit@3, hit@5 and MRR, then the combined variant + messy line on test, Arun's group, and every miss at 5 with its expected and top 3 predicted guides.

**Bar:** hit@5 of 90% or more on test, variant + messy combined.

### Running it

```bash
set -a; source .env; set +a
uv run --python 3.11 python eval/eval_retrieval.py                 # offline, vector only (default)
uv run --python 3.11 python eval/eval_retrieval.py --no-cards      # without the doc cards (kind:card)
uv run --python 3.11 python eval/eval_retrieval.py --split dev --origin variant
uv run --python 3.11 python eval/eval_retrieval.py --live          # staging, after the load (needs knowledge.py, PR B)
```

| Mode | What it searches |
|---|---|
| `--offline` (default) | `kb_eval_common.offline_search`: cosine over `services/ai_worker/ingest/private/rows.jsonl` in memory, mirroring `knowledge.search` without SQL. Vector only, so it can't test the keyword half of the hybrid search |
| `--live` | `knowledge.search` against `match_knowledge` on staging. Needs `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` |
| `--no-cards` | Adds `exclude_tags=["kind:card"]` to either mode |

Both modes use `k=20, candidates=50, per_doc=50, sources=["doc"]`: ranking guides needs the raw chunk order, so the per-doc cap is effectively off. `--creator-id` defaults to the single creator in `rows.jsonl`. A full offline run embeds only new queries (a fraction of a cent for all 75) and takes a few seconds.

### Generating the question sets

```bash
set -a; source .env; set +a
uv run --python 3.11 python eval/generate_kb_eval.py estimate                     # mix and cost, no API calls
uv run --python 3.11 python eval/generate_kb_eval.py generate --set retrieval --budget 1
uv run --python 3.11 python eval/generate_kb_eval.py freeze --set retrieval        # after hand review
```

1. **`generate`.** `google/gemini-2.5-pro` (env `KB_EVAL_GEN_MODEL`), never the drafter or the judge, writes questions from each guide's id, title, summary, care topics and H1/H2 headings. It never sees body text. Requests send `provider: {"data_collection": "deny", "require_parameters": true}` and a strict JSON schema whose guide ids are an enum. Each spec names its target guide(s), cycling through the guides. Candidates that mention media, contradict their kind, or sit within 0.8 (difflib ratio) of any guide question variant or of another candidate are dropped. It refuses to overwrite a candidates file unless given `--force`, so a review in progress is safe.
2. **Review by hand.** Fix or delete lines in `private/kb_candidates_<set>.jsonl` and check `expected_hpa_ids` (and for drafts `expected_coverage`): the generator only proposes them. Deleting a line shifts the ids assigned at freeze.
3. **`freeze`.** Validates every row (labels present, guide ids exist, rounds well formed, `flagged_topics` only from the profile's risk topics), assigns `ret-NNN` / `draft-NNN` in file order and `split = split_for(id)`, and appends to `private/retrieval_golden.jsonl` (with `origin: "messy"`) or `private/draft_golden.jsonl`. It refuses if the file already holds that set.

`--set draft` builds about 40 paid questions for the draft eval (PR B): 12 plain, 10 clarified (a vague first message plus 1 or 2 clarification rounds, `question_text` = original and replies joined with `\n` like triage), 10 out of the knowledge base (`expected_coverage: "none"`), 8 risk topics (`safety_flagged: true`), about 8 of them asked in the Knowledge app. Clarified rows are always Instagram, because clarification rounds come from Instagram triage.

The retrieval set was generated on 2026-10-30 for $0.107: 21 written, 15 kept, none dropped by the filters. Review added a second or third answering guide to 6 rows; all 15 rows also hit at 3 against the generator's original ids.

### Results (2026-10-30, offline, vector only)

| Rows | Split | n | hit@3 | hit@5 | MRR | no cards: hit@3 | hit@5 | MRR |
|---|---|---|---|---|---|---|---|---|
| variant | dev | 13 | 100.0% | 100.0% | 0.962 | 100.0% | 100.0% | 0.962 |
| variant | test | 47 | 91.5% | 95.7% | 0.782 | 91.5% | 95.7% | 0.771 |
| messy | dev | 3 | 100.0% | 100.0% | 1.000 | 100.0% | 100.0% | 1.000 |
| messy | test | 12 | 100.0% | 100.0% | 1.000 | 100.0% | 100.0% | 1.000 |
| **variant + messy** | **test** | 59 | 93.2% | **96.6%** | 0.826 | 93.2% | **96.6%** | 0.818 |

Passes the bar in both modes. The cards add a little MRR (0.826 vs 0.818) and no hits; held-out variants are never on a card, so this measures the cards' summary and keywords, not leaked questions. Two test misses, the same in both modes. Nothing was tuned: the chunking constants are unchanged since the chunk review. Arun's group comes later (SCRUM-91).

**Live (2026-10-30, `match_knowledge` on staging, hybrid):** variant dev 92.3% / 100% / 0.891, variant test 97.9% / 97.9% / 0.797, messy dev and test 100% / 100% / 1.000, **variant + messy test 98.3% / 98.3% / 0.839** (hit@3 / hit@5 / MRR). It passes the bar and matches offline within a few points on hit@5 (+1.7). The keyword half lifts test hit@3 by 5 points and fixes both offline misses, and it costs one dev row at hit@3 (100% to 92.3% of 13). One live test miss: `HPA-TROUBLE-0005:v3`.

## Draft eval

Checks `draft()` end to end: the real search, the real draft models and checkpoint 2, on synthetic paid questions (spec `docs/plans/kb-draft-implementation-spec.md`, sections 9.2, 14.4 and 14.7 Q5). The questions are derived from the guides, so they live in `private/`.

| File | What |
|---|---|
| `eval_draft.py` | Runs `draft()` on every row, checks, judges and reports per split; `--gate-sweep` tunes the gate |
| `private/draft_golden.jsonl` | The frozen rows: 40 from `generate_kb_eval.py --set draft` plus 5 dev rows added later (below) |
| `private/kb_candidates_draft*.jsonl` | The generator candidates and their `.meta.json` (model, seed, cost, filter stats) |
| `results/draft-<timestamp>.json` | One file per run: settings, metrics per split, and per row the labels, outcome, passage ids and similarities, checks, judge verdict, latency and cost. The judge's `unsupported_claims` are kept only here; no question, passage or answer text |
| `results/draft-sweep-<timestamp>.json` | One file per gate sweep: each row's best similarity and the table |

### Rows

```json
{"id": "draft-007", "split": "test", "kind": "plain", "channel": "instagram", "question_text": "...",
 "safety_flagged": false, "expected_hpa_ids": ["HPA-FUND-0003"], "expected_coverage": "high", "notes": "..."}
```

| Field | Meaning |
|---|---|
| `id`, `split` | `draft-NNN` with `split = split_for(id)` (the same 30/70 hash as retrieval), or `draft-dev-NN` with `split: "dev"` set by hand |
| `kind` | `plain`, `clarified` (vague first message plus 1 or 2 rounds), `out_of_kb` (no guide covers it) or `risk` (touches a profile risk topic) |
| `channel` | `instagram` (1000-byte limit) or `knowledge_app` (4000) |
| `question_text` | The paid question; for `clarified`, the original and the replies joined with `\n`, like triage |
| `original_text`, `rounds` | `clarified` only: the first DM and `[{"round", "prompt", "reply"}]` |
| `safety_flagged`, `flagged_topics` | `risk` rows: `true` and the checkpoint-1 topics |
| `expected_hpa_ids` | The guides that answer it (empty for `none`) |
| `expected_coverage` | `high`, `partial` or `none`, set by hand review |
| `origin` | `dev_added` on the 5 rows added after the freeze |

**Mix after review:** 45 rows, 17 dev and 28 test. Of the 40 generated rows, review relabelled 5 `out_of_kb` rows as `plain` / `partial`, because a guide partly covers them, and relabelled 4 risk rows as `high` or `partial`. That leaves only 5 `out_of_kb` rows among the 40, and the hash put all of them in test.

**Dev out-of-KB rows added after the freeze.** With no `out_of_kb` (or `none`) rows in dev, the gate could not be tuned, so 5 were added the same way triage's dev rows `syn-NN` were written. `generate_kb_eval.py generate --set draft --kinds out_of_kb=8 --out private/kb_candidates_draft_dev.jsonl --avoid "<topics already used>"` wrote 8 candidates ($0.062), kept away from the existing out-of-KB topics, from topics a guide partly covers, and within 0.8 of any existing row or guide question variant. Hand review deleted 3. `freeze --set draft --dev-added --out ...` appended the other 5 as `draft-dev-01..05` (`split: "dev"`, `origin: "dev_added"`), without touching or renumbering the frozen rows.

### Search

`--offline` (default) runs `kb_eval_common.offline_search` over `rows.jsonl` (cosine only). `--live` runs `knowledge.search` against `match_knowledge` on staging (needs `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`). Both use `draft()`'s own settings (`k=8`, `sources=["doc"]`) and `knowledge.search`'s defaults (`candidates=20`, `per_doc=3`). Both are wrapped, so the eval sees the passages that were sent. `--exclude-tags review:pending` previews production; the default excludes nothing, as on staging.

### Metrics and bars (per split)

| Metric | How | Bar |
|---|---|---|
| Automatic checks | Every drafted answer passes `draft.py`'s own validators (`draft._check` on the rebuilt reply), fits the channel's byte limit, and cites only passages that were sent | 100% |
| `invalid_output`, `safety_blocked` | Counts | |
| Coverage accuracy | The decision's `knowledge_coverage` (`none` for any `no_draft`) equals `expected_coverage`; automatic, no judge. The report also prints the 3x3 confusion | ≥ 80% |
| Abstention | `out_of_kb` rows that come back `no_draft` | |
| False abstention | `high` / `partial` rows that come back `no_draft`, split into stopped by the gate (no model call) and by the model | |
| Grounded | The judge, over drafted rows | ≥ 90% |
| Uses clarification | The judge, over drafted `clarified` rows | |
| Retrieval hit | Any `expected_hpa_ids` among the passages' hpa ids | |
| Fallback share | Drafts the fallback wrote | |
| Latency | Mean and p90 of `draft()` wall time, drafted rows | |
| Cost | Mean draft-model cost per draft (judge reported separately) | < $0.02 |

### Judge

The judge is `openai/gpt-6.1-sol` (no `temperature`, strict schema), a different family from the Sonnet drafter. When a draft came from the `openai/` Terra fallback, the judge is `google/gemini-2.5-pro` at `temperature: 0`, so no model grades its own family. Both send `provider: {"data_collection": "deny", "require_parameters": true}`. The judge sees the question, the original and rounds, the creator rules, **every passage sent** with its ref, the answer and its `used_sources`, and returns `{"grounded", "unsupported_claims", "uses_clarification"}`:
- **grounded** is true only if every care claim (cause, step, number, timing, product type) is supported by at least one passage sent. Plain connecting words and cautions that match the creator rules count as supported.
- **uses_clarification** is true if the answer uses at least one specific detail from the follower's replies.

### Gate tuning

`eval_draft.py --gate-sweep` (dev only; it refuses another split) runs `draft()` with the gate above any similarity, so each row costs one search and no model call. It prints each row's best similarity, the should-stop rows against the lowest answerable one, and a table for cutoffs 0.20 to 0.50 in steps of 0.025. The pick is the cutoff that stops the most `none` rows while wrongly stopping at most 1 answerable dev row, with ties going to the lowest cutoff.

On 2026-10-30 (offline) the 5 dev out-of-KB rows scored 0.425 to 0.465 and the 12 answerable dev rows 0.515 to 0.656. **0.475** stops 5/5 and wrongly stops 0/12 (0.450 stops 2/5; 0.500 ties). It's frozen in `draft.DRAFT_MIN_SIMILARITY`. The margin is small (0.040 below the lowest answerable dev row, on 12 rows).

### Running it

```bash
set -a; source .env; set +a
uv run --python 3.11 python eval/eval_draft.py --split dev                 # offline, real models, about $0.25
uv run --python 3.11 python eval/eval_draft.py --split test                # once per prompt version
uv run --python 3.11 python eval/eval_draft.py --live --split dev          # staging match_knowledge
uv run --python 3.11 python eval/eval_draft.py --gate-sweep                # dev, no drafting
uv run --python 3.11 python eval/eval_draft.py --split dev --limit 3 --no-judge --gate 0.45   # quick try, gate for this run only
```

Other flags: `--rows FILE` (rows.jsonl, also the default creator), `--golden FILE`, `--creator-id`, `--workers N` (default 4). Transient API errors are retried in the eval (production raises them). Drafts and judge scores run without temperature, so expect a row or two of noise between runs.

### Results (2026-10-30, `draft-v2+sweetlife-v2`, gate 0.475)

`draft-v1` on dev scored 27.3% grounded and 58.8% coverage. Most unsupported claims were follow-up timings ("check again in a few days") prompted by a creator rule, plus small extrapolations. `draft-v2` was tuned on dev in three runs (grounded 63.6%, 45.5%, 72.7%; coverage 64.7%, 70.6%, 76.5%) and the last, best version ran on test once.

| Metric | dev offline (17) | dev live (17) | test offline (28) | Bar |
|---|---|---|---|---|
| Drafted / no_draft | 11 / 6 | 11 / 6 | 23 / 5 | |
| Automatic checks | 11/11 = 100% | 11/11 = 100% | 23/23 = 100% | 100% PASS |
| `invalid_output` / `safety_blocked` | 0 / 0 | 0 / 0 | 0 / 0 | |
| Coverage accuracy | 13/17 = 76.5% | 12/17 = 70.6% | 13/28 = 46.4% | ≥ 80% FAIL |
| Abstention (`out_of_kb`) | 5/5 | 5/5 | 3/5 | |
| False abstention (gate / model) | 1/12 (0 / 1) | 1/12 (0 / 1) | 2/22 (2 / 0) | |
| Grounded | 8/11 = 72.7% | 8/11 = 72.7% | 16/23 = 69.6% | ≥ 90% FAIL |
| Uses clarification | 3/3 | 3/3 | 7/7 | |
| Retrieval hit | 12/12 | 12/12 | 21/22 | |
| Fallback drafts | 0/11 | 0/11 | 0/23 | |
| Latency mean / p90 | 9.3 / 14.3 s | 8.5 / 14.9 s | 9.0 / 13.1 s | |
| Cost per draft | $0.0175 | $0.0164 | $0.0177 | < $0.02 PASS |

On test, coverage is mostly one step lower than the review label: 9 of 14 `high` rows came back `partial`, 2 `partial` rows stopped at the gate, and 3 `none` rows came back `partial`. Two of the 5 out-of-KB test rows scored 0.503 and 0.506, above the gate, and two answerable rows scored 0.428 and 0.471, below it. No cutoff separates them on test. The gate was not retuned. Only 5 `out_of_kb` rows exist per split, so abstention rests on a small sample.

## Models

Every OpenRouter call sends `provider: {"data_collection": "deny"}` (plus `require_parameters: true` with a schema), so only providers that don't retain prompts are used. `check_providers.py` confirms each model below finds such a provider with exactly these settings. Rerun it whenever a model id or a setting changes:

```bash
set -a; source .env; set +a
uv run --python 3.11 python eval/check_providers.py
```

Last checked 2026-10-30, all 9 checks passed.

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
