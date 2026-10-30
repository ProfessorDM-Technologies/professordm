# /// script
# requires-python = ">=3.11"
# dependencies = ["python-docx"]
# ///
"""Read a Houseplant Academy guide (.docx) and turn its body into ordered blocks.

Ingest step 1 of 5 (spec section 3.1 and 14.1). normalize.py calls these
functions and writes one doc.json per guide; nothing here writes files.

Contents:
    read_docx        .docx -> raw elements (the only python-docx code)
    split_document   raw elements -> body (member-facing) and tail (references,
                     related entries, internal metadata)
    promote_headings turns a missing numbered H1 typed as Normal into a heading
    body_blocks      body elements -> heading, paragraph, list, table and
                     callout blocks with their heading path
    list_item        styled list paragraphs and typed bullets ("□ ", "• ")
    clean_heading    strips "o " bullets and dotted section numbers
    heading_level    Word heading style -> 1, 2, ... or None

Depends on: python-docx, imported inside read_docx only, so the tests and
every other module stay standard library. Everything after read_docx works on
plain dicts and is tested on hand-built fixtures.

Never does: call a model, touch the network or the database, write files, or
print or log guide text. There is no guide-specific code: every rule is a
pattern, so the same code serves the next 100 guides.
"""

import re


# Word paragraph styles that mark a list item. A paragraph with numbering
# properties (w:numPr) is a list item whatever its style.
LIST_STYLES = {"List Bullet", "List Number", "List Paragraph"}

# The only list style that means "numbered steps". List Paragraph is used for
# both bullets and numbers in the guides, so it is treated as unordered.
ORDERED_STYLE = "List Number"

# Where the member-facing body ends (spec 14.1 Q1). Matched against heading
# paragraphs only, case-insensitive, with an optional leading section number
# ("11." or "5"). Older guides use "Related Academy Entries", newer ones
# "Related entries, references & evidence"; "References" is the fallback.
CUT_HEADING = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\.?\s+)?"
    r"(?:related academy entries|related entries,\s*references\s*&\s*evidence|references)\s*$",
    re.IGNORECASE)

# Sections that only list what the guide covers. Their heading, paragraphs
# and lists are dropped; boxes and tables inside them are kept (13 guides put
# a tip box there).
CONTENTS_HEADINGS = {"in this guide", "contents"}

# Banner lines before the first heading, dropped by pattern rather than by
# position (spec 14.1 Q2). The guide-title line is matched separately against
# the title from the metadata.
ACADEMY_LINE = re.compile(r"^the\b.*\bacademy$", re.IGNORECASE)
ID_LINE = re.compile(r"^[A-Z]{2,6}-[A-Z]+-\d{4}\s*\|")

# Path given to text before the first heading.
INTRO = "Introduction"

# A heading's leading "o " bullet (Word renders some H2s with a typed "o").
BULLET_PREFIX = re.compile(r"^o\s+")

# A leading section number, stripped only when followed by a dot ("2. ",
# "2.1. ", "10. "), so a heading such as "3 Signs ..." keeps its number.
SECTION_NUMBER = re.compile(r"^\d+(?:\.\d+)*\.\s+")

# A figure caption prefix: "Figure 3." or "Figure 3:", optionally wrapped in
# Markdown-style bold. The rest of the caption is kept as a normal sentence.
FIGURE_PREFIX = re.compile(r"^\**\s*figure\s+\d+\s*[.:]\s*\**\s*", re.IGNORECASE)

# A 1x1 box is a titled callout only when its title (the text before the
# first colon) is short: at most this many words and characters (spec 14.1
# Q3). Longer text before a colon is an ordinary sentence.
MAX_CALLOUT_TITLE_WORDS = 8
MAX_CALLOUT_TITLE_CHARS = 60

# Characters some guides type in front of a Normal paragraph instead of using
# a list style. One constant, so a new glyph is a one-character addition.
BULLET_GLYPHS = "□•▪◦●‣"
TYPED_BULLET = re.compile(rf"^[{re.escape(BULLET_GLYPHS)}][ \t]*")

# A section heading typed as a Normal paragraph: "5. How light changes".
# promote_headings only accepts it with the guards documented there.
NUMBERED_LINE = re.compile(r"^(\d+)\.\s+\S")
MAX_PROMOTED_WORDS = 12

# A box that opens with a quote is a myth box ("“X.” Not quite..."), never a
# titled callout, even if a colon appears early.
QUOTE_MARKS = ("\"", "“", "‘", "'")


def read_docx(path):
    """Read a .docx body in document order as raw paragraphs and tables.

    Args:
        path (str | Path): The .docx file.

    Returns:
        list[dict]: In body order, each one of
            {"kind": "paragraph", "style": str, "text": str, "list": bool}
            {"kind": "table", "rows": [[cell text, ...], ...]}
        Paragraph text is stripped. "list" is true for LIST_STYLES or a
        paragraph with numbering properties. A cell's paragraphs are joined
        with "\\n"; a horizontally merged cell appears once per row, not once
        per grid column.

    Raises:
        ModuleNotFoundError: If python-docx is not installed (run with uv run).
        docx.opc.exceptions.PackageNotFoundError: If the file is not a .docx.

    Side effects: reads the file.
    """
    import docx
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx.Document(str(path))
    elements = []
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            paragraph = Paragraph(child, document)
            text = paragraph.text.strip()
            if not text:
                # Empty spacers and image-only paragraphs carry no text.
                continue
            properties = child.find(qn("w:pPr"))
            numbered = properties is not None and properties.find(qn("w:numPr")) is not None
            style = paragraph.style.name if paragraph.style is not None else ""
            elements.append({"kind": "paragraph", "style": style, "text": text,
                             "list": numbered or style in LIST_STYLES})
        elif child.tag == qn("w:tbl"):
            rows = []
            for row in Table(child, document).rows:
                cells, seen = [], set()
                for cell in row.cells:
                    # python-docx repeats a merged cell for every grid column
                    # it spans; keep the first occurrence only.
                    if id(cell._tc) in seen:
                        continue
                    seen.add(id(cell._tc))
                    cells.append("\n".join(p.text.strip() for p in cell.paragraphs if p.text.strip()))
                rows.append(cells)
            elements.append({"kind": "table", "rows": rows})
    return elements


def heading_level(style):
    """Return the heading level of a Word paragraph style.

    Args:
        style (str | None): The style name, for example "Heading 2".

    Returns:
        int | None: 1, 2, ... for "Heading N", otherwise None.

    Side effects: none.
    """
    match = re.fullmatch(r"Heading\s+(\d)", style or "")
    return int(match.group(1)) if match else None


def _is_heading(element):
    """Tell whether a raw element is a heading paragraph.

    Args:
        element (dict): A raw element from read_docx.

    Returns:
        bool: True for a paragraph whose style is a Word heading style.

    Side effects: none.
    """
    return element["kind"] == "paragraph" and heading_level(element.get("style")) is not None


def split_document(elements):
    """Split a guide at its cut heading into the body and the tail.

    Args:
        elements (list[dict]): Raw elements from read_docx.

    Returns:
        dict: {"body": [...], "tail": [...], "cut_found": bool}. tail starts
        with the cut heading itself. Only a heading-styled paragraph matching
        CUT_HEADING cuts; the word "References" in body text never does.
        Without a cut heading, every element is body and tail is empty.

    Side effects: none.
    """
    for index, element in enumerate(elements):
        if _is_heading(element) and CUT_HEADING.match(element["text"]):
            return {"body": elements[:index], "tail": elements[index:], "cut_found": True}
    return {"body": list(elements), "tail": [], "cut_found": False}


def clean_heading(text):
    """Clean a heading for display and for chunk titles.

    Args:
        text (str): The raw heading text.

    Returns:
        str: Without a leading "o " bullet or a dotted section number
        ("2. ", "2.1. ", "10. "), with whitespace collapsed. "3 Signs ..."
        keeps its number because no dot follows it.

    Side effects: none.
    """
    text = BULLET_PREFIX.sub("", " ".join(text.split()))
    return SECTION_NUMBER.sub("", text)


def _fold(text):
    """Fold text for loose equality: casefold, collapse spaces, drop end punctuation.

    Args:
        text (str | None): Any text.

    Returns:
        str: The folded text ("" for None).

    Side effects: none.
    """
    return " ".join((text or "").casefold().split()).rstrip(".!?:;,")


def _is_banner(text, guide_title):
    """Tell whether a pre-heading line is part of the guide's banner.

    Args:
        text (str): A paragraph before the first heading.
        guide_title (str | None): The guide title from the metadata.

    Returns:
        bool: True for the academy name line, a line equal to the title
        (folded), or the "HPA-XXXX-NNNN | ..." id line.

    Side effects: none.
    """
    text = " ".join(text.split())
    return bool(ACADEMY_LINE.match(text) or ID_LINE.match(text)
                or (guide_title and _fold(text) == _fold(guide_title)))


def _box(text, path):
    """Turn the text of a 1x1 box into a callout or a paragraph block.

    Args:
        text (str): The box text (paragraphs joined with "\\n").
        path (list[str]): The heading path the box sits under.

    Returns:
        dict: {"type": "callout", "title", "text", "path"} when the box opens
        with a short title and a colon (see MAX_CALLOUT_TITLE_WORDS,
        MAX_CALLOUT_TITLE_CHARS) and does not open with a quote mark;
        otherwise {"type": "paragraph", "text", "path"} with the whole text.

    Side effects: none.
    """
    title, colon, rest = text.partition(":")
    title = title.strip()
    if (colon and title and "\n" not in title and not text.startswith(QUOTE_MARKS)
            and len(title.split()) <= MAX_CALLOUT_TITLE_WORDS and len(title) <= MAX_CALLOUT_TITLE_CHARS):
        return {"type": "callout", "title": title, "text": rest.strip(), "path": path}
    return {"type": "paragraph", "text": text, "path": path}


def _table(rows, path):
    """Turn a multi-cell table into a table block.

    Args:
        rows (list[list[str]]): The table rows from read_docx.
        path (list[str]): The heading path the table sits under.

    Returns:
        dict: {"type": "table", "header": first row, "rows": the other rows
        without the ones whose cells are all empty, "path": path}.

    Side effects: none.
    """
    return {"type": "table", "header": rows[0] if rows else [],
            "rows": [row for row in rows[1:] if any(cell.strip() for cell in row)], "path": path}


def _is_caption_style(style):
    """Tell whether a paragraph style is a caption style ("Caption Custom", "Figure Caption").

    Args:
        style (str | None): The style name.

    Returns:
        bool: True when the name contains "caption".

    Side effects: none.
    """
    return "caption" in (style or "").casefold()


def list_item(element):
    """Read a paragraph as a list item, if it is one.

    Args:
        element (dict): A raw paragraph element.

    Returns:
        tuple[bool, str] | None: (ordered, item text) for a styled list
        paragraph (ordered only for ORDERED_STYLE) or a typed bullet (a
        non-heading, non-caption paragraph starting with one of
        BULLET_GLYPHS, always unordered). The glyph and the whitespace after
        it are stripped. None for any other paragraph.

    Side effects: none.
    """
    style, text = element.get("style") or "", element["text"]
    if element.get("list"):
        return style == ORDERED_STYLE, TYPED_BULLET.sub("", text).strip()
    if heading_level(style) is None and not _is_caption_style(style) and TYPED_BULLET.match(text):
        return False, TYPED_BULLET.sub("", text).strip()
    return None


def promote_headings(body):
    """Turn a numbered H1 that was typed as a Normal paragraph into a Heading 1.

    Some guides number their H1s ("1.", "2.", ...) and one of them was typed
    in body style, so its section would fall under the previous heading. A
    paragraph is promoted only when every guard holds:
        - it is not a heading or a list paragraph and matches NUMBERED_LINE;
        - it has at most MAX_PROMOTED_WORDS words and does not end with ".";
        - its number N is missing from the guide's numbered H1s;
        - it sits after numbered H1 N-1 (or before every numbered H1 when N
          is 1) and before numbered H1 N+1 (or, when no H1 is numbered above
          N, anywhere before the cut, which is the end of the body);
        - at least one of H1 N-1 and N+1 exists.
    Nothing else is ever promoted.

    Args:
        body (list[dict]): split_document(...)["body"].

    Returns:
        tuple[list[dict], list[int]]: (body with promoted paragraphs restyled
        as "Heading 1", the promoted numbers in order). The input is not
        changed.

    Side effects: none.
    """
    numbered = {}
    for index, element in enumerate(body):
        if element["kind"] == "paragraph" and heading_level(element.get("style")) == 1:
            match = NUMBERED_LINE.match(element["text"])
            if match:
                numbered.setdefault(int(match.group(1)), index)
    result, promoted = list(body), []
    for index, element in enumerate(body):
        if element["kind"] != "paragraph" or element.get("list") or heading_level(element.get("style")) is not None:
            continue
        text = element["text"].strip()
        match = NUMBERED_LINE.match(text)
        if not match or len(text.split()) > MAX_PROMOTED_WORDS or text.endswith("."):
            continue
        number = int(match.group(1))
        if number in numbered or number in promoted or not ({number - 1, number + 1} & numbered.keys()):
            continue
        after_previous = (index > numbered[number - 1] if number - 1 in numbered
                          else number == 1 and all(position > index for position in numbered.values()))
        before_next = (index < numbered[number + 1] if number + 1 in numbered
                       else all(n < number for n in numbered))
        if after_previous and before_next:
            result[index] = {**element, "style": "Heading 1", "list": False}
            promoted.append(number)
    return result, promoted


def body_blocks(body, guide_title):
    """Turn the body elements of one guide into ordered blocks.

    Args:
        body (list[dict]): split_document(...)["body"], after promote_headings.
        guide_title (str | None): The guide title, used to drop the title
            banner line.

    Returns:
        list[dict]: In document order, each one of
            {"type": "heading", "level": 1 | 2, "text": cleaned}
            {"type": "paragraph", "text", "path"}
            {"type": "list", "ordered": bool, "items": [...], "path"}
            {"type": "table", "header": [...], "rows": [[...]], "path"}
            {"type": "callout", "title", "text", "path"}
        path is the cleaned heading path: ["Introduction"] before the first
        heading, then [H1] or [H1, H2].

        Rules: banner lines before the first heading are dropped by pattern.
        An "In this guide" / "Contents" heading starts a section whose
        heading, plain paragraphs and lists are dropped; its boxes, tables and
        figure captions are kept under the path before it. The same words as
        a plain paragraph (any style) drop that line and the list directly
        after it. 1x1 tables are boxes (_box). A "Figure N." prefix is
        stripped from captions, and a caption line that continues the
        previous caption (same caption style, no "Figure" prefix) is joined
        to it. Consecutive list items (list_item) become one list block.

    Side effects: none.
    """
    blocks = []
    h1 = h2 = None
    seen_heading = in_contents = False
    path = [INTRO]
    # open_list: the list block the next list item extends. caption_style:
    # the style a wrapped caption line must have. skip_list: drop the list
    # directly after an unstyled "In this guide" line. Any other element
    # ends all three.
    open_list = caption_style = None
    skip_list = False
    for element in body:
        previous_caption, caption_style = caption_style, None
        if element["kind"] == "table":
            open_list, skip_list = None, False
            rows = element["rows"]
            if len(rows) == 1 and len(rows[0]) == 1:
                blocks.append(_box(rows[0][0], path))
            elif rows:
                blocks.append(_table(rows, path))
            continue
        text, style = element["text"], element.get("style", "")
        level = heading_level(style)
        if level is not None:
            open_list, skip_list = None, False
            seen_heading = True
            heading = clean_heading(text)
            in_contents = heading.casefold() in CONTENTS_HEADINGS
            if in_contents:
                # Leave the path alone, so kept boxes and captions take the
                # path of what came before the contents list.
                continue
            # The guides have no H3; anything deeper is treated as an H2.
            level = min(level, 2)
            if level == 1:
                h1, h2 = heading, None
            else:
                h2 = heading
            path = [part for part in (h1, h2) if part]
            blocks.append({"type": "heading", "level": level, "text": heading})
            continue
        if not seen_heading and _is_banner(text, guide_title):
            continue
        item = list_item(element)
        if item is not None:
            ordered, item_text = item
            if in_contents or skip_list or not item_text:
                continue
            if open_list is not None and open_list["ordered"] == ordered:
                open_list["items"].append(item_text)
            else:
                open_list = {"type": "list", "ordered": ordered, "items": [item_text], "path": path}
                blocks.append(open_list)
            continue
        open_list, skip_list = None, False
        if " ".join(text.split()).casefold() in CONTENTS_HEADINGS:
            # "In this guide" typed in a body style: drop the line and the
            # list right after it, keep everything else.
            skip_list = True
            continue
        if FIGURE_PREFIX.match(text):
            blocks.append({"type": "paragraph", "text": FIGURE_PREFIX.sub("", text), "path": path})
            # Only a dedicated caption style can wrap onto the next paragraph;
            # a caption typed in Normal must not swallow the body text after it.
            caption_style = style if _is_caption_style(style) else None
        elif previous_caption is not None and style == previous_caption:
            # A caption wrapped onto a second paragraph of the same style.
            blocks[-1]["text"] += " " + text
            caption_style = style
        elif not in_contents:
            blocks.append({"type": "paragraph", "text": text, "path": path})
    return blocks
