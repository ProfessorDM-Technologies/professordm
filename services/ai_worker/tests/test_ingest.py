"""Unit tests for ingest/parse.py and ingest/normalize.py.

Every fixture is a hand-built list of raw elements (the shape read_docx
returns) with made-up text, so no .docx file, no python-docx and no network
are needed. Run with:
    uv run --python 3.11 python -m unittest discover services/ai_worker/tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))

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


if __name__ == "__main__":
    unittest.main()
