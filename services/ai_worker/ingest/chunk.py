# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Cut each normalized guide into chunks for embedding.

Ingest step 3 of 5 (spec sections 3.3 and 14.1). Reads every doc.json that
normalize.py wrote and writes one line per chunk to private/chunks.jsonl.
build_rows.py embeds `title + "\\n" + content` of each line.

Contents:
    est_tokens, chunk_tokens  the token estimate (characters / 4, no tokenizer)
    sentences        sentence split that never breaks inside a quote
    render_list      list block -> "- item" or "1. item" lines
    replace_ids      internal guide ids in body text -> guide titles
    build_sections   blocks -> sections (paragraph and list text per heading path)
    merge_sections   small sections merge forward inside one H1
    pack             the splitter shared by sections, callouts and tables
    split_section    one section -> parts of 300 to 500 tokens with overlap
    table_lines      table block -> "<Header>: X -> <Header>: Y" lines
    split_variants   question variants -> (card, held out); the retrieval
                     eval imports this exact function
    card_content     the doc card text
    chunk_document   doc.json -> chunk records and warning codes
    main             the CLI (stats table, --show)

Usage (from the repo root):
    uv run --python 3.11 services/ai_worker/ingest/chunk.py [--docs DIR] [--out FILE] [--show HPA-ID]

Every size rule is measured on the embedding input (title + "\\n" + content),
the same number written as est_tokens, so "no chunk over HARD_MAX" holds for
what is actually embedded.

Depends on: the standard library only.

Never does: call a model, touch the network or the database, or print guide
text, except with --show, which prints one guide's chunks to the local
terminal for reading by eye. The default run prints counts and token sizes
only. There is no guide-specific code.
"""

import argparse
import json
import math
import re
import statistics
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
# Defaults, both under the git-ignored private/.
DOCS_DIR = HERE / "private" / "docs"
OUTPUT_FILE = HERE / "private" / "chunks.jsonl"

# Characters per token for the estimate. About 4 for English prose with the
# OpenAI tokenizers; close enough for sizing chunks without a dependency.
CHARS_PER_TOKEN = 4

# A section smaller than this merges forward into the next section of the
# same H1 (spec 3.3 rule 2). A chunk this small carries too little context to
# rank well on its own.
MIN_TOKENS = 80
# A merge never grows a chunk past this, so merged chunks stay well inside
# the split target and are never split again.
MERGE_MAX = 400
# The size range a split aims for (spec 3.3 rule 3). A section up to
# TARGET_MAX stays whole.
TARGET_MIN = 300
TARGET_MAX = 500
# No chunk is ever larger, except one sentence or one table row that cannot
# be cut without breaking it (kept whole, with a warning).
HARD_MAX = 800
# Upper bound on the sentences carried from one split part into the next.
# About two short sentences: enough to keep a pronoun's referent, small
# enough not to duplicate whole paragraphs.
OVERLAP_TOKENS = 50
# The CLI warns about section and table chunks smaller than this: a sign of
# a heading with almost nothing under it, or a near-empty table.
TINY_TOKENS = 20

# A sentence ends at ".", "!" or "?" followed by whitespace. sentences()
# skips any break that falls inside a double quote.
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")

# An internal guide id written in body text, with or without the "HPA-"
# prefix ("HPA-FUND-0001", "FUND-0001"). Members never see these ids, so
# replace_ids swaps each one for a readable name before chunk text is built
# (spec 14.10). The same pattern as normalize.RELATED_ID.
GUIDE_ID = re.compile(r"\b(?:HPA-)?([A-Z]{3,8}-\d{4})\b")
# GUIDE_ID plus the full stop right after it, if any, so a title that ends
# in its own "?", "!" or "." does not end up as "Why is it wilting?." (spec
# 14.10).
GUIDE_ID_AND_STOP = re.compile(GUIDE_ID.pattern + r"(\.?)")
# Stands in for an id whose guide is not in this batch.
UNKNOWN_GUIDE = "a related guide"

# Separator between the parts of a chunk title: "Guide > H1 > H2".
TITLE_SEPARATOR = " > "
# The last title part of the doc card.
OVERVIEW = "Overview"

# How pieces are joined back together when a split part is rebuilt:
# paragraphs with a blank line, list lines with a newline, sentences of one
# paragraph with a space.
PARAGRAPH_JOIN = "\n\n"
LINE_JOIN = "\n"
SENTENCE_JOIN = " "


def est_tokens(text):
    """Estimate the token count of a text.

    Args:
        text (str): Any text.

    Returns:
        int: ceil(len(text) / CHARS_PER_TOKEN); 0 for "".

    Side effects: none.
    """
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def chunk_tokens(title, content):
    """Estimate the tokens of a chunk's embedding input.

    Args:
        title (str): The chunk title.
        content (str): The chunk content.

    Returns:
        int: est_tokens(title + "\\n" + content), the value written as
        est_tokens and used by every size rule.

    Side effects: none.
    """
    return est_tokens(title + "\n" + content)


def _title(guide, path):
    """Join a guide title and a heading path into a chunk title.

    Args:
        guide (str): The guide title.
        path (list[str]): Cleaned headings, for example ["Light", "Signs"].

    Returns:
        str: For example "Guide > Light > Signs".

    Side effects: none.
    """
    return TITLE_SEPARATOR.join([guide, *path])


def sentences(text):
    """Split text into sentences at SENTENCE_BREAK, never inside a quote.

    A break is skipped while a curly double quote is open (more "“" than "”"
    since the sentence started) or a straight double quote is unbalanced.

    Args:
        text (str): One paragraph or line.

    Returns:
        list[str]: The sentences, stripped, empties dropped. A text with no
        break is one sentence.

    Side effects: none.
    """
    parts, start = [], 0
    for match in SENTENCE_BREAK.finditer(text):
        sentence = text[start:match.start()]
        if sentence.count("“") > sentence.count("”") or sentence.count('"') % 2:
            continue
        parts.append(sentence)
        start = match.end()
    parts.append(text[start:])
    return [part.strip() for part in parts if part.strip()]


def render_list(block):
    """Render a list block as text lines.

    Args:
        block (dict): {"type": "list", "ordered": bool, "items": [...]}.

    Returns:
        str: "- item" lines, or "1. item", "2. item" lines when ordered,
        joined with "\\n". These are reference passages; the no-markdown rule
        applies to answers only.

    Side effects: none.
    """
    items = [item for item in block["items"] if item.strip()]
    if block.get("ordered"):
        return LINE_JOIN.join(f"{number}. {item}" for number, item in enumerate(items, 1))
    return LINE_JOIN.join(f"- {item}" for item in items)


def replace_ids(blocks, titles):
    """Replace internal guide ids in body text with guide titles.

    Args:
        blocks (list[dict]): doc["blocks"].
        titles (dict[str, str]): "HPA-XXXX-NNNN" -> guide title, for every
            guide in this batch.

    Returns:
        tuple[list[dict], int]: (new blocks, number of ids replaced). Each
        GUIDE_ID match in paragraph text, list items, table header and
        cells, and callout title and text becomes the title of that guide,
        or UNKNOWN_GUIDE when it is not in the batch. A full stop right
        after the id is dropped when the title already ends with "?", "!"
        or ".". Headings are left
        alone. The input blocks are not changed, so doc["related"] and the
        hpa: tags built from doc.json keep the real ids.

    Side effects: none.
    """
    count = 0

    def name(match):
        nonlocal count
        count += 1
        title = titles.get(f"HPA-{match.group(1)}") or UNKNOWN_GUIDE
        stop = match.group(2)
        return title if title.endswith(("?", "!", ".")) else title + stop

    def swap(text):
        return GUIDE_ID_AND_STOP.sub(name, text)

    result = []
    for block in blocks:
        if block["type"] in ("paragraph", "callout"):
            block = {**block, "text": swap(block["text"])}
            if block["type"] == "callout":
                block["title"] = swap(block["title"])
        elif block["type"] == "list":
            block = {**block, "items": [swap(item) for item in block["items"]]}
        elif block["type"] == "table":
            block = {**block, "header": [swap(cell) for cell in block.get("header") or []],
                     "rows": [[swap(cell) for cell in row] for row in block["rows"]]}
        result.append(block)
    return result, count


def build_sections(blocks):
    """Collect the paragraph and list text of each heading path.

    A new section starts at every heading and whenever a text block's path
    changes. Tables and callouts are skipped here (they become their own
    chunks), so a heading whose only content is a table makes no section.

    Args:
        blocks (list[dict]): doc["blocks"] from normalize.py.

    Returns:
        list[dict]: In document order, each
            {"path": [...], "group": (H1 count, path[0]), "position": int,
             "paragraphs": [str, ...]}
        path is ["Introduction"], [H1] or [H1, H2]. group is the same for the
        H1's own text and its H2 sections and differs across H1s, even when
        two H1s share a name. position is the index of the section's first
        text block. A list block is one paragraph of rendered lines.

    Side effects: none.
    """
    sections, current, h1_count = [], None, 0
    for position, block in enumerate(blocks):
        if block["type"] == "heading":
            current = None
            if block["level"] == 1:
                h1_count += 1
            continue
        if block["type"] == "paragraph":
            text = block["text"].strip()
        elif block["type"] == "list":
            text = render_list(block)
        else:
            continue
        if not text:
            continue
        path = list(block["path"])
        if current is None or current["path"] != path:
            current = {"path": path, "group": (h1_count, path[0]), "position": position, "paragraphs": []}
            sections.append(current)
        current["paragraphs"].append(text)
    return sections


def _candidate(group, guide):
    """Build the chunk candidate for one section or a run of merged sections.

    Args:
        group (list[dict]): Consecutive sections from build_sections, all in
            one H1.
        guide (str): The guide title.

    Returns:
        dict: {"title", "paragraphs", "position"}. One section keeps its full
        path title and its paragraphs. Merged sections take the title
        "Guide > H1", and each H2 heading becomes a line above that H2's
        first paragraph.

    Side effects: none.
    """
    if len(group) == 1:
        section = group[0]
        return {"title": _title(guide, section["path"]), "paragraphs": list(section["paragraphs"]),
                "position": section["position"]}
    paragraphs = []
    for section in group:
        first, *rest = section["paragraphs"]
        if len(section["path"]) > 1:
            first = section["path"][-1] + LINE_JOIN + first
        paragraphs += [first, *rest]
    return {"title": _title(guide, group[0]["path"][:1]), "paragraphs": paragraphs,
            "position": group[0]["position"]}


def _candidate_tokens(group, guide):
    """Return the chunk size a group of sections would have once built.

    Args:
        group (list[dict]): As for _candidate.
        guide (str): The guide title.

    Returns:
        int: chunk_tokens of the built candidate.

    Side effects: none.
    """
    candidate = _candidate(group, guide)
    return chunk_tokens(candidate["title"], PARAGRAPH_JOIN.join(candidate["paragraphs"]))


def merge_sections(sections, guide):
    """Merge small sections forward inside one H1 (spec 3.3 rule 2, 14.1 Q6).

    Walking in order, a section (or a merged run) under MIN_TOKENS absorbs
    the next section of the same H1 as long as the result stays at or under
    MERGE_MAX, and keeps absorbing while it is still under MIN_TOKENS. A
    merge never crosses an H1: a small last section, or a small H1 with no
    H2s, stays alone.

    Args:
        sections (list[dict]): From build_sections.
        guide (str): The guide title.

    Returns:
        list[dict]: Candidates from _candidate, in document order.

    Side effects: none.
    """
    candidates, index = [], 0
    while index < len(sections):
        group = [sections[index]]
        index += 1
        while (index < len(sections) and sections[index]["group"] == group[0]["group"]
               and _candidate_tokens(group, guide) < MIN_TOKENS
               and _candidate_tokens(group + [sections[index]], guide) <= MERGE_MAX):
            group.append(sections[index])
            index += 1
        candidates.append(_candidate(group, guide))
    return candidates


def _join(pieces):
    """Rebuild text from pieces.

    Args:
        pieces (list[tuple[str, str]]): (joiner before this piece, text).

    Returns:
        str: The texts joined with their joiners; the first joiner is unused.

    Side effects: none.
    """
    return pieces[0][1] + "".join(joiner + text for joiner, text in pieces[1:])


def _overlap(text):
    """Pick the sentences that the next split part starts with.

    Args:
        text (str): The last piece of the previous part.

    Returns:
        str | None: The last 2 sentences of its last line if they fit in
        OVERLAP_TOKENS, else the last 1 if it fits, else None.

    Side effects: none.
    """
    lines = [line for line in text.split(LINE_JOIN) if line.strip()]
    units = sentences(lines[-1]) if lines else []
    for count in (2, 1):
        if len(units) >= count:
            tail = SENTENCE_JOIN.join(units[-count:])
            if est_tokens(tail) <= OVERLAP_TOKENS:
                return tail
    return None


def _deviation(tokens):
    """Measure how far a part's size falls outside TARGET_MIN..TARGET_MAX.

    Args:
        tokens (int): The part's chunk_tokens.

    Returns:
        int: 0 inside the range, otherwise the distance to it.

    Side effects: none.
    """
    return max(0, TARGET_MIN - tokens) + max(0, tokens - TARGET_MAX)


def pack(pieces, title, limit, overlap):
    """Group pieces into parts of at most `limit` tokens, as close to the target range as possible.

    Picks the cut points by dynamic programming: the fewest tokens outside
    TARGET_MIN..TARGET_MAX in total, then the fewest parts. Ties go to the
    earliest cut, so the result is deterministic. Tried in order:
        1. at least two parts, each between MIN_TOKENS and `limit`;
        2. the whole text as one part, if it fits in `limit`;
        3. any parts up to `limit`, with no lower bound.
    A single piece larger than `limit` (one sentence or one table row that
    cannot be cut) is always allowed as a part of its own.

    Args:
        pieces (list[tuple[str, str]]): (joiner before, text) in order.
        title (str): The title every part will carry, counted in its size.
        limit (int): The largest allowed part (HARD_MAX for sections and
            callouts, TARGET_MAX for table rows).
        overlap (bool): Start each later part with _overlap() of the piece
            before it, dropped when a single-piece part would no longer fit.

    Returns:
        list[str]: The part contents, in order, covering every piece once
        (plus the overlap sentences).

    Side effects: none.
    """
    count = len(pieces)
    tails = [None] + [_overlap(pieces[j - 1][1]) if overlap else None for j in range(1, count)]

    def part(start, end):
        body = _join(pieces[start:end])
        if tails[start]:
            with_tail = tails[start] + pieces[start][0] + body
            if end - start > 1 or chunk_tokens(title, with_tail) <= limit:
                return with_tail
        return body

    def solve(minimum, at_least_two):
        # best[i] = (tokens outside the target, parts, previous cut) for the
        # best grouping of pieces[:i].
        best = [None] * (count + 1)
        best[0] = (0, 0, None)
        for end in range(1, count + 1):
            for start in range(end):
                if best[start] is None or (at_least_two and start == 0 and end == count):
                    continue
                tokens = chunk_tokens(title, part(start, end))
                unbreakable = end - start == 1 and chunk_tokens(title, pieces[start][1]) > limit
                if not unbreakable and not minimum <= tokens <= limit:
                    continue
                cost = (best[start][0] + _deviation(tokens), best[start][1] + 1)
                if best[end] is None or cost < best[end][:2]:
                    best[end] = (*cost, start)
        if best[count] is None:
            return None
        cuts, end = [], count
        while end:
            start = best[end][2]
            cuts.append(part(start, end))
            end = start
        return cuts[::-1]

    if count > 1:
        parts = solve(MIN_TOKENS, at_least_two=True)
        if parts:
            return parts
    whole = _join(pieces)
    if chunk_tokens(title, whole) <= limit:
        return [whole]
    return solve(0, at_least_two=False)


def _section_pieces(paragraphs, title):
    """Turn paragraphs into pieces, cutting any paragraph over HARD_MAX into sentences.

    Args:
        paragraphs (list[str]): The section's paragraphs.
        title (str): The chunk title, counted in each paragraph's size.

    Returns:
        list[tuple[str, str]]: (joiner before, text). A paragraph that fits
        in HARD_MAX is one piece. A larger one is cut at its lines (list
        items, box lines), then at sentences(), never mid-sentence.

    Side effects: none.
    """
    pieces = []
    for paragraph in paragraphs:
        if chunk_tokens(title, paragraph) <= HARD_MAX:
            pieces.append((PARAGRAPH_JOIN, paragraph))
            continue
        lines = [line for line in paragraph.split(LINE_JOIN) if line.strip()]
        for line_number, line in enumerate(lines):
            for sentence_number, sentence in enumerate(sentences(line)):
                if sentence_number:
                    joiner = SENTENCE_JOIN
                else:
                    joiner = LINE_JOIN if line_number else PARAGRAPH_JOIN
                pieces.append((joiner, sentence))
    return pieces


def split_section(title, paragraphs, keep_up_to=TARGET_MAX):
    """Split one section (or callout) into parts with overlap (spec 3.3 rules 3 and 4).

    Args:
        title (str): The chunk title, kept by every part.
        paragraphs (list[str]): The text, one entry per paragraph.
        keep_up_to (int): Keep the text whole up to this size: TARGET_MAX
            for sections, HARD_MAX for callouts.

    Returns:
        list[str]: Part contents. One entry when the text fits in
        keep_up_to. Otherwise parts from pack() with limit HARD_MAX, cut at
        paragraph boundaries (and sentence boundaries inside a paragraph
        over HARD_MAX), each later part starting with the last 1 or 2
        sentences of the one before. Overlap stays inside this one section.

    Side effects: none.
    """
    whole = PARAGRAPH_JOIN.join(paragraphs)
    if chunk_tokens(title, whole) <= keep_up_to:
        return [whole]
    return pack(_section_pieces(paragraphs, title), title, HARD_MAX, overlap=True)


def table_lines(block):
    """Render a table as one self-describing line per row (spec 14.1 Q4).

    Args:
        block (dict): {"type": "table", "header": [...], "rows": [[...]]}.

    Returns:
        list[str]: "<Header1>: X -> <Header2>: Y" per row. Empty cells are
        skipped; an empty or missing header cell is named "Column N"
        (1-based). Whitespace inside cells is collapsed. A row with no
        non-empty cell gives no line.

    Side effects: none.
    """
    header = block.get("header") or []
    lines = []
    for row in block["rows"]:
        cells = []
        for number, cell in enumerate(row, 1):
            value = " ".join(cell.split())
            if not value:
                continue
            name = " ".join(header[number - 1].split()) if number <= len(header) else ""
            cells.append(f"{name or f'Column {number}'}: {value}")
        if cells:
            lines.append(" -> ".join(cells))
    return lines


def split_table(title, lines):
    """Split a table chunk by rows when it is over HARD_MAX.

    Args:
        title (str): The chunk title (the section path).
        lines (list[str]): From table_lines.

    Returns:
        list[str]: One content when the table fits in HARD_MAX. Otherwise
        parts of whole rows, each at most TARGET_MAX, with no repeated
        header line and no overlap (every row names its own columns).

    Side effects: none.
    """
    whole = LINE_JOIN.join(lines)
    if chunk_tokens(title, whole) <= HARD_MAX:
        return [whole]
    return pack([(LINE_JOIN, line) for line in lines], title, TARGET_MAX, overlap=False)


def split_variants(question_variants):
    """Split question variants into card variants and held-out eval variants.

    The retrieval eval imports this exact function to rebuild the held-out
    set (spec 14.7 Q6), so it must stay pure and deterministic.

    Args:
        question_variants (list[str]): doc["question_variants"].

    Returns:
        tuple[list[str], list[str]]: (card, held_out). card holds the even
        indices (0, 2, 4, ...), held_out the odd ones, both in their
        original order. The input is not changed.

    Side effects: none.
    """
    return list(question_variants[0::2]), list(question_variants[1::2])


def card_content(doc):
    """Build the doc card text for one guide (spec 3.3 rule 7).

    Args:
        doc (dict): A doc.json dict.

    Returns:
        str: Lines "Summary: ...", "Keywords: a, b, c", "Questions:" and one
        line per card variant (split_variants). A line whose value is
        missing is left out.

    Side effects: none.
    """
    card, _ = split_variants(doc.get("question_variants") or [])
    lines = []
    if doc.get("summary"):
        lines.append(f"Summary: {doc['summary']}")
    if doc.get("keywords"):
        lines.append("Keywords: " + ", ".join(doc["keywords"]))
    if card:
        lines += ["Questions:", *card]
    return LINE_JOIN.join(lines)


def _record(doc, chunk_index, kind, title, content):
    """Build one output line.

    Args:
        doc (dict): The doc.json dict the chunk comes from.
        chunk_index (int | None): Position among the guide's chunks; None
            for the card.
        kind (str): "section", "callout", "table" or "card".
        title (str): The chunk title.
        content (str): The chunk content.

    Returns:
        dict: {"hpa_id", "chunk_index", "kind", "title", "content",
        "review_status", "care_topics", "est_tokens"}.

    Side effects: none.
    """
    return {"hpa_id": doc["hpa_id"], "chunk_index": chunk_index, "kind": kind, "title": title,
            "content": content, "review_status": doc["review_status"],
            "care_topics": list(doc.get("care_topics") or []), "est_tokens": chunk_tokens(title, content)}


# Warning code per chunk kind for a chunk left over HARD_MAX. pack() only
# allows that for one sentence (sections, callouts) or one row (tables).
OVERSIZE_WARNINGS = {"section": "oversized_sentence", "callout": "oversized_sentence",
                     "table": "oversized_row", "card": "oversized_card"}


def chunk_document(doc, titles=None):
    """Cut one guide into chunks.

    Args:
        doc (dict): A doc.json dict from normalize.py (title, summary,
            keywords, question_variants, care_topics, review_status, blocks).
        titles (dict[str, str] | None): hpa_id -> guide title for every
            guide in the batch, used by replace_ids. None means this guide
            alone.

    Returns:
        tuple[list[dict], list[str], int]: (chunks, warnings, ids_replaced).
        chunks are _record dicts: section, table and callout chunks in
        document order with chunk_index 0, 1, 2, ..., then the card with
        chunk_index None. A chunk sits at the position of its first block;
        the parts of one split keep their order. warnings holds codes only,
        for example "oversized_sentence:4" (the chunk index), never guide
        text. ids_replaced counts the guide ids swapped by replace_ids.

    Side effects: none.
    """
    guide = doc.get("title") or doc["hpa_id"]
    if titles is None:
        titles = {doc["hpa_id"]: guide}
    # Ids are replaced before any size is measured, so merges and splits see
    # the text that is actually embedded.
    blocks, ids_replaced = replace_ids(doc["blocks"], titles)
    # (position, part number, kind, title, content); sorted into document order.
    parts = []
    for candidate in merge_sections(build_sections(blocks), guide):
        for number, content in enumerate(split_section(candidate["title"], candidate["paragraphs"])):
            parts.append((candidate["position"], number, "section", candidate["title"], content))
    for position, block in enumerate(blocks):
        if block["type"] == "table":
            title = _title(guide, block["path"])
            lines = table_lines(block)
            if lines:
                for number, content in enumerate(split_table(title, lines)):
                    parts.append((position, number, "table", title, content))
        elif block["type"] == "callout":
            title = _title(guide, [*block["path"], block["title"]])
            content = f"{block['title']}: {block['text']}".strip()
            # One paragraph, so the box's own line breaks survive; only a box
            # over HARD_MAX is cut (at its lines, then sentences).
            for number, piece in enumerate(split_section(title, [content], keep_up_to=HARD_MAX)):
                parts.append((position, number, "callout", title, piece))
    parts.sort(key=lambda item: item[:2])
    chunks = [_record(doc, index, kind, title, content)
              for index, (_, _, kind, title, content) in enumerate(parts)]
    chunks.append(_record(doc, None, "card", _title(guide, [OVERVIEW]), card_content(doc)))
    warnings = [f"{OVERSIZE_WARNINGS[c['kind']]}:{c['chunk_index'] if c['chunk_index'] is not None else 'card'}"
                for c in chunks if c["est_tokens"] > HARD_MAX]
    return chunks, warnings, ids_replaced


def _load_docs(folder):
    """Read every doc.json in a folder.

    Args:
        folder (str | Path): The docs folder.

    Returns:
        list[dict]: The docs, sorted by file name.

    Side effects: reads the files.
    """
    return [json.loads(path.read_text()) for path in sorted(Path(folder).glob("*.json"))]


def _stats_row(doc, chunks, ids_replaced):
    """Count one guide's chunks for the stats table.

    Args:
        doc (dict): The doc.json dict.
        chunks (list[dict]): Its chunks.
        ids_replaced (int): From chunk_document.

    Returns:
        list[str]: hpa_id, section count, chunks by kind, total,
        ids_replaced, and min / median / max est_tokens. Counts only, no
        guide text.

    Side effects: none.
    """
    kinds = [sum(c["kind"] == kind for c in chunks) for kind in ("section", "table", "callout", "card")]
    tokens = [c["est_tokens"] for c in chunks]
    return [doc["hpa_id"], str(len(build_sections(doc["blocks"]))), *map(str, kinds), str(len(chunks)),
            str(ids_replaced), str(min(tokens)), f"{statistics.median(tokens):g}", str(max(tokens))]


def _print_table(rows):
    """Print rows as left-aligned columns.

    Args:
        rows (list[list[str]]): The header row first.

    Returns:
        None.

    Side effects: prints to stdout.
    """
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for row in rows:
        print("  ".join(cell.ljust(width) for cell, width in zip(row, widths)))


def _show(chunks):
    """Print one guide's chunks in full, for reading by eye.

    Args:
        chunks (list[dict]): The guide's chunks.

    Returns:
        None.

    Side effects: prints guide text to the local terminal (--show only).
    """
    for chunk in chunks:
        index = "card" if chunk["chunk_index"] is None else chunk["chunk_index"]
        print(f"=== [{index}] {chunk['kind']}, {chunk['est_tokens']} tokens")
        print(chunk["title"])
        print("---")
        print(chunk["content"])
        print()


def main():
    """Chunk every guide, write chunks.jsonl and print stats, or show one guide.

    Args (command line):
        --docs DIR       folder of doc.json files (default private/docs)
        --out FILE       output JSONL (default private/chunks.jsonl)
        --show HPA-ID    print that guide's chunks in full instead; nothing
                         is written

    Returns:
        None.

    Raises:
        SystemExit: 1 if the docs folder has no .json files, or --show names
            a guide that is not there.

    Side effects: reads the docs; writes the output file and prints a stats
    table and warnings (counts and ids only), or with --show prints one
    guide's chunks.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--docs", default=str(DOCS_DIR))
    parser.add_argument("--out", default=str(OUTPUT_FILE))
    parser.add_argument("--show")
    args = parser.parse_args()
    docs = _load_docs(args.docs)
    if not docs:
        sys.exit(f"No .json files in {args.docs}")
    # Every guide in the batch, so an id pointing at another guide becomes
    # that guide's title.
    titles = {doc["hpa_id"]: doc.get("title") or doc["hpa_id"] for doc in docs}
    if args.show:
        doc = next((doc for doc in docs if doc["hpa_id"] == args.show), None)
        if doc is None:
            sys.exit(f"No guide {args.show} in {args.docs}")
        _show(chunk_document(doc, titles)[0])
        return
    rows, warnings, every_chunk = [], [], []
    for doc in docs:
        chunks, codes, ids_replaced = chunk_document(doc, titles)
        every_chunk += chunks
        rows.append(_stats_row(doc, chunks, ids_replaced))
        warnings += [f"{doc['hpa_id']}: {code}" for code in codes]
        warnings += [f"{doc['hpa_id']}: tiny_{c['kind']}:{c['chunk_index']} ({c['est_tokens']} tokens)"
                     for c in chunks if c["kind"] in ("section", "table") and c["est_tokens"] < TINY_TOKENS]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(chunk, ensure_ascii=False) + "\n" for chunk in every_chunk))
    header = ["hpa_id", "sections", "section", "table", "callout", "card", "chunks", "ids_replaced",
              "min", "median", "max"]
    tokens = [c["est_tokens"] for c in every_chunk]
    totals = ["TOTAL", *(str(sum(int(row[i]) for row in rows)) for i in range(1, 8)),
              str(min(tokens)), f"{statistics.median(tokens):g}", str(max(tokens))]
    _print_table([header, *rows, totals])
    print(f"\n{len(docs)} guides, {len(every_chunk)} chunks. Wrote {out}")
    for warning in warnings:
        print(f"WARNING {warning}")
    if not warnings:
        print(f"No chunk over {HARD_MAX} tokens; no section or table chunk under {TINY_TOKENS}.")


if __name__ == "__main__":
    main()
