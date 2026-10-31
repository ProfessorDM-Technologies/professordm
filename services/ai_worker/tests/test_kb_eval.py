"""Unit tests for the knowledge base eval code in eval/.

Covers kb_eval_common (offline search, split, metrics, query cache),
generate_kb_eval (candidate filters, validation, freeze) and eval_retrieval
(variant rows, golden rows). Every fixture uses made-up text and tiny
vectors; embed functions are fakes, so nothing touches the network. Run with:
    uv run --python 3.11 python -m unittest discover services/ai_worker/tests
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

EVAL = Path(__file__).resolve().parents[3] / "eval"
sys.path.insert(0, str(EVAL))

import eval_retrieval  # noqa: E402  (needs the sys.path line above)
import generate_kb_eval as gen  # noqa: E402
import kb_eval_common as common  # noqa: E402
from prompts import SWEETLIFE_FLORA  # noqa: E402

CREATOR = "creator-a"


def entry(entry_id, vector, *, doc_id="doc-1", hpa="HPA-TEST-0001", source="doc", tags=None, creator=CREATOR):
    """Build a knowledge_entries-shaped row with an hpa tag unless tags are given."""
    return {"id": entry_id, "creator_id": creator, "doc_id": doc_id, "source": source, "title": f"T {entry_id}",
            "content": "made-up text", "tags": tags if tags is not None else [f"hpa:{hpa}", "kind:section"],
            "embedding": vector}


def fixed_embed(vector):
    """Return a fake embed that maps every text to one vector and counts its calls."""
    calls = []

    def embed(texts):
        """Record the texts and return the fixed vector for each."""
        calls.append(list(texts))
        return [vector for _ in texts], {"model": "fake", "tokens": 1, "latency_ms": 0}

    embed.calls = calls
    return embed


class OfflineSearchTests(unittest.TestCase):
    def setUp(self):
        """Six rows for creator A in two guides plus a Q&A row, and one row for another creator."""
        self.rows = [
            entry("e1", [1, 0, 0]),
            entry("e2", [0.9, 0.1, 0]),
            entry("e3", [0.8, 0.2, 0]),
            entry("e4", [0.7, 0.3, 0], doc_id="doc-2", hpa="HPA-TEST-0002"),
            entry("q1", [0.95, 0, 0.05], doc_id=None, source="question"),
            entry("q2", [0.6, 0.4, 0], doc_id=None, source="question"),
            entry("x1", [1, 0, 0], creator="creator-b"),
            {**entry("n1", None), "embedding": None},
        ]
        # Q&A rows with null tags, like the demo entries.
        self.rows[4]["tags"] = None
        self.rows[5]["tags"] = None
        self.embed = fixed_embed([1, 0, 0])

    def search(self, **kwargs):
        """Run offline_search for creator A with the fake embed."""
        return common.offline_search("q", CREATOR, rows=self.rows, embed=self.embed, **kwargs)

    def test_same_shape_as_knowledge_search(self):
        """Each result has exactly knowledge.search's keys, and score equals similarity."""
        result = self.search()[0]
        self.assertEqual(set(result), {"entry_id", "doc_id", "hpa_id", "source", "title", "content",
                                       "similarity", "score"})
        self.assertEqual(result["score"], result["similarity"])
        self.assertEqual((result["entry_id"], result["hpa_id"]), ("e1", "HPA-TEST-0001"))

    def test_creator_and_missing_embedding_filtered(self):
        """Another creator's rows and rows without an embedding never come back."""
        ids = [r["entry_id"] for r in self.search(k=20, per_doc=20)]
        self.assertNotIn("x1", ids)
        self.assertNotIn("n1", ids)

    def test_ranked_by_cosine(self):
        """Results come back in descending cosine similarity."""
        similarities = [r["similarity"] for r in self.search(k=20, per_doc=20)]
        self.assertEqual(similarities, sorted(similarities, reverse=True))
        self.assertAlmostEqual(similarities[0], 1.0)

    def test_per_doc_cap_and_null_doc_groups(self):
        """At most per_doc rows per doc_id; each null-doc_id row is its own group."""
        ids = [r["entry_id"] for r in self.search(k=20, per_doc=1)]
        self.assertEqual(ids, ["e1", "q1", "e4", "q2"])

    def test_candidates_apply_before_cap_and_k_after(self):
        """The cap works on the first `candidates` rows only, then k trims."""
        self.assertEqual([r["entry_id"] for r in self.search(candidates=3, per_doc=1)], ["e1", "q1"])
        self.assertEqual(len(self.search(k=2, per_doc=20)), 2)

    def test_sources_filter(self):
        """sources keeps only the listed sources."""
        self.assertEqual({r["source"] for r in self.search(k=20, per_doc=20, sources=["doc"])}, {"doc"})

    def test_exclude_tags_keeps_null_tag_rows(self):
        """Excluding a tag drops rows carrying it but keeps rows with null tags."""
        ids = [r["entry_id"] for r in self.search(k=20, per_doc=20, exclude_tags=["kind:section"])]
        self.assertEqual(ids, ["q1", "q2"])

    def test_ties_broken_by_id(self):
        """Equal similarities are ordered by row id, so runs repeat exactly."""
        rows = [entry("b", [1, 0]), entry("a", [1, 0])]
        ids = [r["entry_id"] for r in common.offline_search("q", CREATOR, rows=rows, embed=fixed_embed([1, 0]))]
        self.assertEqual(ids, ["a", "b"])

    def test_embeds_query_once(self):
        """The query is embedded with one call holding just the query text."""
        self.search()
        self.assertEqual(self.embed.calls, [["q"]])


class MetricTests(unittest.TestCase):
    def test_split_is_deterministic_and_about_thirty_percent_dev(self):
        """split_for gives the same answer every time and about 30% dev."""
        ids = [f"row-{i}" for i in range(2000)]
        self.assertEqual([common.split_for(i) for i in ids], [common.split_for(i) for i in ids])
        share = sum(common.split_for(i) == "dev" for i in ids) / len(ids)
        self.assertTrue(0.26 < share < 0.34, share)

    def test_doc_ranking_first_seen_skipping_none(self):
        """Guides are listed at their first occurrence; rows without an hpa_id are skipped."""
        results = [{"hpa_id": "B"}, {"hpa_id": None}, {"hpa_id": "A"}, {"hpa_id": "B"}, {"hpa_id": "C"}]
        self.assertEqual(common.doc_ranking(results), ["B", "A", "C"])

    def test_hit_at_any_expected(self):
        """A hit needs any one expected guide inside the top k."""
        self.assertTrue(common.hit_at(["A", "B", "C"], ["C", "Z"], 3))
        self.assertFalse(common.hit_at(["A", "B", "C"], ["C"], 2))
        self.assertFalse(common.hit_at([], ["A"], 5))

    def test_reciprocal_rank(self):
        """MRR uses the first expected guide's position, 0 when none is ranked."""
        self.assertEqual(common.reciprocal_rank(["A", "B", "C"], ["C", "B"]), 0.5)
        self.assertEqual(common.reciprocal_rank(["A"], ["Z"]), 0.0)


class CacheAndLoadTests(unittest.TestCase):
    def test_cache_embeds_once_and_stores_no_text(self):
        """A second lookup makes no call, and the cache file holds hashes, not the query."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cache.json"
            inner = fixed_embed([0.5, 0.5])
            embed = common.cached_embed(inner, path, model="m1")
            embed(["secret question"])
            vectors, _ = common.cached_embed(inner, path, model="m1")(["secret question"])
            self.assertEqual(len(inner.calls), 1)
            self.assertEqual(vectors, [[0.5, 0.5]])
            self.assertNotIn("secret question", path.read_text())

    def test_cache_passes_options_to_embed(self):
        """Keyword options such as knowledge.search's retry=False reach the inner embed on a miss."""
        calls = []

        def inner(texts, **options):
            """Record the texts and options and return one fixed vector per text."""
            calls.append((list(texts), options))
            return [[1.0] for _ in texts], {"model": "fake", "tokens": 1, "latency_ms": 0}

        with tempfile.TemporaryDirectory() as folder:
            embed = common.cached_embed(inner, Path(folder) / "cache.json", model="m1")
            embed(["q"], retry=False)
            embed(["q"], retry=False)
        self.assertEqual(calls, [(["q"], {"retry": False})])

    def test_cache_for_another_model_is_ignored(self):
        """Vectors cached for a different embedding model are never reused."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cache.json"
            common.cached_embed(fixed_embed([1.0]), path, model="m1")(["q"])
            inner = fixed_embed([2.0])
            vectors, _ = common.cached_embed(inner, path, model="m2")(["q"])
            self.assertEqual((vectors, len(inner.calls)), ([[2.0]], 1))

    def test_load_rows_keeps_entry_upserts_only(self):
        """Docs rows and set_embedding records are skipped."""
        records = [{"table": "knowledge_docs", "op": "upsert", "id": "d"},
                   {"table": "knowledge_entries", "op": "upsert", "id": "e", "creator_id": CREATOR},
                   {"table": "knowledge_entries", "op": "set_embedding", "id": "s", "embedding": [1]}]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rows.jsonl"
            path.write_text("".join(json.dumps(r) + "\n" for r in records))
            rows = common.load_rows(path)
        self.assertEqual([r["id"] for r in rows], ["e"])
        self.assertEqual(common.default_creator(rows), CREATOR)


DOCS = [{"hpa_id": "HPA-TEST-0001", "title": "Fern Guide", "summary": "About ferns.", "care_topics": ["watering"],
         "question_variants": ["v0 how often water fern", "v1 fern leaves crispy", "v2 fern light",
                               "v3 misting ferns", "v4 fern soil"],
         "blocks": [{"type": "heading", "level": 1, "text": "Watering"},
                    {"type": "paragraph", "text": "body text never sent"},
                    {"type": "heading", "level": 2, "text": "Dry tips"}]},
        {"hpa_id": "HPA-TEST-0002", "title": "Cactus Guide", "summary": None, "care_topics": [],
         "question_variants": ["c0 cactus sun", "c1 cactus winter"], "blocks": []}]
RISK = SWEETLIFE_FLORA["risk_topics"][0]


class GeneratorTests(unittest.TestCase):
    def test_catalog_has_headings_but_no_body_text(self):
        """The generator sees titles, summaries and headings, never paragraphs."""
        text = gen.catalog(DOCS)
        self.assertIn("Watering (Dry tips)", text)
        self.assertIn("HPA-TEST-0002 | Cactus Guide", text)
        self.assertNotIn("body text never sent", text)

    def test_join_question_matches_triage(self):
        """question_text is the original and the replies joined with newlines, empties skipped."""
        rounds = [{"round": 1, "prompt": "Which plant?", "reply": "a fern"},
                  {"round": 2, "prompt": "Where is it?", "reply": ""}]
        self.assertEqual(gen.join_question("help my plant", rounds), "help my plant\na fern")

    def test_draft_mix_and_app_channel_count(self):
        """Specs follow COUNTS, and the first rows of each kind hold 8 Knowledge app questions."""
        import random
        specs = gen.specs("draft", DOCS, random.Random(1))
        kept = [s for kind, count in gen.COUNTS["draft"].items() for s in [x for x in specs if x["kind"] == kind][:count]]
        self.assertEqual(sum(s["channel"] == "knowledge_app" for s in kept), 8)
        self.assertTrue(all(s["channel"] == "instagram" for s in specs if s["kind"] == "clarified"))

    def test_candidate_filters(self):
        """Media mentions, wrong round counts and labels that contradict the kind are dropped."""
        clarified = {"kind": "clarified", "channel": "instagram", "style": "s", "targets": ["HPA-TEST-0001"], "rounds": 1}
        item = {"message": "plant sad", "rounds": [{"prompt": "Which plant?", "reply": "fern"}],
                "expected_hpa_ids": ["HPA-TEST-0001"], "expected_coverage": "high", "flagged_topics": [], "notes": ""}
        row, reason = gen.to_candidate("draft", clarified, item)
        self.assertIsNone(reason)
        self.assertEqual(row["question_text"], "plant sad\nfern")
        self.assertEqual(gen.to_candidate("draft", clarified, {**item, "message": "see my photo"})[1], "media")
        self.assertEqual(gen.to_candidate("draft", {**clarified, "rounds": 2}, item)[1], "bad_rounds")
        long_prompt = [{"prompt": "x" * 200, "reply": "fern"}]
        self.assertEqual(gen.to_candidate("draft", clarified, {**item, "rounds": long_prompt})[1], "bad_rounds")
        out_of_kb = {"kind": "out_of_kb", "channel": "instagram", "style": "s", "targets": []}
        self.assertEqual(gen.to_candidate("draft", out_of_kb, {**item, "rounds": []})[1], "off_kind")

    def test_risk_candidate_is_flagged_with_its_topic(self):
        """Risk rows carry safety_flagged and the spec's risk topic."""
        spec = {"kind": "risk", "channel": "instagram", "style": "s", "targets": [], "risk_topic": RISK}
        item = {"message": "is my fern ok near the cat", "rounds": [], "expected_hpa_ids": [],
                "expected_coverage": "none", "flagged_topics": [], "notes": ""}
        row, _ = gen.to_candidate("draft", spec, item)
        self.assertEqual((row["safety_flagged"], row["flagged_topics"]), (True, [RISK]))

    def test_validate_catches_bad_rows(self):
        """Unknown ids, risk topics outside the profile and malformed rounds are reported."""
        ids = {"HPA-TEST-0001"}
        self.assertTrue(gen.validate("retrieval", {"query": "q", "expected_hpa_ids": ["HPA-NOPE-0001"]}, ids))
        self.assertEqual(gen.validate("retrieval", {"query": "q", "expected_hpa_ids": ["HPA-TEST-0001"] * 3}, ids), [])
        self.assertTrue(gen.validate("retrieval", {"query": "q", "expected_hpa_ids": ["HPA-TEST-0001"] * 4}, ids))
        base = {"kind": "risk", "channel": "instagram", "question_text": "q", "safety_flagged": True,
                "flagged_topics": [RISK], "expected_hpa_ids": [], "expected_coverage": "none"}
        self.assertEqual(gen.validate("draft", base, ids), [])
        self.assertTrue(gen.validate("draft", {**base, "flagged_topics": ["made up topic"]}, ids))
        clarified = {**base, "kind": "clarified", "safety_flagged": False, "flagged_topics": [],
                     "expected_hpa_ids": ["HPA-TEST-0001"], "expected_coverage": "high", "original_text": "o",
                     "rounds": [{"round": 2, "prompt": "p", "reply": "r"}]}
        self.assertTrue(gen.validate("draft", clarified, ids))

    def test_freeze_assigns_ids_and_splits_and_refuses_twice(self):
        """freeze writes ret-NNN rows with split_for splits and origin messy, then refuses a second run."""
        with tempfile.TemporaryDirectory() as folder:
            private = Path(folder)
            golden = private / "retrieval_golden.jsonl"
            candidates = [{"cid": "c01", "query": "fern crispy?? 😭", "expected_hpa_ids": ["HPA-TEST-0001"],
                           "notes": "n"},
                          {"cid": "c02", "query": "cactus help", "expected_hpa_ids": ["HPA-TEST-0002"], "notes": ""}]
            (private / "kb_candidates_retrieval.jsonl").write_text(
                "".join(json.dumps(c) + "\n" for c in candidates))
            with patch.object(gen, "PRIVATE", private), patch.dict(gen.GOLDEN, {"retrieval": golden}), \
                    patch.object(gen, "load_docs", return_value=DOCS), patch("builtins.print"):
                gen.freeze("retrieval")
                rows = [json.loads(line) for line in golden.read_text().splitlines()]
                self.assertEqual([r["id"] for r in rows], ["ret-001", "ret-002"])
                self.assertEqual([r["split"] for r in rows], [common.split_for("ret-001"), common.split_for("ret-002")])
                self.assertEqual({r["origin"] for r in rows}, {"messy"})
                with self.assertRaises(SystemExit):
                    gen.freeze("retrieval")


class EvalRetrievalTests(unittest.TestCase):
    def test_variant_rows_use_held_out_variants_and_full_list_index(self):
        """Variant rows are the held-out variants, with ids from their index in the full list."""
        rows = eval_retrieval.variant_rows(DOCS)
        self.assertEqual([r["id"] for r in rows], ["HPA-TEST-0001:v1", "HPA-TEST-0001:v3", "HPA-TEST-0002:v1"])
        self.assertEqual(rows[0]["query"], "v1 fern leaves crispy")
        self.assertEqual(rows[0]["split"], common.split_for("HPA-TEST-0001:v1"))
        self.assertEqual({r["origin"] for r in rows}, {"variant"})

    def test_golden_rows_accept_arun_as_test_only(self):
        """Arun rows default to test; an Arun row marked dev is rejected."""
        ids = {"HPA-TEST-0001"}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "golden.jsonl"
            path.write_text(json.dumps({"id": "arun-01", "query": "q", "expected_hpa_ids": ["HPA-TEST-0001"],
                                        "origin": "arun"}) + "\n")
            self.assertEqual(eval_retrieval.golden_rows(path, ids)[0]["split"], "test")
            path.write_text(json.dumps({"id": "arun-01", "split": "dev", "query": "q",
                                        "expected_hpa_ids": ["HPA-TEST-0001"], "origin": "arun"}) + "\n")
            with self.assertRaises(SystemExit):
                eval_retrieval.golden_rows(path, ids)

    def test_missing_golden_file_means_variants_only(self):
        """Without retrieval_golden.jsonl there are no messy or Arun rows."""
        self.assertEqual(eval_retrieval.golden_rows(Path("/nonexistent/golden.jsonl"), set()), [])


if __name__ == "__main__":
    unittest.main()
