# /// script
# requires-python = ">=3.11"
# dependencies = ["python-docx"]
# ///
"""Turn each guide's metadata and body into one clean doc.json.

Ingest step 2 of 5 (spec sections 3.2, 14.1 and 14.7). Reads every .docx in
the input folder with parse.py, reads the internal metadata after the cut
heading, and writes private/docs/<hpa_id>.json per guide. The metadata is
never embedded, shown to members or sent to a model; only the fields below
are kept, for chunk titles, tags and the retrieval eval.

Contents:
    ALIASES, LABEL_KEYS, PLACEHOLDERS   the metadata vocabulary, in one place
    extract_metadata    tail -> (machine-key values, routing-table values)
    metadata_template   which of the three metadata templates a guide uses
    split_list          the one list-splitting rule (";", "|", "?", ",")
    question_variants   metadata and routing variants, merged and deduplicated
    snake_case          the shared care-topic normalizer
    related_ids         related guide ids from metadata, routing and the tail
    normalize_document  raw elements -> the doc.json dict
    check_unique        refuses two input files with the same hpa_id
    main                the CLI

Usage (from the repo root):
    uv run services/ai_worker/ingest/normalize.py [--input DIR] [--out DIR]

Depends on: parse.py (and through it python-docx, for reading only). The
logic here is standard library and is tested on hand-built fixtures.

Never does: call a model, touch the network or the database, or print guide
text. The CLI prints one row of counts per guide; file names and ids only.
"""

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

import parse


HERE = Path(__file__).resolve().parent
# Default folders, both under the git-ignored private/.
INPUT_DIR = HERE / "private" / "input"
OUTPUT_DIR = HERE / "private" / "docs"

# Machine keys that mean the same thing in different guide templates. Applied
# to every key before lookup, so the rest of the code uses one name.
ALIASES = {
    "urgency_level": "urgency",
    "version": "content_version",
}

# Bold column-1 labels of the label template (TROUBLE-0001) mapped to the
# machine keys of the other templates. Labels not listed are ignored. "Status"
# is the publication status the guide marks approved; the separate "Expert
# Review Status" row is deliberately not mapped.
LABEL_KEYS = {
    "content id": "content_id",
    "full title": "content_title",
    "status": "expert_review_status",
    "version": "content_version",
    "search keywords": "search_keywords",
    "natural language queries": "search_question_variants",
    "primary topic": "primary_topic",
    "secondary topics": "secondary_topics",
    "urgency level": "urgency",
    "related content ids": "related_content_ids",
}

# A table is a label table when at least this many column-1 cells are known
# labels, so an ordinary 2-column table with one matching word is not read as
# metadata.
MIN_LABEL_MATCHES = 2

# Values that mean "no value". Matched at the start, case-insensitive, because
# real values carry a note ("NOT POPULATED - broad cross-group guide").
PLACEHOLDERS = re.compile(r"^\s*(?:not populated|not applicable|not assigned|not set)\b", re.IGNORECASE)

# Header rows that identify each metadata template, compared casefolded.
FOUR_COLUMN_HEADER = ("field", "machine key", "assigned value")
THREE_COLUMN_HEADER = ("machine key", "assigned value")
ROUTING_HEADERS = {"element", "routing field"}

# Routing-table labels (casefolded) that hold question variants and the summary.
ROUTING_QUESTIONS = ("natural-language queries", "natural-language routing")
ROUTING_SUMMARY = "result summary"
ROUTING_LINKS = "internal linking"

# A guide id with or without the "HPA-" prefix ("FUND-0001" in FUND-0005).
RELATED_ID = re.compile(r"\b(?:HPA-)?([A-Z]{3,8}-\d{4})\b")

# Characters folded to their straight forms before comparing variants.
QUOTE_FOLD = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})


def _clean(value):
    """Collapse whitespace in a cell value and turn placeholders into None.

    Args:
        value (str | None): A raw metadata value.

    Returns:
        str | None: The value with whitespace collapsed, or None if it is
        empty or starts with a PLACEHOLDERS phrase.

    Side effects: none.
    """
    if value is None:
        return None
    value = " ".join(value.split())
    return None if not value or PLACEHOLDERS.match(value) else value


def _key(text):
    """Normalize a machine key and apply ALIASES.

    Args:
        text (str): The key cell text, for example "urgency_level".

    Returns:
        str: The lowercase key with aliases resolved, for example "urgency".

    Side effects: none.
    """
    key = "_".join(text.strip().lower().split())
    return ALIASES.get(key, key)


def _header(row):
    """Casefold and trim a table's first row for template detection.

    Args:
        row (list[str]): A table row.

    Returns:
        tuple[str, ...]: The folded cells.

    Side effects: none.
    """
    return tuple(" ".join(cell.casefold().split()) for cell in row)


def _label_rows(rows):
    """Return the known-label rows of a 2-column table, or [] if it is not a label table.

    Args:
        rows (list[list[str]]): The table rows.

    Returns:
        list[tuple[str, str]]: (machine key, raw value) for each row whose
        column-1 label is in LABEL_KEYS, when at least MIN_LABEL_MATCHES rows
        match and every row has 2 cells; otherwise [].

    Side effects: none.
    """
    if not rows or any(len(row) != 2 for row in rows):
        return []
    matches = [(LABEL_KEYS[label], row[1]) for row in rows
               if (label := " ".join(row[0].casefold().split()).rstrip(":")) in LABEL_KEYS]
    return matches if len(matches) >= MIN_LABEL_MATCHES else []


def extract_metadata(tail):
    """Read the metadata and routing tables after the cut heading.

    Handles the three templates: 4-column (key in column 2, value in column
    3), 3-column split across several tables (merged), and label tables
    (2 columns, no header). A value from a label table never overrides the
    same key from a machine-key table.

    Args:
        tail (list[dict]): split_document(...)["tail"].

    Returns:
        tuple[dict, dict]: (meta, routing). meta maps machine key (aliases
        applied) to the raw value with whitespace collapsed; routing maps the
        routing-table label (casefolded) to its value. Placeholders are kept
        raw here; callers clean them.

    Side effects: none.
    """
    meta, labelled, routing = {}, {}, {}
    for element in tail:
        if element["kind"] != "table" or not element["rows"]:
            continue
        rows = element["rows"]
        header = _header(rows[0])
        if header[:3] == FOUR_COLUMN_HEADER:
            pairs = [(row[1], row[2]) for row in rows[1:] if len(row) >= 3]
        elif header[:2] == THREE_COLUMN_HEADER:
            pairs = [(row[0], row[1]) for row in rows[1:] if len(row) >= 2]
        elif header and header[0] in ROUTING_HEADERS:
            for row in rows[1:]:
                if len(row) >= 2 and row[0].strip():
                    routing.setdefault(" ".join(row[0].casefold().split()), " ".join(row[1].split()))
            continue
        else:
            for key, value in _label_rows(rows):
                labelled.setdefault(key, " ".join(value.split()))
            continue
        for key, value in pairs:
            if key.strip():
                meta.setdefault(_key(key), " ".join(value.split()))
    return {**labelled, **meta}, routing


def metadata_template(tail):
    """Name the metadata template a guide uses.

    Args:
        tail (list[dict]): split_document(...)["tail"].

    Returns:
        str | None: "four_column", "three_column" or "label", or None if no
        metadata table was found. Only the label template splits keyword and
        topic lists on commas.

    Side effects: none.
    """
    for element in tail:
        if element["kind"] == "table" and element["rows"]:
            header = _header(element["rows"][0])
            if header[:3] == FOUR_COLUMN_HEADER:
                return "four_column"
            if header[:2] == THREE_COLUMN_HEADER:
                return "three_column"
    if any(element["kind"] == "table" and _label_rows(element["rows"]) for element in tail):
        return "label"
    return None


def split_list(value, *, questions=False, commas=False):
    """Split a metadata value into a list (the one splitting rule).

    Args:
        value (str | None): The raw value.
        questions (bool): Split after each "?" when there is no ";" or "|"
            (newer guides write "Does X? Does Y?").
        commas (bool): Split on "," when there is no ";" or "|" (label
            template keyword and topic fields only).

    Returns:
        list[str]: Trimmed items, empties dropped. [] for None or a
        placeholder. Uses ";" if present, else "|", else the "?" or ","
        rule, else the whole value as one item.

    Side effects: none.
    """
    value = _clean(value)
    if value is None:
        return []
    if ";" in value:
        parts = value.split(";")
    elif "|" in value:
        parts = value.split("|")
    elif questions and "?" in value:
        parts = re.split(r"(?<=\?)", value)
    elif commas:
        parts = value.split(",")
    else:
        parts = [value]
    return [part.strip() for part in parts if part.strip()]


def _variant_key(text):
    """Fold a question variant for duplicate detection.

    Args:
        text (str): A question variant.

    Returns:
        str: Casefolded, whitespace collapsed, curly quotes and apostrophes
        straightened, trailing "?", "." and "!" stripped.

    Side effects: none.
    """
    return " ".join(text.translate(QUOTE_FOLD).casefold().split()).rstrip("?.! ")


def dedupe_variants(*lists):
    """Merge variant lists in order, keeping the first original of each duplicate.

    Args:
        *lists (list[str]): Variant lists, highest priority first.

    Returns:
        list[str]: The merged list.

    Side effects: none.
    """
    merged, seen = [], set()
    for items in lists:
        for item in items:
            key = _variant_key(item)
            if key and key not in seen:
                seen.add(key)
                merged.append(item)
    return merged


def variant_lists(meta, routing):
    """Return the metadata and routing question-variant lists, each deduplicated.

    Args:
        meta (dict): From extract_metadata.
        routing (dict): From extract_metadata.

    Returns:
        tuple[list[str], list[str]]: (from search_question_variants, from the
        routing table's natural-language queries or routing row).

    Side effects: none.
    """
    from_meta = split_list(meta.get("search_question_variants"), questions=True)
    from_routing = next((split_list(routing[label], questions=True) for label in ROUTING_QUESTIONS
                         if label in routing), [])
    return dedupe_variants(from_meta), dedupe_variants(from_routing)


def question_variants(meta, routing):
    """Return every question variant, metadata first, deduplicated.

    Args:
        meta (dict): From extract_metadata.
        routing (dict): From extract_metadata.

    Returns:
        list[str]: The union of variant_lists, metadata order first.

    Side effects: none.
    """
    return dedupe_variants(*variant_lists(meta, routing))


def snake_case(text):
    """Normalize a care topic to snake_case so topic tags match across guides.

    Args:
        text (str): A topic, for example "Light & Acclimation".

    Returns:
        str: For example "light_and_acclimation". Accents are dropped,
        "&" becomes "and", every other non-alphanumeric run becomes one "_".

    Side effects: none.
    """
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = text.lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def care_topics(meta, label_template):
    """Return the guide's care topics, snake_cased and deduplicated.

    Args:
        meta (dict): From extract_metadata.
        label_template (bool): True for the label template, which stores
            primary_topic and secondary_topics as comma lists.

    Returns:
        list[str]: Topics in source order.

    Side effects: none.
    """
    if label_template:
        raw = [*split_list(meta.get("primary_topic"), commas=True),
               *split_list(meta.get("secondary_topics"), commas=True)]
    else:
        raw = split_list(meta.get("care_topic"))
    topics = []
    for topic in map(snake_case, raw):
        if topic and topic not in topics:
            topics.append(topic)
    return topics


def review_status(value):
    """Map the guide's review status to "approved" or "pending".

    Args:
        value (str | None): The expert_review_status value.

    Returns:
        str: "approved" only when the value is exactly "approved" (any case);
        anything else, including a missing value, is "pending".

    Side effects: none.
    """
    return "approved" if (_clean(value) or "").casefold() == "approved" else "pending"


def _related_section_text(tail):
    """Collect the tail text that lists related guides.

    Args:
        tail (list[dict]): split_document(...)["tail"].

    Returns:
        list[str]: Paragraph texts under any heading that mentions "related",
        up to the next heading. Covers both "Related Academy Entries" (the
        cut heading itself) and an H2 "Related Academy entries" under a
        combined cut heading.

    Side effects: none.
    """
    texts, inside = [], False
    for element in tail:
        if element["kind"] != "paragraph":
            continue
        if parse.heading_level(element.get("style")) is not None:
            inside = "related" in element["text"].casefold()
        elif inside:
            texts.append(element["text"])
    return texts


def related_ids(hpa_id, meta, routing, tail):
    """Collect the ids of related guides (kept for cross-links, never embedded).

    Args:
        hpa_id (str): The guide's own id, dropped from the result.
        meta (dict): From extract_metadata (related_content_ids).
        routing (dict): From extract_metadata ("internal linking").
        tail (list[dict]): For the related-entries section text.

    Returns:
        list[str]: "HPA-XXXX-NNNN" ids in first-seen order, deduplicated. Bare
        ids such as "FUND-0001" get the "HPA-" prefix.

    Side effects: none.
    """
    sources = [_clean(meta.get("related_content_ids")) or "", routing.get(ROUTING_LINKS) or "",
               *_related_section_text(tail)]
    ids = []
    for text in sources:
        for match in RELATED_ID.finditer(text):
            found = f"HPA-{match.group(1)}"
            if found != hpa_id and found not in ids:
                ids.append(found)
    return ids


def _references(tail):
    """Return the reference texts after the cut heading.

    Args:
        tail (list[dict]): split_document(...)["tail"].

    Returns:
        list[str]: Non-empty, non-heading paragraph texts after the cut
        heading, up to the first table. Kept for provenance, never embedded.

    Side effects: none.
    """
    texts = []
    for element in tail[1:]:
        if element["kind"] == "table":
            break
        if parse.heading_level(element.get("style")) is None and element["text"].strip():
            texts.append(element["text"])
    return texts


def _summary(meta, routing, blocks):
    """Pick the guide summary from the best available source.

    Args:
        meta (dict): content_summary, if present.
        routing (dict): "result summary", if present.
        blocks (list[dict]): From parse.body_blocks.

    Returns:
        str | None: content_summary, else the routing result summary, else the
        first Introduction paragraph, else the first body paragraph, else None.

    Side effects: none.
    """
    paragraphs = [block for block in blocks if block["type"] == "paragraph"]
    intro = next((b["text"] for b in paragraphs if b["path"] == [parse.INTRO]), None)
    return (_clean(meta.get("content_summary")) or _clean(routing.get(ROUTING_SUMMARY)) or intro
            or (paragraphs[0]["text"] if paragraphs else None))


def normalize_document(elements, source_file):
    """Turn one guide's raw elements into the doc.json dict.

    Args:
        elements (list[dict]): From parse.read_docx.
        source_file (str): The .docx file name, stored for provenance.

    Returns:
        dict: {"hpa_id", "title", "summary", "keywords", "question_variants",
        "care_topics", "urgency", "review_status", "content_version",
        "related", "blocks", "references", "source_file", "warnings"}.
        warnings holds short codes only: "no_cut_heading", "no_title",
        "no_summary".

    Raises:
        ValueError: If the guide has no content_id.

    Side effects: none.
    """
    parts = parse.split_document(elements)
    # Without a cut heading the metadata tables sit in the body; read them
    # from the whole document so the guide still gets its id (with a warning).
    metadata_source = parts["tail"] if parts["cut_found"] else elements
    meta, routing = extract_metadata(metadata_source)
    hpa_id = _clean(meta.get("content_id"))
    if not hpa_id:
        raise ValueError(f"{source_file}: no content_id in the metadata")
    label_template = metadata_template(metadata_source) == "label"
    title = _clean(meta.get("content_title"))
    blocks = parse.body_blocks(parts["body"], title)
    summary = _summary(meta, routing, blocks)
    warnings = [code for code, missing in (("no_cut_heading", not parts["cut_found"]),
                                           ("no_title", not title), ("no_summary", not summary)) if missing]
    return {
        "hpa_id": hpa_id,
        "title": title,
        "summary": summary,
        "keywords": split_list(meta.get("search_keywords"), commas=label_template),
        "question_variants": question_variants(meta, routing),
        "care_topics": care_topics(meta, label_template),
        "urgency": _clean(meta.get("urgency")),
        "review_status": review_status(meta.get("expert_review_status")),
        "content_version": _clean(meta.get("content_version")),
        "related": related_ids(hpa_id, meta, routing, parts["tail"]),
        "blocks": blocks,
        "references": _references(parts["tail"]),
        "source_file": source_file,
        "warnings": warnings,
    }


def check_unique(docs):
    """Refuse two input files that resolve to the same hpa_id.

    Args:
        docs (list[dict]): normalize_document outputs.

    Returns:
        None.

    Raises:
        ValueError: Naming the id and both files, for example a v2 and a v4
            of one guide left side by side in the input folder.

    Side effects: none.
    """
    seen = {}
    for doc in docs:
        if doc["hpa_id"] in seen:
            raise ValueError(f"{doc['hpa_id']} comes from both {seen[doc['hpa_id']]} and {doc['source_file']}")
        seen[doc["hpa_id"]] = doc["source_file"]


def _stats(doc, meta_variants, routing_variants):
    """Count what one guide produced, for the CLI table.

    Args:
        doc (dict): normalize_document output.
        meta_variants (int): Variants from the metadata list.
        routing_variants (int): Variants from the routing table.

    Returns:
        list[str]: The row cells, counts and codes only (no guide text).

    Side effects: none.
    """
    count = lambda kind: sum(block["type"] == kind for block in doc["blocks"])
    return [doc["source_file"][:34], doc["hpa_id"], doc["review_status"], str(len(doc["blocks"])),
            str(count("heading")), str(count("callout")), str(count("table")), str(count("list")),
            f"{meta_variants}/{routing_variants}/{len(doc['question_variants'])}",
            str(len(doc["care_topics"])), str(len(doc["related"])), ",".join(doc["warnings"]) or "-"]


def main():
    """Parse and normalize every guide, write doc.json files and print a summary.

    Args (command line):
        --input DIR   folder of .docx guides (default private/input)
        --out DIR     where to write <hpa_id>.json (default private/docs)

    Returns:
        None.

    Raises:
        SystemExit: 1 if the input folder has no .docx files, a guide has no
            content_id, or two files share an hpa_id. Nothing is written in
            those cases.

    Side effects: reads the guides, writes one JSON file per guide, prints
    one row of counts per guide.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(INPUT_DIR))
    parser.add_argument("--out", default=str(OUTPUT_DIR))
    args = parser.parse_args()
    files = sorted(path for path in Path(args.input).glob("*.docx") if not path.name.startswith("~$"))
    if not files:
        sys.exit(f"No .docx files in {args.input}")
    docs, rows = [], []
    for path in files:
        elements = parse.read_docx(path)
        try:
            doc = normalize_document(elements, path.name)
        except ValueError as error:
            sys.exit(str(error))
        parts = parse.split_document(elements)
        meta, routing = extract_metadata(parts["tail"] if parts["cut_found"] else elements)
        from_meta, from_routing = variant_lists(meta, routing)
        docs.append(doc)
        rows.append(_stats(doc, len(from_meta), len(from_routing)))
    try:
        check_unique(docs)
    except ValueError as error:
        sys.exit(f"Duplicate guide: {error}")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for doc in docs:
        (out / f"{doc['hpa_id']}.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    header = ["file", "hpa_id", "review", "blocks", "sections", "callouts", "tables", "lists",
              "variants m/r/all", "topics", "related", "warnings"]
    widths = [max(len(row[i]) for row in [header, *rows]) for i in range(len(header))]
    for row in [header, *rows]:
        print("  ".join(cell.ljust(width) for cell, width in zip(row, widths)))
    totals = {name: sum(int(row[i]) for row in rows) for i, name in ((3, "blocks"), (5, "callouts"), (6, "tables"))}
    print(f"\n{len(docs)} guides, {totals['blocks']} blocks, {totals['callouts']} callouts, "
          f"{totals['tables']} tables, approved: {sum(doc['review_status'] == 'approved' for doc in docs)}. "
          f"Wrote {out}")


if __name__ == "__main__":
    main()
