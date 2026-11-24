"""
Group prompt builder and extractor for BRD documents.

Mirrors the structure of group_prompts.py but targets BRD-specific sections
(PROV-xx and CALC-xxx tables).  Reuses helpers from the parent package
read-only; no existing files are modified.

Usage:
    results = extract_brd_group(llm, pages, "withdrawals", doc_name="BRD v2.3")
    # results: dict[str, PropertyResult]
"""
from __future__ import annotations

import json
import re
import sys
import pathlib
from typing import Optional

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

# ── reuse from parent package (read-only) ──────────────────────────────────── #
from group_prompts import (
    SYSTEM_PROMPT,
    VALUE_SHAPES,
    PropertyResult,
    RETRYABLE_FLAGS,
    verify_group_response,
    format_document,
)
from .brd_schema import BRD_GROUPS, by_brd_group, BY_BRD_KEY

PROMPT_VERSION = "0.1"


# =========================================================================== #
# 1.  BRD-aware system prompt
# =========================================================================== #
BRD_PREAMBLE = """\
You are extracting from a Business Requirements Document (BRD) for an insurance \
annuity product. BRDs are technical specification documents organised as numbered \
provision tables (PROV-01, PROV-02, …, PROV-15) and calculation tables \
(CALC-001, CALC-002, …, CALC-013). All quantitative rules and formulas live in \
these numbered tables; each property description identifies its source section.

When extracting formulas (CALC-xxx sections), copy the complete mathematical \
expression verbatim (e.g. "CV × (1 + r)^(d/365)"). Do not paraphrase or \
simplify a formula.

"""

BRD_SYSTEM_PROMPT = BRD_PREAMBLE + SYSTEM_PROMPT


# =========================================================================== #
# 2.  Group-level guidance
# =========================================================================== #
BRD_GROUP_GUIDANCE: dict[str, str] = {
    "product_identity": (
        "Identity details often appear on the cover page, header rows, or title block. "
        "The BRD version date is the document revision date, not the product launch date."
    ),
    "eligibility": (
        "Issue ages and plan types are usually in PROV-01 tables, often split by "
        "Qualified/Non-Qualified categories. Premium bands appear in PROV-02. "
        "State availability may be listed as an approved or not-approved set."
    ),
    "crediting": (
        "GOA crediting rules are in PROV-03; FOA cap and reallocation in PROV-04; "
        "GOP renewal in PROV-05. Rates are percentages as plain numbers (5.45, not 5.45%)."
    ),
    "withdrawals": (
        "Free withdrawal percentage and systematic options are in PROV-06; "
        "RMD/SEPP in PROV-07; withdrawal charge schedule and MVA in PROV-08; "
        "full surrender in PROV-09. Capture the complete year-by-year charge schedule "
        "under withdrawal_charge_schedule; record MVA applicability in its mva field."
    ),
    "benefits": (
        "Minimum value guarantee and basis are in PROV-10; death benefit in PROV-11; "
        "annuitization and maturity in PROV-12; waiver riders in PROV-13; "
        "contract-party changes in PROV-14."
    ),
    "calculations": (
        "Every property in this group maps to a specific CALC-xxx table. Extract the "
        "formula expression verbatim from the table cell. If the section lists multiple "
        "variants, capture the primary (base-case) formula and note the variants."
    ),
    "processing": (
        "Transaction processing order is in Section 8.1 (usually an ordered list). "
        "Reconciliation tolerances are in Section 11.2. Open decisions in Section 12. "
        "Acceptance criteria in Section 14.1."
    ),
}


# =========================================================================== #
# 3.  JSON schema helpers (small, self-contained)
# =========================================================================== #
def _obj(props: dict) -> dict:
    return {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


_STR_N = {"type": ["string", "null"]}


def _property_result_schema(type_: str) -> dict:
    from group_prompts import SYSTEM_PROMPT  # ensure VALUE_SHAPES already imported
    return _obj({
        "evidence": {
            "type": "array",
            "items": _obj({"quote": {"type": "string"},
                           "page": {"type": "integer"}}),
        },
        "state": {"type": "string", "enum": ["found", "not_applicable", "not_found"]},
        "raw_value": _STR_N,
        "value": _nullable(VALUE_SHAPES[type_][0]),
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "note": _STR_N,
    })


def _build_json_schema(group: str, only_keys: Optional[list] = None) -> dict:
    props = by_brd_group(group)
    if only_keys is not None:
        only_set = set(only_keys)
        props = [p for p in props if p.key in only_set]
    return _obj({p.key: _property_result_schema(p.type) for p in props})


def build_brd_response_format(group: str,
                               only_keys: Optional[list] = None) -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": f"brd_{group}_extraction",
            "strict": True,
            "schema": _build_json_schema(group, only_keys),
        },
    }


# =========================================================================== #
# 4.  Task block
# =========================================================================== #
def _render_brd_property(p) -> str:
    shape_text = VALUE_SHAPES[p.type][1]
    lines = [f'<property key="{p.key}" label="{p.label}" type="{p.type}">']
    lines.append(f"description: {p.description}")
    if p.aliases:
        lines.append("also_called: " + "; ".join(p.aliases))
    if p.na_means:
        lines.append(f"not_applicable_means: {p.na_means}")
    lines.append(f"value_shape: {shape_text}")
    if p.format_hint:
        lines.append(f"format_hint: {p.format_hint}")
    if p.notes:
        lines.append(f"notes: {p.notes}")
    lines.append("</property>")
    return "\n".join(lines)


def _build_group_task(
    group: str,
    only_keys: Optional[list] = None,
    feedback: Optional[dict] = None,
) -> str:
    if group not in BRD_GROUPS:
        raise ValueError(f"unknown BRD group {group!r}")
    props = by_brd_group(group)
    if only_keys is not None:
        only_set = set(only_keys)
        props = [p for p in props if p.key in only_set]

    count = len(props)
    noun = "property" if count == 1 else "properties"
    parts = [
        "<task>",
        f'Extract the {count} {noun} below (group "{group}") from the BRD document '
        "above. Return one result per property key, exactly as the response schema "
        "requires.",
    ]
    if group in BRD_GROUP_GUIDANCE:
        parts.append(f"Group guidance: {BRD_GROUP_GUIDANCE[group]}")
    parts.append("</task>")
    parts.append("<properties>")
    parts.extend(_render_brd_property(p) for p in props)
    parts.append("</properties>")

    if feedback:
        parts.append("<corrections>")
        parts.append(
            "Your previous answer had problems. Re-extract these properties carefully, "
            "quoting the document verbatim:"
        )
        for key, issue in feedback.items():
            parts.append(f"- {key}: {issue}")
        parts.append("</corrections>")
    return "\n".join(parts)


def build_brd_messages(
    pages: list,
    group: str,
    doc_name: str = "document",
    only_keys: Optional[list] = None,
    feedback: Optional[dict] = None,
) -> list:
    task = _build_group_task(group, only_keys, feedback)
    return [
        {"role": "system", "content": BRD_SYSTEM_PROMPT},
        {"role": "user", "content": format_document(pages, doc_name) + "\n\n" + task},
    ]


# =========================================================================== #
# 5.  Extraction orchestration (one group, with one targeted retry)
# =========================================================================== #
def extract_brd_group(
    llm,
    pages: list,
    group: str,
    doc_name: str = "document",
    max_retries: int = 1,
) -> dict:
    """Extract one BRD property group with quote verification and one retry pass."""
    all_keys = [p.key for p in by_brd_group(group)]
    results: dict = {}
    todo, feedback = all_keys, None

    for _ in range(max_retries + 1):
        messages = build_brd_messages(pages, group, doc_name,
                                      only_keys=todo, feedback=feedback)
        raw = llm(messages, build_brd_response_format(group, todo))
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            data = {}

        verified = verify_group_response(data, pages, todo)
        results.update(verified)
        todo = [k for k, r in verified.items() if r.retryable]
        if not todo:
            break
        feedback = {k: "; ".join(results[k].issues) for k in todo}

    return {k: results[k] for k in all_keys}
