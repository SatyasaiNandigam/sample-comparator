"""
End-to-end pipeline (v0.1): two documents -> side-by-side comparison report.

    from pipeline import compare_documents, save_report

    pages_a = pdf_to_pages("generated_policy.pdf")      # Document Intelligence / PyMuPDF
    pages_b = pdf_to_pages("third_party_policy.pdf")

    report = compare_documents(llm, pages_a, pages_b, name_a="Generated", name_b="Third party")
    save_report(report, "out/comparison")               # comparison.json + comparison.md

12 extraction calls (6 groups x 2 documents) plus at most 1 judge call. Lower `max_workers`
if your endpoint rate-limits you.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor

from comparator import compare_all, rows_to_markdown, summary
from group_prompts import GROUPS, LLM, PROMPT_VERSION, PropertyResult, extract_group
from policy_schema import VERSION as SCHEMA_VERSION


def extract_document(llm: LLM, pages: list[str], doc_name: str = "document",
                     max_workers: int = 6) -> dict[str, PropertyResult]:
    """All groups for one document, run in parallel."""
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {g: ex.submit(extract_group, llm, pages, g, doc_name) for g in GROUPS}
        merged: dict[str, PropertyResult] = {}
        for g in GROUPS:
            merged.update(futures[g].result())
    return merged


def compare_documents(llm: LLM, pages_a: list[str], pages_b: list[str],
                      name_a: str = "A", name_b: str = "B",
                      max_workers: int = 6, use_judge: bool = True) -> dict:
    """Extract both documents concurrently, then compare."""
    with ThreadPoolExecutor(max_workers=2) as outer:
        fa = outer.submit(extract_document, llm, pages_a, name_a, max_workers)
        fb = outer.submit(extract_document, llm, pages_b, name_b, max_workers)
        results_a, results_b = fa.result(), fb.result()

    rows = compare_all(results_a, results_b, llm if use_judge else None)
    return {
        "meta": {"schema_version": SCHEMA_VERSION, "prompt_version": PROMPT_VERSION,
                 "doc_a": name_a, "doc_b": name_b,
                 "pages_a": len(pages_a), "pages_b": len(pages_b)},
        "summary": summary(rows),
        "rows": [r.to_dict() for r in rows],
        "markdown": rows_to_markdown(rows, name_a, name_b),
    }


def save_report(report: dict, path_stem: str) -> None:
    os.makedirs(os.path.dirname(path_stem) or ".", exist_ok=True)
    with open(path_stem + ".json", "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in report.items() if k != "markdown"},
                  f, indent=2, ensure_ascii=False)
    with open(path_stem + ".md", "w", encoding="utf-8") as f:
        f.write(report["markdown"])


if __name__ == "__main__":
    from LLMClient import call_openai
    from group_prompts import split_markdown_pages
    from doc_extract import extract_doc_as_markdown

    pages_a = split_markdown_pages(extract_doc_as_markdown("sample.docx"))
    pages_b = split_markdown_pages(extract_doc_as_markdown("sample2.docx"))

    report = compare_documents(call_openai, pages_a, pages_b, name_a="sample", name_b="sample2")
    print(report)
    save_report(report, "out/comparison")