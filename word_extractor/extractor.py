"""
Word document extractor – converts a .docx file into a list of page strings.

Each element in the returned list corresponds to one page of the Word document,
aligned with the page numbers shown in Word's status bar.

Page boundaries are detected from two XML signals:
  - <w:br w:type="page"/> – explicit (hard) page break inserted by the author
  - <w:lastRenderedPageBreak/> – soft page break recorded by Word on last save

Tables are formatted as markdown pipe tables so the LLM can read row/cell structure.
Headings (Heading1, Heading2, Heading3 styles) are prefixed with #, ##, ### markers.
"""
from __future__ import annotations

from docx import Document
from docx.oxml.ns import qn

# XML qualified names used for navigation
_W_P   = qn("w:p")       # paragraph
_W_TBL = qn("w:tbl")     # table
_W_TR  = qn("w:tr")      # table row
_W_TC  = qn("w:tc")      # table cell
_W_R   = qn("w:r")       # run
_W_T   = qn("w:t")       # text node
_W_BR  = qn("w:br")      # break element
_W_LRPB = qn("w:lastRenderedPageBreak")
_W_PST = qn("w:pStyle")  # paragraph style
_W_PPR = qn("w:pPr")     # paragraph properties
_W_RPR = qn("w:rPr")     # run properties

_HEADING_PREFIXES = {
    "heading1": "# ",
    "heading2": "## ",
    "heading3": "### ",
    "heading4": "#### ",
}


# =========================================================================== #
# Helpers
# =========================================================================== #

def _heading_prefix(para_elem) -> str:
    """Return '# ', '## ', '### ' etc. based on paragraph style, or '' if not a heading."""
    ppr = para_elem.find(_W_PPR)
    if ppr is None:
        return ""
    pst = ppr.find(_W_PST)
    if pst is None:
        return ""
    style_val = (pst.get(qn("w:val")) or "").lower().replace(" ", "")
    return _HEADING_PREFIXES.get(style_val, "")


def _run_has_page_break(run_elem) -> bool:
    """True if this run contains an explicit or soft page break."""
    # Explicit page break: <w:br w:type="page"/>
    for br in run_elem.iter(_W_BR):
        if br.get(qn("w:type")) == "page":
            return True
    # Soft page break: <w:lastRenderedPageBreak/>
    for _ in run_elem.iter(_W_LRPB):
        return True
    return False


def _run_text(run_elem) -> str:
    """Concatenate all <w:t> text nodes in a run, preserving spaces."""
    parts = []
    for t in run_elem.iter(_W_T):
        parts.append(t.text or "")
    return "".join(parts)


def _cell_text(cell_elem) -> str:
    """Extract plain text from a table cell (concatenate all paragraphs)."""
    lines = []
    for p in cell_elem.iter(_W_P):
        parts = []
        for r in p.iter(_W_R):
            parts.append(_run_text(r))
        text = "".join(parts).strip()
        if text:
            lines.append(text)
    return " ".join(lines)


def _extract_table(tbl_elem) -> str:
    """Format a <w:tbl> element as a markdown pipe table."""
    rows = []
    for tr in tbl_elem.iter(_W_TR):
        # Skip nested table rows — iter() descends into nested tables too.
        # Only take direct <w:tc> children of this <w:tr>.
        cells = [_cell_text(tc) for tc in tr if tc.tag == _W_TC]
        rows.append(cells)

    if not rows:
        return ""

    # Build markdown table
    lines = []
    for i, row in enumerate(rows):
        line = "| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |"
        lines.append(line)
        if i == 0:
            # Header separator after first row
            lines.append("| " + " | ".join("---" for _ in row) + " |")

    return "\n".join(lines)


def _extract_paragraph(para_elem) -> tuple[list[str], bool]:
    """
    Extract text from a paragraph element.

    Returns:
        (texts, had_page_break)
        texts: list of text fragments — may be split into two parts if a page
               break was found mid-paragraph (before_break, after_break).
               If no page break, contains a single string.
        had_page_break: True if a page break was found in this paragraph.
    """
    prefix = _heading_prefix(para_elem)
    before_parts: list[str] = []
    after_parts: list[str] = []
    found_break = False

    for child in para_elem:
        if child.tag != _W_R:
            continue
        run = child
        if not found_break and _run_has_page_break(run):
            found_break = True
            # Text in this run after the break goes to the new page.
            # (In practice the run either has the break OR text, rarely both.)
            t = _run_text(run).strip()
            if t:
                after_parts.append(t)
        else:
            t = _run_text(run)
            if found_break:
                after_parts.append(t)
            else:
                before_parts.append(t)

    before_text = (prefix + "".join(before_parts)).strip()
    after_text = (prefix + "".join(after_parts)).strip()

    if found_break:
        return [before_text, after_text], True
    return [before_text], False


# =========================================================================== #
# Public API
# =========================================================================== #

def extract_docx_pages(docx_path: str) -> list[str]:
    """
    Read a .docx file and return a list of page strings.

    Each element corresponds to one page of the Word document, aligned with
    the page numbers shown in Word's status bar.  Tables are formatted as
    markdown pipe tables; headings carry # markers.

    Args:
        docx_path: Path to the .docx file.

    Returns:
        list[str] with at least one element.
    """
    doc = Document(docx_path)

    pages: list[list[str]] = [[]]   # pages[i] = list of text chunks on page i+1

    for elem in doc.element.body:
        tag = elem.tag

        if tag == _W_P:
            fragments, had_break = _extract_paragraph(elem)

            if had_break:
                # fragments[0] belongs to current page; fragments[1] starts new page
                before = fragments[0]
                after = fragments[1] if len(fragments) > 1 else ""
                if before:
                    pages[-1].append(before)
                pages.append([])
                if after:
                    pages[-1].append(after)
            else:
                text = fragments[0]
                if text:
                    pages[-1].append(text)

        elif tag == _W_TBL:
            table_text = _extract_table(elem)
            if table_text:
                pages[-1].append(table_text)

    # Collapse each page's chunks into a single string; drop fully empty pages
    result = ["\n".join(chunks).strip() for chunks in pages]
    result = [p for p in result if p]

    return result if result else [""]


# =========================================================================== #
# CLI helper
# =========================================================================== #
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python extractor.py <path/to/file.docx> [page_number]")
        raise SystemExit(1)

    path = sys.argv[1]
    pages = extract_docx_pages(path)
    print(f"Extracted {len(pages)} page(s) from {path!r}")

    target = int(sys.argv[2]) if len(sys.argv) > 2 else None
    if target is not None:
        idx = target - 1
        if 0 <= idx < len(pages):
            print(f"\n--- Page {target} ---")
            print(pages[idx])
        else:
            print(f"Page {target} out of range (1–{len(pages)})")
    else:
        for i, page in enumerate(pages, 1):
            print(f"\n{'='*60}")
            print(f"PAGE {i}")
            print('='*60)
            print(page[:500] + ("..." if len(page) > 500 else ""))
