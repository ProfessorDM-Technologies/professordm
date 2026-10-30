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
    body_blocks      body elements -> heading, paragraph, list, table and
                     callout blocks with their heading path
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


def body_blocks(body, guide_title):
    """Turn the body elements of one guide into ordered blocks.

    Args:
        body (list[dict]): split_document(...)["body"].
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

        Rules: banner lines before the first heading are dropped by pattern;
        an "In this guide" / "Contents" section loses its heading, paragraphs
        and lists but keeps its boxes and tables (under the path before it);
        1x1 tables are boxes (_box); a "Figure N." prefix is stripped from
        captions, and a caption line that continues the previous caption (same
        caption style, no "Figure" prefix) is joined to it; consecutive list
        paragraphs become one list block, ordered only for ORDERED_STYLE.

    Side effects: none.
    """
    blocks = []
    h1 = h2 = None
    seen_heading = in_contents = False
    path = [INTRO]
    # The list block that the next list paragraph extends, and the style of
    # the caption that the next paragraph may continue. Any other element
    # ends both.
    open_list = caption_style = None
    for element in body:
        previous_caption, caption_style = caption_style, None
        if element["kind"] == "table":
            open_list = None
            rows = element["rows"]
            if len(rows) == 1 and len(rows[0]) == 1:
                blocks.append(_box(rows[0][0], path))
            elif rows:
                blocks.append(_table(rows, path))
            continue
        text, style = element["text"], element.get("style", "")
        level = heading_level(style)
        if level is not None:
            open_list = None
            seen_heading = True
            heading = clean_heading(text)
            in_contents = heading.casefold() in CONTENTS_HEADINGS
            if in_contents:
                # Leave the path alone, so a kept box takes the path of what
                # came before the contents list.
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
        if in_contents or (not seen_heading and _is_banner(text, guide_title)):
            continue
        if element.get("list"):
            ordered = style == ORDERED_STYLE
            if open_list is not None and open_list["ordered"] == ordered:
                open_list["items"].append(text)
            else:
                open_list = {"type": "list", "ordered": ordered, "items": [text], "path": path}
                blocks.append(open_list)
            continue
        open_list = None
        if FIGURE_PREFIX.match(text):
            blocks.append({"type": "paragraph", "text": FIGURE_PREFIX.sub("", text), "path": path})
            # Only a dedicated caption style can wrap onto the next paragraph;
            # a caption typed in Normal must not swallow the body text after it.
            caption_style = style if "caption" in style.casefold() else None
        elif previous_caption is not None and style == previous_caption:
            # A caption wrapped onto a second paragraph of the same style.
            blocks[-1]["text"] += " " + text
            caption_style = style
        else:
            blocks.append({"type": "paragraph", "text": text, "path": path})
    return blocks
