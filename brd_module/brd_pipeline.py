"""
BRD extraction pipeline.

Entry point:
    result = extract_brd_documents(llm, documents, names)

Args:
    llm       – callable(messages, response_format) -> str  (e.g. LLMClient.call_openai)
    documents – list of page-lists, one per document (output of doc_extract.extract_pdf)
    names     – parallel list of human-readable document labels

Returns a dict matching the output JSON schema (format_version 1.0).
"""
from __future__ import annotations

import json
import pathlib
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from normalizers import normalize, jsonable
from .brd_schema import BRD_GROUPS, BRD_PROPERTIES, by_brd_group
from .brd_group_prompts import extract_brd_group

_OUT_DIR = pathlib.Path(__file__).parent / "out"


# =========================================================================== #
# 1.  Display-string generators (one per data type)
# =========================================================================== #
def _n(x) -> str:
    """Format a number cleanly: drop unnecessary decimal zeros."""
    if x is None:
        return "?"
    f = float(x)
    return str(int(f)) if f == int(f) else str(round(f, 4)).rstrip("0").rstrip(".")


def _make_display(type_: str, normalized: Any, raw_value: Optional[str],
                  original_value: Any = None) -> Optional[str]:
    """Build a human-readable string from a normalized value for UI rendering."""
    if normalized is None:
        return None

    if type_ in ("text", "enum_text"):
        return raw_value  # already human-readable

    if type_ == "date":
        return normalized  # ISO date string

    if type_ == "list_text":
        # Prefer the original pre-normalization list to preserve original casing.
        # Fall back to sorted normalized frozenset if original is unavailable.
        if isinstance(original_value, list) and original_value:
            return ", ".join(str(x) for x in original_value)
        items = sorted(normalized, key=str)
        return ", ".join(items) if items else None

    if type_ == "currency":
        amt = normalized.get("amount")
        if amt is None:
            return raw_value
        return f"${int(amt):,}" if float(amt) == int(amt) else f"${float(amt):,.2f}"

    if type_ == "currency_by_category":
        parts = []
        for cat, amt in sorted(normalized.items()):
            if amt is None:
                parts.append(f"{cat}: N/A")
            elif float(amt) == int(amt):
                parts.append(f"{cat}: ${int(amt):,}")
            else:
                parts.append(f"{cat}: ${float(amt):,.2f}")
        return " / ".join(parts) if parts else raw_value

    if type_ == "schedule":
        pcts = normalized.get("schedule_pct") or ()
        if not pcts:
            return raw_value
        return " → ".join(f"{_n(p)}%" for p in pcts)

    if type_ == "age_bands":
        parts = []
        for key, band in normalized.items():
            cat = key.split("|")[0]
            lo = band.get("min_age")
            hi = band.get("max_age")
            if lo is None and hi is None:
                continue
            lo_str = str(lo) if lo is not None else "0"
            hi_str = str(hi) if hi is not None else "+"
            rng = f"{lo_str}–{hi_str}"
            parts.append(f"{rng} ({cat})" if cat and cat != "-" else rng)
        return "; ".join(parts) if parts else raw_value

    if type_ == "state_set":
        # normalized is frozenset of NOT-approved state codes
        if not normalized:
            return "All states"
        excl = sorted(normalized)
        available = 51 - len(excl)   # 50 states + DC
        return f"Available in {available} states (excl. {', '.join(excl)})"

    if type_ == "rate_by_term":
        rates = normalized.get("rates_pct") or ()
        years = normalized.get("guarantee_years")
        rates_str = ", ".join(f"{_n(r)}%" for r in rates)
        if years:
            return f"{rates_str} ({years}-year guarantee)"
        return rates_str if rates_str else raw_value

    if type_ == "count_pair":
        indexed = normalized.get("indexed")
        fixed = normalized.get("fixed")
        parts = []
        if indexed is not None:
            parts.append(f"{indexed} indexed")
        if fixed is not None:
            parts.append(f"{fixed} fixed")
        return ", ".join(parts) if parts else raw_value

    if type_ == "pct_formula":
        varies = normalized.get("varies", False)
        pct = normalized.get("pct_of_premium")
        rmin = normalized.get("rate_min")
        rmax = normalized.get("rate_max")
        if varies:
            if rmin is not None and rmax is not None and rmax != rmin:
                return f"Varies ({_n(rmin)}%–{_n(rmax)}%)"
            if rmin is not None:
                return f"Varies ({_n(rmin)}%)"
            if pct is not None:
                return f"Varies ({_n(pct)}% of premium)"
            return "Varies"
        if pct is not None and rmin is not None:
            if rmax is not None and rmax != rmin:
                return f"{_n(pct)}% of premium at {_n(rmin)}%–{_n(rmax)}%"
            return f"{_n(pct)}% of premium at {_n(rmin)}%"
        if rmin is not None:
            if rmax is not None and rmax != rmin:
                return f"{_n(rmin)}%–{_n(rmax)}%"
            return f"{_n(rmin)}%"
        if pct is not None:
            return f"{_n(pct)}% of premium"
        return raw_value

    if type_ == "rate_band":
        band = normalized.get("band")
        threshold = normalized.get("threshold")
        if band and threshold is not None:
            t = int(threshold) if float(threshold) == int(threshold) else threshold
            return f"{band} / ${t:,}"
        return band or raw_value

    return raw_value


# =========================================================================== #
# 2.  Aggregate state across all documents for one property
# =========================================================================== #
def _aggregate_state(states: list) -> str:
    if not states:
        return "not_found"
    unique = set(states)
    if unique == {"found"}:
        return "found"
    if unique == {"not_applicable"}:
        return "not_applicable"
    if "found" not in unique:
        return "not_found"
    return "partial"


# =========================================================================== #
# 3.  Main pipeline
# =========================================================================== #
def extract_brd_documents(
    llm,
    documents: list,
    names: list,
) -> dict:
    """
    Extract, normalize, and generate display values for all BRD properties
    across N documents.

    Args:
        llm:       callable(messages, response_format) -> str
        documents: list of page-lists (one list[str] per document)
        names:     parallel list of human-readable document labels

    Returns:
        dict conforming to the output JSON schema (format_version "1.0")
    """
    if len(documents) != len(names):
        raise ValueError("documents and names must have equal length")

    document_infos = [
        {
            "document_id": f"doc_{i + 1}",
            "label": names[i],
            "pages": len(pages),
        }
        for i, pages in enumerate(documents)
    ]

    # ── extract all (doc, group) pairs concurrently ───────────────────────── #
    max_workers = min(16, len(documents) * len(BRD_GROUPS))
    task_futures: dict = {}

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for doc_idx, pages in enumerate(documents):
            doc_name = names[doc_idx]
            for group in BRD_GROUPS:
                future = pool.submit(
                    extract_brd_group, llm, pages, group, doc_name
                )
                task_futures[(doc_idx, group)] = future
    # all futures complete when the with-block exits (shutdown wait=True)

    # ── collect: doc_idx → {key: PropertyResult} ─────────────────────────── #
    doc_results: list = [{} for _ in documents]
    for (doc_idx, group), future in task_futures.items():
        try:
            group_results = future.result()
            doc_results[doc_idx].update(group_results)
        except Exception as exc:
            from group_prompts import PropertyResult
            for prop in by_brd_group(group):
                doc_results[doc_idx][prop.key] = PropertyResult(
                    key=prop.key,
                    state="not_found",
                    issues=[f"extraction failed: {exc}"],
                    needs_review=True,
                )

    # ── build output: property-centric with one entry per document ────────── #
    properties_out = []
    for prop in BRD_PROPERTIES:
        prop_docs = []
        states = []

        for doc_idx, doc_info in enumerate(document_infos):
            pr = doc_results[doc_idx].get(prop.key)

            if pr is None:
                prop_docs.append({
                    "document_id": doc_info["document_id"],
                    "doc_name": doc_info["label"],
                    "raw_value": None,
                    "normalized": None,
                    "display": None,
                    "evidence": [],
                    "confidence": None,
                    "note": "extraction result missing",
                })
                states.append("not_found")
                continue

            # normalize
            normalized = None
            if pr.state == "found" and pr.value is not None:
                try:
                    normalized = normalize(prop.type, pr.value)
                except Exception as exc:
                    pr.issues.append(f"normalization failed: {exc}")

            # display
            display = None
            if normalized is not None:
                try:
                    display = _make_display(
                        prop.type, normalized, pr.raw_value,
                        original_value=pr.value,
                    )
                except Exception:
                    display = pr.raw_value

            # note field: use PR note if present, otherwise encode non-found state
            note = pr.note
            if note is None and pr.state != "found":
                note = pr.state

            prop_docs.append({
                "document_id": doc_info["document_id"],
                "doc_name": doc_info["label"],
                "raw_value": pr.raw_value,
                "normalized": jsonable(normalized) if normalized is not None else None,
                "display": display,
                "evidence": pr.evidence,
                "confidence": pr.confidence if pr.state == "found" else None,
                "note": note,
            })
            states.append(pr.state or "not_found")

        properties_out.append({
            "key": prop.key,
            "label": prop.label,
            "group": prop.group,
            "state": _aggregate_state(states),
            "documents": prop_docs,
        })

    return {
        "format_version": "1.0",
        "documents": document_infos,
        "properties": properties_out,
    }


# =========================================================================== #
# 4.  Save helper
# =========================================================================== #
def save_brd_report(result: dict, path: Optional[str] = None) -> str:
    """Write the extraction result to JSON. Returns the path written."""
    if path is None:
        _OUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = _OUT_DIR / "brd_extraction.json"
    else:
        out_path = pathlib.Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)

    return str(out_path)


def compare_brd_docs() -> dict:
    """
    Take list of brd documents and list of names of the documents and return a dict with the comparison of the documents.
    """
    
    
    
    