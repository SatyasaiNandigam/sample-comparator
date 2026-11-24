"""
word_extractor – converts .docx files into page-accurate list[str] for the BRD pipeline.

Usage:
    from word_extractor import extract_docx_pages

    pages = extract_docx_pages("path/to/brd.docx")
    # pages: list[str], one element per Word document page
"""
from .extractor import extract_docx_pages
