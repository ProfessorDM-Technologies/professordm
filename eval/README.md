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
uv run --python 3.11 python eval/eval_retrieval.py --live          # staging match_knowledge (hybrid)
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

For rows added to dev later: `--kinds KIND=N` (only these kinds and counts), `--out FILE` (a separate candidates file), `--avoid "<topics>"` (kept on the command line), `--covered-risk` (risk questions a guide answers), and `freeze --dev-added --out FILE` (next free `draft-dev-NN`, refuses a file already frozen). See [Draft eval](#draft-eval).

1. **`generate`.** `google/gemini-2.5-pro` (env `KB_EVAL_GEN_MODEL`), never the drafter or the judge, writes questions from each guide's id, title, summary, care topics and H1/H2 headings. It never sees body text. Requests send `provider: {"data_collection": "deny", "require_parameters": true}` and a strict JSON schema whose guide ids are an enum. Each spec names its target guide(s), cycling through the guides. Candidates that mention media, contradict their kind, or sit within 0.8 (difflib ratio) of any guide question variant, of a row the set already holds (its golden file and every other `kb_candidates_<set>*.jsonl`), or of another candidate are dropped. It refuses to overwrite a candidates file unless given `--force`, so a review in progress is safe.
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
| `private/draft_golden.jsonl` | The frozen rows: 40 from `generate_kb_eval.py --set draft` plus 18 dev rows added later (below) |
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
| `origin` | `dev_added` on the 18 rows added after the freeze |

**Review of the 40 generated rows.** Review changed labels on 15 rows: 11 coverage or kind changes and 4 added guides. Five of the coverage or kind changes turned `out_of_kb` rows into `plain` / `partial`, because a guide partly covers them. That leaves only 5 `out_of_kb` rows among the 40, and the hash put all of them in test: 12 dev, 28 test.

**Dev rows added after the freeze**, the same way triage's dev rows `syn-NN` were written. They have ids `draft-dev-NN`, `split: "dev"` and `origin: "dev_added"`, and were appended by `freeze --set draft --dev-added --out <file>` without touching or renumbering the frozen rows:
- **`draft-dev-01..05`, out of the knowledge base.** Dev had no `out_of_kb` (or `none`) rows, so the gate could not be tuned. `generate --set draft --kinds out_of_kb=8 --out private/kb_candidates_draft_dev.jsonl --avoid "<topics already used>"` wrote 8 candidates ($0.062). They were kept away from the existing out-of-KB topics and from topics a guide partly covers, and the filter dropped anything within 0.8 of an existing row or guide question variant. Hand review deleted 3.
- **`draft-dev-06..18`, answerable.** These give the gate and the prompt more answerable rows to tune against: 6 plain, 4 clarified and 3 risk rows the guides do cover. `generate --set draft --kinds plain=6,clarified=4,risk=4 --covered-risk --out private/kb_candidates_draft_dev2.jsonl` wrote 12. A 2-row risk top-up kept 1 ($0.156 in all), because 5 of the 9 covered-risk candidates were dropped for contradicting their kind (the filter drops a covered-risk question labelled `none`) and 1 for mentioning media. The generator's coverage instruction uses the draft-v3 definition (below). Hand review relabelled 1, deleted 1 and added 1 hand-written risk row.

The final set has 58 rows: **30 dev** (11 plain, 7 clarified, 7 risk, 5 out_of_kb; 19 `high`, 6 `partial`, 5 `none`) and **28 test** (12 plain, 7 clarified, 4 risk, 5 out_of_kb; 14 `high`, 8 `partial`, 6 `none`). Only 5 `out_of_kb` rows exist per split, so abstention rests on a small sample.

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

Sweeps on 2026-10-30 (offline):
- **17 dev rows:** the 5 out-of-KB rows scored 0.425 to 0.465 and the 12 answerable rows 0.515 to 0.656. **0.475** stopped 5/5 and wrongly stopped 0/12.
- **Re-swept on all 30 dev rows:** the 25 answerable rows start at 0.493. **0.475** again stops 5/5 and wrongly stops 0/25. 0.450 stops 2/5; 0.500 stops 5/5 but wrongly stops 1/25.

It's frozen in `draft.DRAFT_MIN_SIMILARITY`. The margin is small: 0.018 below the lowest answerable dev row.

### Running it

```bash
set -a; source .env; set +a
uv run --python 3.11 python eval/eval_draft.py --split dev                 # offline, real models, about $0.52 (30 rows)
uv run --python 3.11 python eval/eval_draft.py --split test                # once per prompt version
uv run --python 3.11 python eval/eval_draft.py --live --split dev          # staging match_knowledge
uv run --python 3.11 python eval/eval_draft.py --gate-sweep                # dev, no drafting
uv run --python 3.11 python eval/eval_draft.py --split dev --limit 3 --no-judge --gate 0.45   # quick try, gate for this run only
```

Other flags: `--rows FILE` (rows.jsonl, also the default creator), `--golden FILE`, `--creator-id`, `--workers N` (default 4). Transient API errors are retried in the eval (production raises them). Drafts and judge scores run without temperature, so expect a row or two of noise between runs.

### Results (2026-10-30, gate 0.475)

**How the prompt got here (tuned on dev only):**
- **`draft-v1`** scored 27.3% grounded and 58.8% coverage on the first 17 dev rows. Most unsupported claims were follow-up timings ("check again in a few days") that a creator rule prompted, plus small extrapolations.
- **`draft-v2`** came from three dev runs (grounded 63.6%, 45.5%, 72.7%; coverage 64.7%, 70.6%, 76.5%). Its last version ran on test once: the **first test run**.
- **`draft-v3`** came from three runs on the 30-row dev set (grounded 75.0%, 79.2%, 87.5%; coverage 56.7%, 70.0%, 70.0%). Its last version ran on test once: the **second test run**.

What v3 changed:
- The v2 line "choose partial when unsure" is gone.
- Coverage `high` means the passages give advice for everything asked. `partial` means the follower asked more than one thing, or for a specific detail such as an exact distance, timing or product, and the passages don't cover all of it.
- Every sentence with a cause, step, check, number, timing, comparison, reassurance or description must come from a passage.
- Fewer, well-supported points are preferred.

| Metric | dev offline (30) | dev live (30) | test, draft-v3 (second test run) | test, draft-v2 (first test run) | Bar |
|---|---|---|---|---|---|
| Drafted / no_draft | 24 / 6 | 24 / 6 | 23 / 5 | 23 / 5 | |
| Automatic checks | 24/24 = 100% | 24/24 = 100% | 23/23 = 100% | 23/23 = 100% | 100% PASS |
| `invalid_output` / `safety_blocked` | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | |
| Coverage accuracy | 21/30 = 70.0% | 24/30 = 80.0% | 16/28 = 57.1% | 13/28 = 46.4% | ≥ 80% FAIL |
| Abstention (`out_of_kb`) | 5/5 | 5/5 | 3/5 | 3/5 | |
| False abstention (gate / model) | 1/25 (0 / 1) | 1/25 (0 / 1) | 2/22 (2 / 0) | 2/22 (2 / 0) | |
| Grounded | 21/24 = 87.5% | 19/24 = 79.2% | 18/23 = 78.3% | 16/23 = 69.6% | ≥ 90% FAIL |
| Uses clarification | 7/7 | 7/7 | 7/7 | 7/7 | |
| Retrieval hit | 25/25 | 25/25 | 21/22 | 21/22 | |
| Fallback drafts | 0/24 | 0/24 | 0/23 | 0/23 | |
| Latency mean / p90 | 6.8 / 12.9 s | 6.9 / 10.2 s | 7.9 / 10.5 s | 9.0 / 13.1 s | |
| Cost per draft | $0.0153 | $0.0149 | $0.0176 | $0.0177 | < $0.02 PASS |

**Coverage is below its bar.** It only drives the inbox badge; the draft text and `missing_info` don't depend on it.
- **On dev, every miss is one step lower than the label.** `high` comes back `partial`, and one `partial` row comes back `none` through the model's own coverage. The model is cautious there and never overclaims. Six `high` rows came back `partial` in all three v3 runs. Hand review of them against the guides kept the labels.
- **On test, 8 of the 12 misses are one step lower:**
  - 6 are `high` rows that came back `partial`.
  - 2 are `partial` rows stopped at the gate: the false abstentions, at 0.428 and 0.471.
- **On test, 4 misses go higher than the label:**
  - draft-023, draft-026 and draft-036 are rows no guide covers that the gate let through: the two `out_of_kb` rows at 0.506 and 0.503, plus a `none` risk row at 0.480. The model labelled them `partial`.
  - draft-029 is a `partial` row labelled `high`.
- **No single cutoff separates these test rows from the answerable ones** (two answerable rows sit at 0.428 and 0.471). The gate was not retuned.

**Coverage in two classes: extra information added after seeing these results, not a bar.** This scores only "the guides help" (`high` or `partial`) against "they don't" (`none`): dev offline 29/30 = 96.7%, dev live 29/30 = 96.7%, test draft-v3 23/28 = 82.1%, test draft-v2 23/28 = 82.1%.

**Grounded failures by category.** Dev, last run: an assumption about the follower's setup, causes ranked by likelihood, and general advice. Test draft-v3: a general claim, a definition, a timing, general advice, and reassurance; two of these are rows no guide covers (expected `none`) that the gate let through.

**Live vs offline (dev).** Retrieval matches: 29 of 30 rows got the same passages in the same order. Every grounded or coverage verdict that changed between the offline and live runs is on a row with identical passages, so the differences (coverage +3 rows, grounded -2 rows) are drafter and judge run-to-run noise, since neither runs with a temperature. They don't come from the search.

## Models

Every OpenRouter call sends `provider: {"data_collection": "deny"}` (plus `require_parameters: true` with a schema), so only providers that don't retain prompts are used. `check_providers.py` confirms each model below finds such a provider with exactly these settings. Rerun it whenever a model id or a setting changes:

```bash
set -a; source .env; set +a
uv run --python 3.11 python eval/check_providers.py
```

Last checked 2026-10-30, all 9 checks passed. The Gemini row is two checks, without and with `temperature: 0`.

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

Decided by Chinmay (2026-10-30): `anthropic/claude-sonnet-5.5` is the draft model; same price as the tech matrix's Sonnet 5.

Sonnet 5.5 and GPT-6.1-sol reject `temperature` under `require_parameters`, so drafts and judge scores aren't fully deterministic. Expect small run-to-run differences in draft eval numbers; a gate or prompt change must beat the baseline by more than that noise.
