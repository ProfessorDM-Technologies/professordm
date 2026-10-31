"""Unit tests for the ingest scripts: parse, normalize, chunk, build_rows and load_kb.

Every fixture is a hand-built list of raw elements (the shape read_docx
returns), of doc.json blocks, or of chunk and row records, with made-up text,
so no .docx file, no python-docx and no network are needed. build_rows tests
replace llm.embed with a fake; load_kb tests pass a fake HTTP transport. Run
with:
    uv run --python 3.11 python -m unittest discover services/ai_worker/tests
"""

import contextlib
import difflib
import io
import json
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))

import build_rows
import chunk
import load_kb
import normalize
import parse


def p(text, style="Normal", is_list=False):
    """Build a raw paragraph element."""
    return {"kind": "paragraph", "style": style, "text": text, "list": is_list}


def h1(text):
    """Build a raw Heading 1 paragraph."""
    return p(text, "Heading 1")


def h2(text):
    """Build a raw Heading 2 paragraph."""
    return p(text, "Heading 2")


def table(*rows):
    """Build a raw table element from rows of cell text."""
    return {"kind": "table", "rows": [list(row) for row in rows]}


def box(text):
    """Build a 1x1 table (a boxed note)."""
    return table([text])


TITLE = "Caring for Moon Ferns"
BANNER = [p("THE EXAMPLE GARDEN ACADEMY", "Academy Eyebrow"), p(TITLE, "Academy Title"),
          p("HPA-FUND-0099  |  Care Fundamentals Guide", "Asset Meta")]


def blocks_of(*elements, title=TITLE):
    """Run body_blocks on the given elements."""
    return parse.body_blocks(list(elements), title)


def four_column_tail(**values):
    """Build a cut heading plus a 4-column metadata table."""
    rows = [("Field", "Machine Key", "Assigned Value", "Implementation Note")]
    rows += [(key.replace("_", " ").title(), key, value, "note") for key, value in values.items()]
    return [h1("9. Related Academy Entries"), table(*rows)]


def three_column_tail(**values):
    """Build a combined cut heading plus two 3-column tables (split template)."""
    items = list(values.items())
    half = len(items) // 2
    header = ("Machine key", "Assigned value", "Implementation note")
    return [h1("5. Related entries, references & evidence"),
            table(header, *[(key, value, "note") for key, value in items[:half]]),
            table(header, *[(key, value, "note") for key, value in items[half:]])]


class SplitDocumentTests(unittest.TestCase):
    def test_cut_on_heading_with_and_without_number(self):
        for heading in ("Related Academy Entries", "11. Related Academy Entries",
                        "5. Related entries, references & evidence", "References", "12. references"):
            parts = parse.split_document([h1("Intro"), p("Body."), h1(heading), p("Source A.")])
            self.assertTrue(parts["cut_found"], heading)
            self.assertEqual(len(parts["body"]), 2)
            self.assertEqual(parts["tail"][0]["text"], heading)

    def test_body_text_saying_references_never_cuts(self):
        parts = parse.split_document([h1("Intro"), p("References"), p("More body."), h2("References")])
        self.assertEqual(len(parts["body"]), 3)
        self.assertEqual(parts["tail"][0]["style"], "Heading 2")

    def test_no_cut_heading_keeps_everything(self):
        elements = [h1("Intro"), p("Body."), h1("References and further reading")]
        parts = parse.split_document(elements)
        self.assertEqual(parts, {"body": elements, "tail": [], "cut_found": False})


class BodyBlockTests(unittest.TestCase):
    def test_banner_dropped_by_pattern_in_any_order_and_intro_path(self):
        banner = [BANNER[2], p("Caring for moon ferns!", "Normal"), BANNER[0]]
        blocks = blocks_of(*banner, p("An intro sentence."), h1("1. First"), p("Body."))
        self.assertEqual(blocks[0], {"type": "paragraph", "text": "An intro sentence.", "path": ["Introduction"]})
        self.assertEqual(blocks[1], {"type": "heading", "level": 1, "text": "First"})
        self.assertEqual(blocks[2]["path"], ["First"])
        self.assertEqual(len(blocks), 3)

    def test_banner_patterns_only_apply_before_the_first_heading(self):
        blocks = blocks_of(h1("First"), p(TITLE))
        self.assertEqual(blocks[-1]["text"], TITLE)

    def test_in_this_guide_dropped_but_its_box_kept(self):
        blocks = blocks_of(*BANNER, p("Intro."), h2("In this guide"), p("Covers:"),
                           p("Topic one", "List Bullet", True), p("Topic two", "List Bullet", True),
                           box("Helpful Hint: Start small."), h1("1. First"), p("Body."))
        self.assertEqual([b["type"] for b in blocks], ["paragraph", "callout", "heading", "paragraph"])
        self.assertEqual(blocks[1], {"type": "callout", "title": "Helpful Hint", "text": "Start small.",
                                     "path": ["Introduction"]})

    def test_contents_heading_also_dropped(self):
        blocks = blocks_of(h1("First"), p("Body."), h1("Contents"), p("A line."), h1("Second"))
        self.assertEqual([b.get("text") for b in blocks], ["First", "Body.", "Second"])

    def test_heading_cleaning(self):
        cases = {"o  Check 1: Feel the soil": "Check 1: Feel the soil", "2. Light": "Light",
                 "2.1. Morning sun": "Morning sun", "10. Wrap up": "Wrap up", "3 Signs of thirst": "3 Signs of thirst",
                 "  Spaced   out ": "Spaced out"}
        for raw, clean in cases.items():
            self.assertEqual(parse.clean_heading(raw), clean)

    def test_heading_paths(self):
        blocks = blocks_of(h1("1. Water"), h2("o  Timing"), p("A."), h1("2. Light"), p("B."))
        self.assertEqual(blocks[2]["path"], ["Water", "Timing"])
        self.assertEqual(blocks[4]["path"], ["Light"])
        self.assertEqual(blocks[1], {"type": "heading", "level": 2, "text": "Timing"})

    def test_titled_box_becomes_callout(self):
        [block] = blocks_of(box("Key Takeaway: Water the root zone, not the calendar."))
        self.assertEqual(block["type"], "callout")
        self.assertEqual(block["title"], "Key Takeaway")
        self.assertEqual(block["text"], "Water the root zone, not the calendar.")

    def test_long_or_quoted_box_becomes_paragraph(self):
        nine_words = "One two three four five six seven eight nine: rest"
        long_title = "A" * 61 + ": rest"
        quoted = "“Moon ferns love: wet feet.” Not quite."
        straight = "\"Misting: fixes everything.\" It does not."
        for text in (nine_words, long_title, quoted, straight, "No colon in this box at all."):
            [block] = blocks_of(box(text))
            self.assertEqual(block, {"type": "paragraph", "text": text, "path": ["Introduction"]}, text)

    def test_eight_word_sixty_char_title_is_still_a_callout(self):
        title = "One two three four five six seven eight"
        [block] = blocks_of(box(f"{title}: rest"))
        self.assertEqual(block["type"], "callout")
        [block] = blocks_of(box("B" * 60 + ": rest"))
        self.assertEqual(block["type"], "callout")

    def test_table_header_rows_and_empty_rows_dropped(self):
        [block] = blocks_of(h1("Clues"), table(("What you see", "Check first"), ("Droop", "Soil"), ("", " "),
                                               ("Spots", "Leaves")))[1:]
        self.assertEqual(block, {"type": "table", "header": ["What you see", "Check first"],
                                 "rows": [["Droop", "Soil"], ["Spots", "Leaves"]], "path": ["Clues"]})

    def test_figure_caption_prefix_stripped_and_wrapped_line_joined(self):
        blocks = blocks_of(p("Figure 3. Roots need air", "Caption Custom"), p("as well as water.", "Caption Custom"),
                           p("**Figure 4:** A second caption.", "Caption Custom"), p("Normal text."))
        self.assertEqual([b["text"] for b in blocks],
                         ["Roots need air as well as water.", "A second caption.", "Normal text."])

    def test_caption_in_normal_style_does_not_join_the_next_paragraph(self):
        blocks = blocks_of(p("Figure 1. A caption."), p("Body text."))
        self.assertEqual([b["text"] for b in blocks], ["A caption.", "Body text."])

    def test_list_grouping_and_ordered(self):
        blocks = blocks_of(p("Step one", "List Number", True), p("Step two", "List Number", True),
                           p("A bullet", "List Bullet", True), p("Numbered by format", "Normal", True),
                           p("Between."), p("Another bullet", "List Paragraph", True))
        self.assertEqual([(b["type"], b.get("ordered"), b.get("items")) for b in blocks], [
            ("list", True, ["Step one", "Step two"]),
            ("list", False, ["A bullet", "Numbered by format"]),
            ("paragraph", None, None),
            ("list", False, ["Another bullet"])])

    def test_typed_bullets_are_list_items(self):
        blocks = blocks_of(p("□ Check the soil"), p("•\tLift the pot"), p("▪Look under leaves"),
                           p("◦  One"), p("● Two"), p("‣ Three"), p("Not a bullet."), p("• After"))
        self.assertEqual([(b["type"], b.get("ordered"), b.get("items")) for b in blocks], [
            ("list", False, ["Check the soil", "Lift the pot", "Look under leaves", "One", "Two", "Three"]),
            ("paragraph", None, None), ("list", False, ["After"])])

    def test_typed_and_styled_bullets_group_together(self):
        [block] = blocks_of(p("Styled", "List Bullet", True), p("□ Typed"), p("• Styled with glyph", "List Bullet", True))
        self.assertEqual(block["items"], ["Styled", "Typed", "Styled with glyph"])

    def test_glyph_in_heading_or_caption_style_is_not_a_bullet(self):
        blocks = blocks_of(h1("• Odd heading"), p("• A caption line", "Caption Custom"))
        self.assertEqual([b["type"] for b in blocks], ["heading", "paragraph"])
        self.assertEqual(blocks[1]["text"], "• A caption line")

    def test_unstyled_contents_line_drops_the_list_after_it(self):
        blocks = blocks_of(*BANNER, box("Key Point: Made up."), p("In this guide", "Section Green"),
                           p("Topic one", "List Bullet", True), p("□ Topic two"),
                           p("Figure 1. A made-up caption", "Figure Caption"), p("continued.", "Figure Caption"),
                           h1("1. First"), p("Body."))
        self.assertEqual([(b["type"], b.get("text"), b.get("path")) for b in blocks], [
            ("callout", "Made up.", ["Introduction"]),
            ("paragraph", "A made-up caption continued.", ["Introduction"]),
            ("heading", "First", None), ("paragraph", "Body.", ["First"])])

    def test_unstyled_contents_line_keeps_a_list_that_is_not_directly_after(self):
        blocks = blocks_of(h1("First"), p("  CONTENTS "), p("A sentence."), p("□ Kept"))
        self.assertEqual([b["type"] for b in blocks], ["heading", "paragraph", "list"])

    def test_captions_in_contents_section_are_kept_with_the_previous_path(self):
        blocks = blocks_of(h1("First"), p("Body."), h2("In this guide"), p("Covers:"), p("□ Topic"),
                           p("Figure 2. A made-up caption", "Caption Custom"), p("that wraps.", "Caption Custom"),
                           p("A plain line."), h1("Second"))
        self.assertEqual([(b["type"], b.get("text"), b.get("path")) for b in blocks], [
            ("heading", "First", None), ("paragraph", "Body.", ["First"]),
            ("paragraph", "A made-up caption that wraps.", ["First"]), ("heading", "Second", None)])

    def test_list_ends_at_table_or_heading(self):
        blocks = blocks_of(p("One", "List Bullet", True), table(("a", "b"), ("c", "d")), p("Two", "List Bullet", True),
                           h1("Next"), p("Three", "List Bullet", True))
        self.assertEqual([b.get("items") for b in blocks if b["type"] == "list"], [["One"], ["Two"], ["Three"]])


class PromoteHeadingTests(unittest.TestCase):
    def promote(self, *elements):
        """Run promote_headings and return (styles of paragraphs, promoted numbers)."""
        body, numbers = parse.promote_headings(list(elements))
        return [e.get("style") for e in body], numbers

    def test_missing_numbered_h1_typed_as_normal_is_promoted(self):
        elements = [h1("1. One"), p("Body."), p("2. A missing section heading"), p("Body."), h1("3. Three")]
        styles, numbers = self.promote(*elements)
        self.assertEqual(numbers, [2])
        self.assertEqual(styles[2], "Heading 1")
        blocks = parse.body_blocks(parse.promote_headings(elements)[0], None)
        self.assertEqual(blocks[2], {"type": "heading", "level": 1, "text": "A missing section heading"})
        self.assertEqual(blocks[3]["path"], ["A missing section heading"])

    def test_last_number_is_promoted_before_the_cut(self):
        self.assertEqual(self.promote(h1("1. One"), h1("2. Two"), p("Body."), p("3. Last section"), p("Body."))[1], [3])

    def test_first_number_needs_to_come_before_every_numbered_h1(self):
        self.assertEqual(self.promote(p("1. Opening"), h1("2. Two"))[1], [1])
        self.assertEqual(self.promote(h1("3. Three"), p("1. Opening"), h1("2. Two"))[1], [])

    def test_guards_reject_everything_else(self):
        cases = [
            [h1("1. One"), p("2. A full sentence that ends with a period."), h1("3. Three")],
            [h1("1. One"), p("2. " + " ".join(["word"] * 12)), h1("3. Three")],
            [h1("1. One"), h1("2. Two"), p("2. Already present"), h1("3. Three")],
            [h1("1. One"), h1("3. Three"), p("2. After its successor")],
            [h1("1. One"), p("2. Wrong order"), h1("3. Three")][::-1],
            [h1("1. One"), p("2. A list step", "List Paragraph", True), h1("3. Three")],
            [p("2. No numbered headings at all")],
            [h1("1. One"), p("5. Far from any neighbour"), h1("2. Two")],
            [h1("1. One"), p("2.Missing space"), h1("3. Three")],
            [h1("1. One"), h2("2. A real H2"), h1("3. Three")],
        ]
        for elements in cases:
            self.assertEqual(self.promote(*elements)[1], [], elements)

    def test_twelve_words_is_allowed_and_only_one_paragraph_per_number(self):
        twelve = "2. " + " ".join(["word"] * 11)
        self.assertEqual(self.promote(h1("1. One"), p(twelve), p("2. Second candidate"), h1("3. Three"))[1], [2])

    def test_promotion_is_reported_as_a_warning_with_the_number_only(self):
        body = [*BANNER, h1("1. One"), p("Body."), p("2. Secret heading words"), p("Body."), h1("3. Three")]
        doc = normalize.normalize_document(body + four_column_tail(content_id="HPA-FUND-0099",
                                                                   content_title=TITLE), "x.docx")
        self.assertEqual(doc["warnings"], ["promoted_heading:2"])


class MetadataTests(unittest.TestCase):
    VALUES = {"content_id": "HPA-FUND-0099", "content_title": TITLE, "content_summary": "A short made-up summary.",
              "search_keywords": "moon fern; fronds", "search_question_variants": "How do I water a moon fern?; Why are fronds pale?",
              "care_topic": "Watering; Light & Shade", "urgency_level": "low", "version": "1.2",
              "expert_review_status": "Approved", "related_content_ids": "HPA-FUND-0001; FUND-0002"}

    def label_tail(self, expert="Approved"):
        """The same values in the label template (2-column tables, bold labels, comma lists).

        The expert review status sits in its own governance table, as in the
        real label-template guide.
        """
        return [h1("11. Related Academy Entries"), p("HPA-FUND-0001 - Watering", "List Bullet", True),
                h1("12. References"), p("Source A."),
                table(("Content ID", "HPA-FUND-0099"), ("Title", "Ferns"), ("Full Title", TITLE),
                      ("Status", "APPROVED"), ("Version", "1.2")),
                table(("Primary Topic", "Watering"), ("Secondary Topics", "Light & Shade, watering"),
                      ("Search Keywords", "moon fern, fronds"),
                      ("Natural Language Queries", "How do I water a moon fern? | Why are fronds pale?"),
                      ("Urgency Level", "low"), ("Related Content IDs", "HPA-FUND-0001, FUND-0002")),
                table(("Authoring Method", "made up"), ("Expert Review Status", expert),
                      ("Expert Reviewer", "A. Person"), ("Next Review Due", "later"))]

    def normalized(self, tail):
        """Normalize a small body plus the given tail and drop fields that differ by template."""
        body = [*BANNER, p("A short made-up summary."), h1("1. First"), p("Body.")]
        doc = normalize.normalize_document(body + tail, "moon.docx")
        return {key: doc[key] for key in ("hpa_id", "title", "summary", "keywords", "question_variants",
                                          "care_topics", "urgency", "review_status", "content_version", "related")}

    def test_all_three_templates_give_the_same_shape(self):
        expected = {"hpa_id": "HPA-FUND-0099", "title": TITLE, "summary": "A short made-up summary.",
                    "keywords": ["moon fern", "fronds"],
                    "question_variants": ["How do I water a moon fern?", "Why are fronds pale?"],
                    "care_topics": ["watering", "light_and_shade"], "urgency": "low", "review_status": "approved",
                    "content_version": "1.2", "related": ["HPA-FUND-0001", "HPA-FUND-0002"]}
        self.assertEqual(self.normalized(four_column_tail(**self.VALUES)), expected)
        self.assertEqual(self.normalized(three_column_tail(**self.VALUES)), expected)
        self.assertEqual(self.normalized(self.label_tail()), expected)

    def test_template_detection(self):
        self.assertEqual(normalize.metadata_template(four_column_tail(content_id="x")), "four_column")
        self.assertEqual(normalize.metadata_template(three_column_tail(content_id="x", care_topic="y")), "three_column")
        self.assertEqual(normalize.metadata_template(self.label_tail()), "label")
        self.assertIsNone(normalize.metadata_template([table(("Plant", "Light"), ("Fern", "Shade"))]))

    def test_label_never_overrides_machine_key(self):
        tail = [*three_column_tail(content_id="HPA-FUND-0099", content_title="Machine title"),
                table(("Full Title", "Label title"), ("Status", "approved"))]
        meta, _ = normalize.extract_metadata(tail)
        self.assertEqual(meta["content_title"], "Machine title")
        self.assertEqual(meta[normalize.STATUS_LABEL_KEY], "approved")

    def test_one_matching_label_is_not_a_label_table(self):
        meta, _ = normalize.extract_metadata([table(("Status", "approved"), ("Colour", "green"))])
        self.assertEqual(meta, {})

    def test_aliases(self):
        meta, _ = normalize.extract_metadata(three_column_tail(urgency_level="high", version="2.0"))
        self.assertEqual((meta["urgency"], meta["content_version"]), ("high", "2.0"))

    def test_placeholders_become_none(self):
        for value in ("NOT POPULATED", "not populated - broad cross-group guide", "NOT APPLICABLE",
                      "Not Assigned", "NOT SET yet", "", "   "):
            self.assertIsNone(normalize._clean(value), value)
            self.assertEqual(normalize.split_list(value), [])
        self.assertEqual(normalize._clean("NOTABLE value"), "NOTABLE value")

    def test_split_rules(self):
        self.assertEqual(normalize.split_list("a; b ;; c"), ["a", "b", "c"])
        self.assertEqual(normalize.split_list("a | b, c"), ["a", "b, c"])
        self.assertEqual(normalize.split_list("a; b | c"), ["a", "b | c"])
        self.assertEqual(normalize.split_list("Does it? Will it?  Can it", questions=True),
                         ["Does it?", "Will it?", "Can it"])
        self.assertEqual(normalize.split_list("Does it? Will it?"), ["Does it? Will it?"])
        self.assertEqual(normalize.split_list("a, b,, c", commas=True), ["a", "b", "c"])
        self.assertEqual(normalize.split_list("a, b"), ["a, b"])

    def test_variant_union_and_dedup(self):
        meta = {"search_question_variants": "Why is my fern’s frond pale?; How often to mist?"}
        routing = {"natural-language routing": "why is my fern's  frond pale | Should I repot?"}
        self.assertEqual(normalize.variant_lists(meta, routing),
                         (["Why is my fern’s frond pale?", "How often to mist?"],
                          ["why is my fern's frond pale", "Should I repot?"]))
        self.assertEqual(normalize.question_variants(meta, routing),
                         ["Why is my fern’s frond pale?", "How often to mist?", "Should I repot?"])
        self.assertEqual(normalize.question_variants({}, {"natural-language queries": "A? B?"}), ["A?", "B?"])

    def test_snake_case(self):
        self.assertEqual(normalize.snake_case("Light & Acclimation"), "light_and_acclimation")
        self.assertEqual(normalize.snake_case("  Root-zone / Drainage!! "), "root_zone_drainage")
        self.assertEqual(normalize.snake_case("Café pH"), "cafe_ph")

    def test_care_topics_deduplicated_after_normalizing(self):
        self.assertEqual(normalize.care_topics({"care_topic": "Watering; watering ; Pots & Drainage"}, False),
                         ["watering", "pots_and_drainage"])

    def test_review_status_mapping(self):
        for value, status in (("approved", "approved"), ("APPROVED", "approved"), (" Approved ", "approved"),
                              ("approved with edits", "pending"), ("pending", "pending"), (None, "pending"),
                              ("NOT SET", "pending")):
            self.assertEqual(normalize.review_status({"expert_review_status": value}), status, value)

    def test_expert_review_status_decides_over_status_label(self):
        status = normalize.STATUS_LABEL_KEY
        cases = [({"expert_review_status": "pending", status: "APPROVED"}, "pending", True),
                 ({"expert_review_status": "approved", status: "draft"}, "approved", False),
                 ({status: "Approved"}, "approved", False),
                 ({"expert_review_status": "NOT SET", status: "approved"}, "approved", False),
                 ({status: "draft"}, "pending", False), ({}, "pending", False)]
        for meta, expected, conflict in cases:
            self.assertEqual(normalize.review_status(meta), expected, meta)
            self.assertEqual(normalize.review_conflict(meta), conflict, meta)

    def test_label_template_conflict_is_pending_with_a_warning(self):
        body = [*BANNER, p("Summary."), h1("1. First"), p("Body.")]
        doc = normalize.normalize_document(body + self.label_tail(expert="pending"), "moon.docx")
        self.assertEqual(doc["review_status"], "pending")
        self.assertEqual(doc["warnings"], ["review_status_conflict"])
        self.assertEqual(normalize.normalize_document(body + self.label_tail(), "moon.docx")["warnings"], [])

    def test_related_ids_from_every_source(self):
        tail = [h1("5. Related entries, references & evidence"), h2("Related Academy entries"),
                p("FUND-0003 - Soil", "List Bullet", True), p("HPA-PEST-0001 - Mites", "List Bullet", True),
                h2("References"), p("Journal of Plants 2021, PEST-9999.")]
        ids = normalize.related_ids("HPA-FUND-0099", {"related_content_ids": "HPA-FUND-0001; HPA-FUND-0099"},
                                    {"internal linking": "Link to FUND-0001 and TROUBLE-0002"}, tail)
        self.assertEqual(ids, ["HPA-FUND-0001", "HPA-TROUBLE-0002", "HPA-FUND-0003", "HPA-PEST-0001"])

    def test_summary_fallbacks(self):
        body = [*BANNER, p("Intro summary."), h1("1. First"), p("Body.")]
        routed = three_column_tail(content_id="HPA-FUND-0099") + [table(("Element", "Value"), ("Result summary", "Routed."))]
        self.assertEqual(normalize.normalize_document(body + routed, "x.docx")["summary"], "Routed.")
        plain = three_column_tail(content_id="HPA-FUND-0099", content_title=TITLE, content_summary="NOT POPULATED")
        self.assertEqual(normalize.normalize_document(body + plain, "x.docx")["summary"], "Intro summary.")
        no_intro = [h1("1. First"), p("Body.")] + plain
        self.assertEqual(normalize.normalize_document(no_intro, "x.docx")["summary"], "Body.")

    def test_references_stop_at_first_table(self):
        tail = four_column_tail(content_id="HPA-FUND-0099")
        tail[1:1] = [p("Source A."), h1("10. References"), p("Source B.")]
        doc = normalize.normalize_document([h1("First"), p("Body.")] + tail, "x.docx")
        self.assertEqual(doc["references"], ["Source A.", "Source B."])

    def test_no_cut_heading_warns_and_still_reads_metadata(self):
        tables = three_column_tail(content_id="HPA-FUND-0099", care_topic="x")[1:]
        doc = normalize.normalize_document([h1("First")] + tables, "x.docx")
        self.assertEqual(doc["hpa_id"], "HPA-FUND-0099")
        self.assertEqual(doc["warnings"], ["no_cut_heading", "no_title", "no_summary"])

    def test_missing_content_id_is_an_error(self):
        with self.assertRaises(ValueError):
            normalize.normalize_document([h1("First")] + four_column_tail(content_title="T"), "x.docx")

    def test_duplicate_hpa_id_names_both_files(self):
        docs = [{"hpa_id": "HPA-FUND-0001", "source_file": "guide_v2.docx"},
                {"hpa_id": "HPA-FUND-0002", "source_file": "other.docx"},
                {"hpa_id": "HPA-FUND-0001", "source_file": "guide_v4.docx"}]
        with self.assertRaises(ValueError) as caught:
            normalize.check_unique(docs)
        self.assertIn("guide_v2.docx", str(caught.exception))
        self.assertIn("guide_v4.docx", str(caught.exception))
        normalize.check_unique(docs[:2])



class NearDuplicateVariantTests(unittest.TestCase):
    def test_near_duplicate_dropped_and_first_kept(self):
        """A rewording of an earlier variant is dropped, reported by index, and metadata beats routing."""
        variants = ["How often should I mist a moon fern?", "How often do I mist my moon ferns?",
                    "Why are fronds limp?"]
        kept, dropped = normalize.near_duplicates(variants)
        self.assertEqual(kept, [variants[0], variants[2]])
        self.assertEqual([(k, d) for k, d, _ in dropped], [(0, 1)])
        self.assertGreaterEqual(dropped[0][2], normalize.VARIANT_DUP_RATIO)
        merged = normalize.question_variants(
            {"search_question_variants": variants[0]},
            {"natural-language queries": f"{variants[1]}; {variants[2]}"})
        self.assertEqual(merged, [variants[0], variants[2]])

    def test_pair_just_below_the_threshold_is_kept(self):
        """A 0.78 pair is two different questions and both stay."""
        variants = ["Is my pot too big?", "Is my pot too small?"]
        ratio = difflib.SequenceMatcher(None, *map(normalize._variant_key, variants)).ratio()
        self.assertAlmostEqual(ratio, 0.78, places=2)
        self.assertEqual(normalize.near_duplicates(variants), (variants, []))

    def test_dedup_happens_before_the_even_odd_split(self):
        """The dropped rewording takes no slot, so the card and held-out sets shift past it."""
        tail = three_column_tail(content_id="HPA-FUND-0099", content_title=TITLE, search_question_variants=(
            "How often should I mist a moon fern?; How often do I mist my moon ferns?; "
            "Why are fronds limp?; When should I repot?"))
        doc = normalize.normalize_document([h1("First"), p("Body.")] + tail, "x.docx")
        self.assertEqual(chunk.split_variants(doc["question_variants"]),
                         (["How often should I mist a moon fern?", "When should I repot?"],
                          ["Why are fronds limp?"]))

class CitationTests(unittest.TestCase):
    def test_strip_citations_forms(self):
        """Single, consecutive, comma and range markers go, with the space before them; words in brackets stay."""
        self.assertEqual(parse.strip_citations("Water weekly [1]."), "Water weekly.")
        self.assertEqual(parse.strip_citations("Mist daily [1][2] and wipe [3, 4] leaves [2–5] then [6-7] rest."),
                         "Mist daily and wipe leaves then rest.")
        self.assertEqual(parse.strip_citations("Water [1] ."), "Water.")
        self.assertEqual(parse.strip_citations("[1] Starts here."), "Starts here.")
        self.assertEqual(parse.strip_citations("Keep [note] and [sic] as written."), "Keep [note] and [sic] as written.")

    def test_markers_stripped_from_every_body_block(self):
        """Paragraphs, list items, box title and text, table cells and captions lose their markers."""
        blocks = blocks_of(p("Intro text [1]."), h1("Light"), p("A tip [2]."), p("Moss [3]", "List Bullet", True),
                           box("Key Tip [4]: Mist [5]."), table(("Sign [6]", "Fix"), ("Pale [7]", "Move [8, 9]")),
                           p("Figure 1. A fern [10]", "Caption"), p("[11]"))
        self.assertEqual(blocks, [
            {"type": "paragraph", "text": "Intro text.", "path": ["Introduction"]},
            {"type": "heading", "level": 1, "text": "Light"},
            {"type": "paragraph", "text": "A tip.", "path": ["Light"]},
            {"type": "list", "ordered": False, "items": ["Moss"], "path": ["Light"]},
            {"type": "callout", "title": "Key Tip", "text": "Mist.", "path": ["Light"]},
            {"type": "table", "header": ["Sign", "Fix"], "rows": [["Pale", "Move"]], "path": ["Light"]},
            {"type": "paragraph", "text": "A fern", "path": ["Light"]}])

    def test_references_keep_their_markers(self):
        """Only the body is cleaned; references after the cut keep their markers."""
        tail = four_column_tail(content_id="HPA-FUND-0099")
        tail[1:1] = [p("[1] Source A.")]
        doc = normalize.normalize_document([h1("First"), p("Body [1].")] + tail, "x.docx")
        self.assertEqual(doc["blocks"][1]["text"], "Body.")
        self.assertEqual(doc["references"], ["[1] Source A."])

# ---- chunk.py: fixtures are doc.json blocks, the shape normalize.py writes ----

GUIDE = "Moon Fern Care"


def prose(tokens, topic="moss"):
    """Made-up sentences about `topic`, at least `tokens` estimated tokens long."""
    sentences, number = [], 0
    while chunk.est_tokens(" ".join(sentences)) < tokens:
        number += 1
        sentences.append(f"Note {number} on {topic} says keep it damp.")
    return " ".join(sentences)


def heading(level, text):
    """Build a heading block."""
    return {"type": "heading", "level": level, "text": text}


def para(path, text):
    """Build a paragraph block under a heading path."""
    return {"type": "paragraph", "text": text, "path": list(path)}


def bullets(path, *items, ordered=False):
    """Build a list block."""
    return {"type": "list", "ordered": ordered, "items": list(items), "path": list(path)}


def grid(path, header, *rows):
    """Build a table block."""
    return {"type": "table", "header": list(header), "rows": [list(row) for row in rows], "path": list(path)}


def note(path, title, text):
    """Build a callout block."""
    return {"type": "callout", "title": title, "text": text, "path": list(path)}


def guide(*blocks, variants=("q0?", "q1?", "q2?", "q3?", "q4?")):
    """Build a doc.json dict around the given blocks."""
    return {"hpa_id": "HPA-TEST-0001", "title": GUIDE, "summary": "A made-up summary.",
            "keywords": ["moss", "mist"], "question_variants": list(variants), "care_topics": ["watering"],
            "review_status": "pending", "blocks": list(blocks)}


def chunks_of(*blocks, kind=None):
    """Chunk a made-up guide; optionally keep one kind only."""
    chunks, _, _ = chunk.chunk_document(guide(*blocks))
    return [c for c in chunks if kind is None or c["kind"] == kind]


class SectionBuildTests(unittest.TestCase):
    def test_h1_text_h2_sections_and_introduction(self):
        """Intro text, an H1's own text and each H2 are separate sections; the H1 and its H2 share a group."""
        sections = chunk.build_sections([
            para(["Introduction"], "Intro."), heading(1, "Light"), para(["Light"], "Own."),
            heading(2, "Signs"), para(["Light", "Signs"], "Pale."), para(["Light", "Signs"], "Leggy.")])
        self.assertEqual([s["path"] for s in sections], [["Introduction"], ["Light"], ["Light", "Signs"]])
        self.assertEqual(sections[2]["paragraphs"], ["Pale.", "Leggy."])
        self.assertEqual(sections[1]["group"], sections[2]["group"])
        self.assertNotEqual(sections[0]["group"], sections[1]["group"])

    def test_paragraphs_and_lists_render_as_section_text(self):
        """Paragraphs are separated by blank lines; lists render as '- item' and '1. item' lines."""
        [section] = chunks_of(heading(1, "Potting"), para(["Potting"], "Pick a pot."),
                              bullets(["Potting"], "moss", "bark"),
                              bullets(["Potting"], "Soak", "Drain", ordered=True), kind="section")
        self.assertEqual(section["title"], f"{GUIDE} > Potting")
        self.assertEqual(section["content"], "Pick a pot.\n\n- moss\n- bark\n\n1. Soak\n2. Drain")

    def test_tables_and_callouts_leave_section_text_and_empty_section_is_skipped(self):
        """Tables and callouts never enter section text, and a heading with only a table makes no section chunk."""
        chunks = chunks_of(
            heading(1, "Light"), para(["Light"], "Before."), grid(["Light"], ["Sign", "Fix"], ["Pale", "Move"]),
            note(["Light"], "Tip", "Turn weekly."), para(["Light"], "After."),
            heading(1, "Water"), grid(["Water"], ["Sign", "Fix"], ["Limp", "Soak"]))
        self.assertEqual([c["kind"] for c in chunks], ["section", "table", "callout", "table", "card"])
        self.assertEqual(chunks[0]["content"], "Before.\n\nAfter.")
        self.assertNotIn(f"{GUIDE} > Water", [c["title"] for c in chunks if c["kind"] == "section"])


class MergeTests(unittest.TestCase):
    def test_small_h1_text_merges_forward_with_heading_line(self):
        """A small H1 text merges into its next H2; the title drops to Guide > H1 and the H2 becomes a line."""
        own, signs = prose(30, "sun"), prose(100, "pale")
        [merged] = chunks_of(heading(1, "Light"), para(["Light"], own), heading(2, "Signs"),
                             para(["Light", "Signs"], signs), kind="section")
        self.assertEqual(merged["title"], f"{GUIDE} > Light")
        self.assertEqual(merged["content"], f"{own}\n\nSigns\n{signs}")

    def test_merge_stops_at_merge_max(self):
        """A small section does not merge when the result would pass MERGE_MAX."""
        own, signs = prose(30, "sun"), prose(380, "pale")
        self.assertGreater(chunk.chunk_tokens(f"{GUIDE} > Light", f"{own}\n\nSigns\n{signs}"), chunk.MERGE_MAX)
        sections = chunks_of(heading(1, "Light"), para(["Light"], own), heading(2, "Signs"),
                             para(["Light", "Signs"], signs), kind="section")
        self.assertEqual([s["title"] for s in sections], [f"{GUIDE} > Light", f"{GUIDE} > Light > Signs"])
        self.assertEqual(sections[1]["content"], signs)

    def test_merges_chain_while_still_small(self):
        """Two tiny H2s chain into the next one while the merged text is under MIN_TOKENS."""
        a, b, c = prose(15, "ash"), prose(15, "birch"), prose(100, "cedar")
        [merged] = chunks_of(heading(1, "Trees"), heading(2, "A"), para(["Trees", "A"], a),
                             heading(2, "B"), para(["Trees", "B"], b), heading(2, "C"), para(["Trees", "C"], c),
                             kind="section")
        self.assertEqual(merged["title"], f"{GUIDE} > Trees")
        self.assertEqual(merged["content"], f"A\n{a}\n\nB\n{b}\n\nC\n{c}")

    def test_merge_never_crosses_h1_and_small_last_unit_stays_alone(self):
        """A small H1 with no H2s and a small last H2 each stay alone; nothing merges across H1s."""
        sections = chunks_of(heading(1, "One"), para(["One"], prose(20, "ash")),
                             heading(1, "Two"), heading(2, "Big"), para(["Two", "Big"], prose(200, "birch")),
                             heading(2, "Tail"), para(["Two", "Tail"], prose(20, "cedar")), kind="section")
        self.assertEqual([s["title"] for s in sections],
                         [f"{GUIDE} > One", f"{GUIDE} > Two > Big", f"{GUIDE} > Two > Tail"])
        self.assertTrue(all(s["est_tokens"] < chunk.MIN_TOKENS for s in (sections[0], sections[2])))

    def test_introduction_never_merges_into_the_first_h1(self):
        """Introduction is its own H1-level unit, so a short intro stays alone."""
        sections = chunks_of(para(["Introduction"], "Short intro."), heading(1, "Light"),
                             para(["Light"], prose(100, "sun")), kind="section")
        self.assertEqual([s["title"] for s in sections], [f"{GUIDE} > Introduction", f"{GUIDE} > Light"])


class SplitTests(unittest.TestCase):
    def big_section(self, paragraphs=12, topic="leaf"):
        """Blocks for one H1 with many ~100-token paragraphs, each about its own topic."""
        return [heading(1, "Leaves"), *(para(["Leaves"], prose(100, f"{topic}{i}")) for i in range(paragraphs))]

    def test_big_section_splits_into_target_range(self):
        """A section over TARGET_MAX splits at paragraphs into parts within TARGET_MIN..TARGET_MAX, same title."""
        parts = chunks_of(*self.big_section(), kind="section")
        self.assertGreater(len(parts), 1)
        for part in parts:
            self.assertEqual(part["title"], f"{GUIDE} > Leaves")
            self.assertGreaterEqual(part["est_tokens"], chunk.TARGET_MIN)
            self.assertLessEqual(part["est_tokens"], chunk.TARGET_MAX)

    def test_section_at_target_max_stays_whole(self):
        """A section that fits in TARGET_MAX is not split."""
        parts = chunks_of(*self.big_section(paragraphs=3), kind="section")
        self.assertEqual(len(parts), 1)

    def test_long_paragraph_cut_at_sentences_never_over_hard_max(self):
        """One paragraph over HARD_MAX is cut at sentence boundaries only, and no part passes HARD_MAX."""
        text = prose(2000, "frond")
        parts = chunks_of(heading(1, "Fronds"), para(["Fronds"], text), kind="section")
        self.assertGreater(len(parts), 2)
        whole = set(chunk.sentences(text))
        for part in parts:
            self.assertLessEqual(part["est_tokens"], chunk.HARD_MAX)
            self.assertTrue(set(chunk.sentences(part["content"])) <= whole)
        self.assertEqual(set().union(*(chunk.sentences(p["content"]) for p in parts)), whole)

    def test_sentence_split_skips_breaks_inside_quotes(self):
        """A full stop inside curly or straight quotes is not a sentence break."""
        self.assertEqual(chunk.sentences("Water less. The tag says “Dry out. Then soak.” Repeat weekly."),
                         ["Water less.", "The tag says “Dry out. Then soak.” Repeat weekly."])
        self.assertEqual(chunk.sentences('Mist. Then "wait. Then mist." Done! Ok?'),
                         ["Mist.", 'Then "wait. Then mist." Done!', "Ok?"])

    def test_oversized_single_sentence_kept_whole_with_warning(self):
        """A sentence that alone passes HARD_MAX is kept whole and reported by chunk index only."""
        sentence = " ".join(["moss"] * 900) + "."
        chunks, warnings, _ = chunk.chunk_document(guide(heading(1, "Moss"), para(["Moss"], sentence)))
        self.assertEqual(chunks[0]["content"], sentence)
        self.assertGreater(chunks[0]["est_tokens"], chunk.HARD_MAX)
        self.assertEqual(warnings, ["oversized_sentence:0"])

    def test_overlap_only_inside_one_split_section(self):
        """Each later part starts with the last two sentences of the one before; the next section gets none."""
        after = prose(150, "root")
        sections = chunks_of(*self.big_section(), heading(1, "Roots"), para(["Roots"], after), kind="section")
        parts, roots = sections[:-1], sections[-1]
        for previous, current in zip(parts, parts[1:]):
            carried = " ".join(chunk.sentences(previous["content"])[-2:])
            self.assertLessEqual(chunk.est_tokens(carried), chunk.OVERLAP_TOKENS)
            self.assertTrue(current["content"].startswith(carried + "\n\n"))
        self.assertEqual(roots["content"], after)


class TableChunkTests(unittest.TestCase):
    def test_two_and_three_column_lines(self):
        """Each row becomes one line naming the table's own headers."""
        self.assertEqual(chunk.table_lines(grid([], ["What you notice", "What to check"], ["Pale fronds", "Light"])),
                         ["What you notice: Pale fronds -> What to check: Light"])
        self.assertEqual(chunk.table_lines(grid([], ["Sign", "Cause", "Fix"], ["Limp", "Dry", "Soak"])),
                         ["Sign: Limp -> Cause: Dry -> Fix: Soak"])

    def test_empty_cells_skipped_and_empty_header_named_column_n(self):
        """Empty cells are left out and an empty header cell is called Column N."""
        block = grid([], ["Sign", "", "Fix"], ["Pale", "Light", ""], ["", "", ""])
        self.assertEqual(chunk.table_lines(block), ["Sign: Pale -> Column 2: Light"])

    def test_table_title_is_its_section_path(self):
        """A table chunk is titled with the path it sits under."""
        [table_chunk] = chunks_of(heading(1, "Light"), heading(2, "Signs"),
                                  grid(["Light", "Signs"], ["Sign", "Fix"], ["Pale", "Move"]), kind="table")
        self.assertEqual(table_chunk["title"], f"{GUIDE} > Light > Signs")
        self.assertEqual(table_chunk["content"], "Sign: Pale -> Fix: Move")

    def test_big_table_splits_by_rows_without_repeated_header(self):
        """A table over HARD_MAX splits into whole-row parts of at most TARGET_MAX, rows only."""
        rows = [(f"Sign {i} with spots", f"Check the moss tray number {i} and the light") for i in range(60)]
        block = grid(["Light"], ["Sign", "Fix"], *rows)
        lines = chunk.table_lines(block)
        parts = chunks_of(heading(1, "Light"), block, kind="table")
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(p["est_tokens"] <= chunk.TARGET_MAX for p in parts))
        self.assertEqual([line for p in parts for line in p["content"].split("\n")], lines)


class CalloutChunkTests(unittest.TestCase):
    def test_callout_is_its_own_chunk_even_when_short(self):
        """A callout is titled path > box title and its content starts with the box title."""
        [callout] = chunks_of(para(["Introduction"], "Intro."), note(["Introduction"], "Key Tip", "Mist at dawn."),
                              kind="callout")
        self.assertEqual(callout["title"], f"{GUIDE} > Introduction > Key Tip")
        self.assertEqual(callout["content"], "Key Tip: Mist at dawn.")

    def test_callout_keeps_its_line_breaks(self):
        """A multi-line box is not reflowed when it fits."""
        [callout] = chunks_of(note(["Light"], "Safety", "Keep away from cats.\nWash hands."), kind="callout")
        self.assertEqual(callout["content"], "Safety: Keep away from cats.\nWash hands.")


class CardTests(unittest.TestCase):
    def test_card_content_title_and_null_index(self):
        """The card lists summary, keywords and the even-indexed variants, has no index and comes last."""
        chunks = chunks_of(heading(1, "Light"), para(["Light"], "Text."))
        card = chunks[-1]
        self.assertEqual(card["kind"], "card")
        self.assertIsNone(card["chunk_index"])
        self.assertEqual(card["title"], f"{GUIDE} > Overview")
        self.assertEqual(card["content"],
                         "Summary: A made-up summary.\nKeywords: moss, mist\nQuestions:\nq0?\nq2?\nq4?")

    def test_split_variants_even_odd_and_stable(self):
        """Even indices go to the card and odd ones are held out, in order, the same on every call."""
        variants = ["a", "b", "c", "d", "e"]
        self.assertEqual(chunk.split_variants(variants), (["a", "c", "e"], ["b", "d"]))
        self.assertEqual(chunk.split_variants(variants), chunk.split_variants(list(variants)))
        self.assertEqual(variants, ["a", "b", "c", "d", "e"])
        self.assertEqual(chunk.split_variants([]), ([], []))


class ChunkRecordTests(unittest.TestCase):
    def test_chunk_index_follows_document_order_across_kinds(self):
        """Sections, callouts and tables are numbered 0, 1, 2 ... in document order; the card is not counted."""
        chunks = chunks_of(para(["Introduction"], "Intro."), note(["Introduction"], "Tip", "Mist."),
                           heading(1, "A"), para(["A"], "Text A."), grid(["A"], ["Sign", "Fix"], ["Pale", "Move"]),
                           heading(1, "B"), para(["B"], "Text B."))
        self.assertEqual([(c["kind"], c["chunk_index"]) for c in chunks],
                         [("section", 0), ("callout", 1), ("section", 2), ("table", 3), ("section", 4),
                          ("card", None)])

    def test_est_tokens_counts_title_newline_content(self):
        """est_tokens is ceil(characters / 4) of the embedding input title + newline + content."""
        self.assertEqual(chunk.est_tokens(""), 0)
        self.assertEqual(chunk.est_tokens("abcde"), 2)
        for c in chunks_of(heading(1, "A"), para(["A"], "Text A."), note(["A"], "Tip", "Mist.")):
            self.assertEqual(c["est_tokens"], -(-len(c["title"] + "\n" + c["content"]) // 4))

    def test_record_fields_copied_from_the_guide(self):
        """Every record has the output keys and carries the guide's id, review status and care topics."""
        for c in chunks_of(heading(1, "A"), para(["A"], "Text A.")):
            self.assertEqual(set(c), {"hpa_id", "chunk_index", "kind", "title", "content", "review_status",
                                      "care_topics", "est_tokens"})
            self.assertEqual((c["hpa_id"], c["review_status"], c["care_topics"]),
                             ("HPA-TEST-0001", "pending", ["watering"]))



class GuideIdTests(unittest.TestCase):
    TITLES = {"HPA-TEST-0001": GUIDE, "HPA-FUND-0002": "Misting Basics"}

    def chunk_with_ids(self, *blocks):
        """Chunk a made-up guide with a two-guide batch."""
        doc = guide(*blocks)
        doc["related"] = ["HPA-FUND-0002"]
        return doc, chunk.chunk_document(doc, self.TITLES)

    def test_ids_in_the_batch_become_titles_in_every_kind(self):
        """Prefixed and bare ids in paragraphs, lists, tables and callouts become the guide title."""
        _, (chunks, _, replaced) = self.chunk_with_ids(
            heading(1, "Light"), para(["Light"], "See HPA-FUND-0002 next."), bullets(["Light"], "Try FUND-0002"),
            grid(["Light"], ["Sign", "Next guide"], ["Pale", "HPA-FUND-0002"]),
            note(["Light"], "Tip", "Read FUND-0002."))
        body = [c for c in chunks if c["kind"] != "card"]
        self.assertEqual([c["content"] for c in body], [
            "See Misting Basics next.\n\n- Try Misting Basics", "Sign: Pale -> Next guide: Misting Basics",
            "Tip: Read Misting Basics."])
        self.assertEqual(replaced, 4)
        self.assertFalse(any(chunk.GUIDE_ID.search(c["content"]) for c in chunks))

    def test_unknown_id_becomes_a_related_guide(self):
        """An id outside the batch is replaced with a neutral phrase and still counted."""
        _, (chunks, _, replaced) = self.chunk_with_ids(heading(1, "Pests"), para(["Pests"], "See HPA-PEST-0042."))
        self.assertEqual(chunks[0]["content"], "See a related guide.")
        self.assertEqual(replaced, 1)

    def test_doc_json_and_related_ids_are_untouched(self):
        """Replacement works on a copy: the doc's blocks and related ids keep the real ids."""
        doc, _ = self.chunk_with_ids(heading(1, "Light"), para(["Light"], "See HPA-FUND-0002."))
        self.assertEqual(doc["blocks"][1]["text"], "See HPA-FUND-0002.")
        self.assertEqual(doc["related"], ["HPA-FUND-0002"])

    def test_full_stop_after_a_title_ending_in_punctuation_is_dropped(self):
        """'?.' becomes '?' when the title ends with its own punctuation; other titles keep the stop."""
        titles = {"HPA-TEST-0001": GUIDE, "HPA-FUND-0002": "Why is it wilting?", "HPA-FUND-0003": "Misting Basics"}
        chunks, _, _ = chunk.chunk_document(guide(heading(1, "Light"), para(
            ["Light"], "Read HPA-FUND-0002. Then FUND-0003. Done.")), titles)
        self.assertEqual(chunks[0]["content"], "Read Why is it wilting? Then Misting Basics. Done.")


# ---------------------------------------------------------------------------
# build_rows.py
# ---------------------------------------------------------------------------

CREATOR = "11111111-2222-4333-8444-555555555555"


def chunk_record(hpa_id="HPA-TEST-0001", index=0, kind="section", topics=("moss", "light")):
    """Build a chunks.jsonl record with made-up text."""
    return {"hpa_id": hpa_id, "chunk_index": None if kind == "card" else index, "kind": kind,
            "title": f"Moss Guide > Part {index}", "content": f"Moss text {index}.",
            "review_status": "pending", "care_topics": list(topics), "est_tokens": 9}


def doc_record(hpa_id="HPA-TEST-0001", title="Moss Guide"):
    """Build the doc.json fields build_rows reads."""
    return {"hpa_id": hpa_id, "title": title}


def demo_sql(count=8):
    """Build a made-up seed insert with count demo entries, each title holding an escaped quote."""
    rows = [f"""  (
    '89000000-0000-4000-8000-{n:012d}', v_creator_id, 'question',
    'Why won''t moss {n} grow?',
    $t$Moss {n} line one.

It's line two.$t$,
    array['moss'], true
  )""" for n in range(1, count + 1)]
    return ("insert into public.knowledge_entries (id, creator_id, source, title, content, tags, published)\n"
            "values\n" + ",\n".join(rows) + "\non conflict (id) do nothing;\n")


class FakeEmbed:
    """Stand-in for llm.embed: one distinct short vector per input, and a record of every call."""

    def __init__(self):
        """Start with no calls."""
        self.calls = []

    def __call__(self, texts, *, retry=False, timeout=None):
        """Record the call and return [[i]] per input with fixed meta."""
        self.calls.append({"texts": list(texts), "retry": retry, "timeout": timeout})
        return [[float(i)] for i in range(len(texts))], {"model": "fake-embed", "tokens": 42, "latency_ms": 1}


class BuildRowsTests(unittest.TestCase):
    def build(self, chunks, docs=(doc_record(),), demo=()):
        """Run build_rows with a fake embed; return (records, the fake)."""
        fake = FakeEmbed()
        with patch.object(build_rows.llm, "embed", fake):
            records, _ = build_rows.build_rows(list(chunks), list(docs), list(demo), CREATOR)
        return records, fake

    def test_ids_are_stable_across_runs_and_differ_across_guides(self):
        """Two runs give the same ids; a second guide gets different doc and entry ids."""
        chunks = [chunk_record("HPA-TEST-0001", 0), chunk_record("HPA-TEST-0002", 0)]
        docs = [doc_record("HPA-TEST-0001"), doc_record("HPA-TEST-0002", "Fern Guide")]
        first, _ = self.build(chunks, docs)
        second, _ = self.build(chunks, docs)
        ids = [r["id"] for r in first]
        self.assertEqual(ids, [r["id"] for r in second])
        self.assertEqual(len(set(ids)), 4)
        self.assertEqual(first[0]["id"], str(uuid.uuid5(build_rows.NAMESPACE, "doc:HPA-TEST-0001")))
        self.assertEqual(first[2]["id"], str(uuid.uuid5(build_rows.NAMESPACE, "HPA-TEST-0001:0")))

    def test_card_id_uses_card_suffix(self):
        """The doc card has no chunk index, so its id is uuid5 of '<hpa_id>:card'."""
        card = chunk_record(kind="card")
        self.assertEqual(build_rows.entry_id(card), str(uuid.uuid5(build_rows.NAMESPACE, "HPA-TEST-0001:card")))

    def test_tags_are_ordered_and_deduplicated(self):
        """hpa, kind, review, then each topic once, in first-seen order."""
        tags = build_rows.entry_tags(chunk_record(kind="table", topics=("moss", "light", "moss")))
        self.assertEqual(tags, ["hpa:HPA-TEST-0001", "kind:table", "review:pending", "topic:moss", "topic:light"])

    def test_record_shapes_and_embedding_inputs(self):
        """Doc rows, then entry rows, then demo set_embedding rows, with the embed inputs to match."""
        demo = [{"id": build_rows.DEMO_IDS[0], "title": "Demo title", "content": "Demo text."}]
        records, fake = self.build([chunk_record(index=0), chunk_record(kind="card")], demo=demo)
        self.assertEqual(records[0], {"table": "knowledge_docs", "op": "upsert",
                                      "id": build_rows.doc_id("HPA-TEST-0001"), "creator_id": CREATOR,
                                      "title": "Moss Guide", "storage_path": f"{CREATOR}/HPA-TEST-0001.docx"})
        self.assertEqual(records[1], {"table": "knowledge_entries", "op": "upsert",
                                      "id": build_rows.entry_id(chunk_record(index=0)), "creator_id": CREATOR,
                                      "doc_id": records[0]["id"], "question_id": None, "source": "doc",
                                      "title": "Moss Guide > Part 0", "content": "Moss text 0.",
                                      "tags": ["hpa:HPA-TEST-0001", "kind:section", "review:pending",
                                               "topic:moss", "topic:light"],
                                      "published": False, "embedding": [0.0]})
        self.assertEqual(records[2]["tags"][1], "kind:card")
        self.assertEqual(records[3], {"table": "knowledge_entries", "op": "set_embedding",
                                      "id": build_rows.DEMO_IDS[0], "embedding": [2.0]})
        self.assertEqual(fake.calls, [{"texts": ["Moss Guide > Part 0\nMoss text 0.", "Moss Guide > Part 0\nMoss text 0.",
                                                 "Demo title\nDemo text."], "retry": True, "timeout": 60}])

    def test_chunks_without_a_doc_are_rejected(self):
        """A chunk whose guide has no doc.json stops the build before any embedding."""
        fake = FakeEmbed()
        with patch.object(build_rows.llm, "embed", fake), self.assertRaisesRegex(ValueError, "HPA-TEST-0002"):
            build_rows.build_rows([chunk_record("HPA-TEST-0002")], [doc_record()], [], CREATOR)
        self.assertEqual(fake.calls, [])

    def test_seed_parser_reads_quoted_title_and_dollar_block(self):
        """'' in a title becomes ', and the $t$ block is kept exactly, blank line and quote included."""
        entries = build_rows.parse_demo_entries(demo_sql())
        self.assertEqual([e["id"] for e in entries], list(build_rows.DEMO_IDS))
        self.assertEqual(entries[2]["title"], "Why won't moss 3 grow?")
        self.assertEqual(entries[2]["content"], "Moss 3 line one.\n\nIt's line two.")

    def test_seed_parser_requires_exactly_eight(self):
        """Seven demo entries is an error, not a partial result."""
        with self.assertRaisesRegex(ValueError, "found 7"):
            build_rows.parse_demo_entries(demo_sql(7))

    def run_main(self, folder, *extra, seed_count=8):
        """Write made-up inputs to folder and run build_rows.main; return (stdout, the fake embed)."""
        folder = Path(folder)
        (folder / "docs").mkdir()
        (folder / "docs" / "HPA-TEST-0001.json").write_text(json.dumps(doc_record()))
        (folder / "chunks.jsonl").write_text(json.dumps(chunk_record()) + "\n")
        (folder / "seed.sql").write_text(demo_sql(seed_count))
        fake, out = FakeEmbed(), io.StringIO()
        argv = ["--chunks", str(folder / "chunks.jsonl"), "--docs", str(folder / "docs"),
                "--seed", str(folder / "seed.sql"), "--out", str(folder / "rows.jsonl"), *extra]
        with patch.object(build_rows.llm, "embed", fake), contextlib.redirect_stdout(out):
            build_rows.main(argv)
        return out.getvalue(), fake

    def test_main_writes_rows_and_prints_counts(self):
        """One guide, one chunk and 8 demo entries give 10 records and a counts line."""
        with tempfile.TemporaryDirectory() as folder:
            printed, _ = self.run_main(folder, "--creator-id", CREATOR.upper())
            records = [json.loads(line) for line in (Path(folder) / "rows.jsonl").read_text().splitlines()]
        self.assertEqual(len(records), 10)
        self.assertEqual(records[0]["creator_id"], CREATOR)
        self.assertIn("guides=1 chunks=1 demo_entries=8", printed)
        self.assertIn("tokens=42", printed)
        self.assertNotIn(CREATOR, printed)

    def test_wrong_demo_count_exits_before_embedding(self):
        """A seed with 7 demo entries exits non-zero and never calls embed."""
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(SystemExit) as caught:
            self.run_main(folder, "--creator-id", CREATOR, seed_count=7)
        self.assertNotIn(caught.exception.code, (0, None))
        self.assertFalse((Path(folder) / "rows.jsonl").exists())

    def test_invalid_creator_id_is_rejected_without_echo(self):
        """A creator id that is not a UUID exits with code 2, and the message does not repeat it."""
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as caught:
            build_rows.main(["--creator-id", "creator-typo-123"])
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("must be a UUID", err.getvalue())
        self.assertNotIn("creator-typo-123", err.getvalue())


# ---------------------------------------------------------------------------
# load_kb.py
# ---------------------------------------------------------------------------

BASE_URL = "https://example.supabase.co"
KEY = "test-service-key"
ENV = {"SUPABASE_URL": BASE_URL, "SUPABASE_SERVICE_ROLE_KEY": KEY}


def doc_id_n(n):
    """A made-up doc uuid."""
    return f"d0000000-0000-4000-8000-{n:012d}"


def entry_id_n(doc, n):
    """A made-up entry uuid for doc number doc."""
    return f"e{doc:07d}-0000-4000-8000-{n:012d}"


def rows_file(folder, entries_per_doc=(2, 1), demo=2):
    """Write a made-up rows.jsonl (docs, entries, demo vectors) and return its path."""
    records = [{"table": "knowledge_docs", "op": "upsert", "id": doc_id_n(d), "creator_id": CREATOR,
                "title": f"Guide {d}", "storage_path": f"{CREATOR}/HPA-TEST-{d:04d}.docx"}
               for d in range(1, len(entries_per_doc) + 1)]
    for d, count in enumerate(entries_per_doc, 1):
        records += [{"table": "knowledge_entries", "op": "upsert", "id": entry_id_n(d, n), "creator_id": CREATOR,
                     "doc_id": doc_id_n(d), "question_id": None, "source": "doc", "title": "t", "content": "c",
                     "tags": ["kind:section"], "published": False, "embedding": [0.5, 0.25]}
                    for n in range(count)]
    records += [{"table": "knowledge_entries", "op": "set_embedding", "id": build_rows.DEMO_IDS[i],
                 "embedding": [0.125]} for i in range(demo)]
    path = Path(folder) / "rows.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


class FakeTransport:
    """Stand-in for load_kb.urllib_transport: records requests and answers from a function, no network."""

    def __init__(self, answer=None):
        """answer(method, url) -> (status, data) overrides the defaults (201/204/200 with [{"id"}] for PATCH)."""
        self.answer = answer
        self.calls = []

    def __call__(self, method, url, headers, body=None):
        """Record the request and return the answer."""
        self.calls.append({"method": method, "url": url, "headers": headers, "body": body})
        if self.answer:
            reply = self.answer(method, url)
            if reply is not None:
                return reply
        return {"POST": (201, None), "DELETE": (204, None), "PATCH": (200, [{"id": "x"}]), "GET": (200, [])}[method]


@patch.dict(os.environ, ENV)
class LoadKbTests(unittest.TestCase):
    def run_load(self, *extra, entries_per_doc=(2, 1), demo=2, answer=None):
        """Run load_kb.main on a made-up rows file; return (transport, stdout)."""
        transport, out = FakeTransport(answer), io.StringIO()
        with tempfile.TemporaryDirectory() as folder:
            path = rows_file(folder, entries_per_doc, demo)
            with contextlib.redirect_stdout(out):
                load_kb.main(["--rows", str(path), *extra], transport=transport)
        return transport, out.getvalue()

    def test_request_order(self):
        """Docs upsert, entries upsert, one stale delete per guide, then one PATCH per demo entry."""
        transport, printed = self.run_load()
        steps = [(c["method"], c["url"].split("?")[0].rsplit("/", 1)[1]) for c in transport.calls]
        self.assertEqual(steps, [("POST", "knowledge_docs"), ("POST", "knowledge_entries"),
                                 ("DELETE", "knowledge_entries"), ("DELETE", "knowledge_entries"),
                                 ("PATCH", "knowledge_entries"), ("PATCH", "knowledge_entries")])
        self.assertIn("docs=2  entries=3", printed)

    def test_upsert_url_headers_and_body(self):
        """POST ?on_conflict=id with merge-duplicates, service-role headers, and rows without table or op."""
        transport, _ = self.run_load()
        docs, entries = transport.calls[0], transport.calls[1]
        self.assertEqual(docs["url"], f"{BASE_URL}/rest/v1/knowledge_docs?on_conflict=id")
        self.assertEqual(docs["headers"], {"apikey": KEY, "Authorization": f"Bearer {KEY}",
                                           "Content-Type": "application/json",
                                           "Prefer": "resolution=merge-duplicates,return=minimal"})
        self.assertEqual(docs["body"][0], {"id": doc_id_n(1), "creator_id": CREATOR, "title": "Guide 1",
                                           "storage_path": f"{CREATOR}/HPA-TEST-0001.docx"})
        self.assertEqual(entries["url"], f"{BASE_URL}/rest/v1/knowledge_entries?on_conflict=id")
        self.assertTrue(all("table" not in row and "op" not in row for row in entries["body"]))
        self.assertEqual(entries["body"][0]["embedding"], [0.5, 0.25])

    def test_entries_upsert_in_batches_of_50(self):
        """120 entries go in requests of 50, 50 and 20."""
        transport, _ = self.run_load(entries_per_doc=(70, 50))
        sizes = [len(c["body"]) for c in transport.calls if c["url"].endswith("knowledge_entries?on_conflict=id")]
        self.assertEqual(sizes, [50, 50, 20])

    def test_stale_delete_uses_not_in_with_that_guides_ids(self):
        """Each guide's DELETE keeps exactly the ids just loaded for that guide."""
        transport, _ = self.run_load()
        deletes = [c for c in transport.calls if c["method"] == "DELETE"]
        self.assertEqual(deletes[0]["url"], f"{BASE_URL}/rest/v1/knowledge_entries?doc_id=eq.{doc_id_n(1)}"
                                            f"&id=not.in.({entry_id_n(1, 0)},{entry_id_n(1, 1)})")
        self.assertEqual(deletes[1]["url"], f"{BASE_URL}/rest/v1/knowledge_entries?doc_id=eq.{doc_id_n(2)}"
                                            f"&id=not.in.({entry_id_n(2, 0)})")
        self.assertIsNone(deletes[0]["body"])

    def test_demo_patch_filter_body_and_counts(self):
        """PATCH only where embedding is null, body is only the embedding, empty reply counts as already set."""
        demo_one = build_rows.DEMO_IDS[1]
        transport, printed = self.run_load(
            answer=lambda method, url: (200, []) if method == "PATCH" and demo_one in url else None)
        patches = [c for c in transport.calls if c["method"] == "PATCH"]
        self.assertEqual(patches[0]["url"], f"{BASE_URL}/rest/v1/knowledge_entries"
                                            f"?id=eq.{build_rows.DEMO_IDS[0]}&embedding=is.null&select=id")
        self.assertEqual(patches[0]["body"], {"embedding": [0.125]})
        self.assertEqual(patches[0]["headers"]["Prefer"], "return=representation")
        self.assertIn("demo_updated=1  demo_already_set=1", printed)

    def test_dry_run_only_reads(self):
        """--dry-run makes GET requests only and reports stale ids, demo updates and extra docs."""
        stale_id = entry_id_n(1, 9)
        extra_doc = doc_id_n(9)

        def answer(method, url):
            """Serve one stale chunk for guide 1, one demo still null, and one extra doc."""
            if f"doc_id=eq.{doc_id_n(1)}" in url:
                return 200, [{"id": stale_id}]
            if "embedding=is.null" in url:
                return 200, [{"id": build_rows.DEMO_IDS[0]}]
            if url.startswith(f"{BASE_URL}/rest/v1/knowledge_docs?"):
                return 200, [{"id": doc_id_n(1)}, {"id": extra_doc}]
            return None

        transport, printed = self.run_load("--dry-run", answer=answer)
        self.assertEqual({c["method"] for c in transport.calls}, {"GET"})
        self.assertEqual(transport.calls[0]["url"], f"{BASE_URL}/rest/v1/knowledge_entries?doc_id=eq.{doc_id_n(1)}"
                                                    f"&id=not.in.({entry_id_n(1, 0)},{entry_id_n(1, 1)})&select=id")
        self.assertEqual(transport.calls[3]["url"], f"{BASE_URL}/rest/v1/knowledge_docs"
                                                    f"?creator_id=eq.{CREATOR}&select=id")
        self.assertIn(f"HPA-TEST-0001  upsert=2  stale=1  stale_ids={stale_id}", printed)
        self.assertIn("demo_would_update=1  demo_already_set=1", printed)
        self.assertIn(f"not in the rows file (not deleted): {extra_doc}", printed)
        self.assertNotIn(CREATOR, printed)
        self.assertNotIn(KEY, printed)

    def test_http_error_exits_naming_step_and_status(self):
        """A failed entries upsert exits non-zero with the step and status, and no later step runs."""
        def answer(method, url):
            """Fail the entries upsert."""
            return (500, None) if method == "POST" and "knowledge_entries" in url else None

        transport = FakeTransport(answer)
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(SystemExit) as caught:
            load_kb.main(["--rows", str(rows_file(folder))], transport=transport)
        self.assertIn("upsert knowledge_entries failed (HTTP 500)", str(caught.exception.code))
        self.assertEqual([c["method"] for c in transport.calls], ["POST", "POST"])

    def test_network_error_also_exits(self):
        """A transport that got no status (network error) is an error, not a success."""
        with self.assertRaises(SystemExit) as caught:
            self.run_load(answer=lambda method, url: (None, None))
        self.assertIn("upsert knowledge_docs failed (HTTP network error)", str(caught.exception.code))

    def test_missing_env_names_the_variable_without_values(self):
        """A missing key stops before any request, naming the variable and echoing no value."""
        transport = FakeTransport()
        with patch.dict(os.environ, {"SUPABASE_SERVICE_ROLE_KEY": ""}), self.assertRaises(SystemExit) as caught:
            load_kb.main(["--rows", "unused.jsonl"], transport=transport)
        message = str(caught.exception.code)
        self.assertIn("SUPABASE_SERVICE_ROLE_KEY", message)
        self.assertNotIn(BASE_URL, message)
        self.assertEqual(transport.calls, [])


if __name__ == "__main__":
    unittest.main()
