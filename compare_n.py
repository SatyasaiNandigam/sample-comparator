"""
N-document comparison (v0.1).

Compares every schema property across any number of documents (2 or more) in one pass.
Pairwise comparison is avoided: each property is judged from all N states together.

    from compare_n import DocInput, extract_n, compare_n

    docs = [DocInput("generated", "Generated", pages_gen),
            DocInput("vendor_a", "Vendor A", pages_a),
            DocInput("vendor_b", "Vendor B", pages_b)]

    results = extract_n(llm, docs)                    # {document_id: {key: PropertyResult}}
    report = compare_n(llm, docs, results)            # comparison dict (see below)

`report` is the input for api_response.to_api_response(); with two documents the rows carry
the same `documents` array as the N-document layout, so no adapter is needed there.

Status rules (per property, over all N documents)
-------------------------------------------------
  needs_review     any document's result failed verification, or a judge was uncertain
  all_na           every document says not applicable
  all_not_found    every document is silent
  not_comparable   a mix of not_applicable and not_found (cannot tell "none" from "silent")
  missing          found in some documents, silent in others
  different        found in some documents, not applicable in others, or values differ
  match            every document found it and the normalized values are equal

Text properties (compare = judge): values are first compared deterministically
(normalized equality, then numeric tokens). Anything still unresolved goes to ONE batched
judge call per document pair-set: each other document is judged against a reference
document (the first found one). So N-1 items per property, all in a single call.

Per-document status: documents are grouped by normalized value (`groups` in each row),
so the UI can show which documents agree without any logic of its own.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Optional

from comparator import JUDGE_SYSTEM, MATCH, DIFFERENT, NEEDS_REVIEW, _compare_text
from comparator import cmp_deep, cmp_set, judge_batch, summary, STATUS_LABEL
from group_prompts import GROUPS, LLM, PROMPT_VERSION, PropertyResult, RETRYABLE_FLAGS, extract_group
from normalizers import jsonable, normalize
from policy_schema import PROPERTIES, Property
from policy_schema import VERSION as SCHEMA_VERSION

# N-document statuses
MATCH_N = "match"
DIFFERENT_N = "different"
MISSING_N = "missing"
ALL_NA = "all_na"
ALL_NOT_FOUND = "all_not_found"
NOT_COMPARABLE = "not_comparable"
NEEDS_REVIEW_N = "needs_review"


@dataclass(frozen=True)
class DocInput:
    document_id: str
    label: str
    pages: list[str]


# --------------------------------------------------------------------------- #
# Extraction for N documents
# --------------------------------------------------------------------------- #
def extract_n(llm: LLM, docs: list[DocInput], max_workers: int = 6
              ) -> dict[str, dict[str, PropertyResult]]:
    """Run all groups for all documents through one bounded thread pool.

    A failed group is recorded as needs_review rather than aborting the run.
    Returns {document_id: {key: PropertyResult}}.
    """
    _check_docs(docs)
    out: dict[str, dict[str, PropertyResult]] = {d.document_id: {} for d in docs}
    errors: dict[str, dict[str, str]] = {d.document_id: {} for d in docs}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [(d.document_id, g,
                    ex.submit(extract_group, llm, d.pages, g, d.label))
                   for d in docs for g in GROUPS]
        for doc_id, group, fut in futures:
            try:
                out[doc_id].update(fut.result())
            except Exception as e:
                errors[doc_id][group] = f"{type(e).__name__}: {e}"

    for doc_id, errs in errors.items():
        for group, msg in errs.items():
            for p in PROPERTIES:
                if p.group == group:
                    out[doc_id][p.key] = PropertyResult(
                        key=p.key, state="not_found", flags={"group_failed"},
                        issues=[f"extraction of group '{group}' failed: {msg}"],
                        needs_review=True)
    return out


def _check_docs(docs: list[DocInput]) -> None:
    if len(docs) < 2:
        raise ValueError("at least two documents are required to compare")
    ids = [d.document_id for d in docs]
    if len(set(ids)) != len(ids):
        raise ValueError(f"document_id values must be unique: {ids}")


# --------------------------------------------------------------------------- #
# Per-property comparison over N documents
# --------------------------------------------------------------------------- #
@dataclass
class NRow:
    prop: Property
    statuses: dict                 # doc_id -> state
    normals: dict                  # doc_id -> normalized (found docs only)
    displays: dict                 # doc_id -> display text
    results: dict                  # doc_id -> PropertyResult
    status: str = ""
    reason: str = ""
    method: str = "state"
    detail: dict = None
    review_reasons: list = None
    groups: list = None            # [{"value": display, "documents": [ids]}] for found docs
    pending: Optional[dict] = None # doc_id -> text, for the judge
    judge_equal: dict = None       # doc_id -> True if judged equivalent to the reference


def _display_for(r: PropertyResult) -> str:
    from output_formatters import format_property
    entry = format_property(PROPERTY_BY_KEY[r.key], r) if r.key in PROPERTY_BY_KEY else None
    if entry:
        return entry["display"]
    if r.state == "found":
        return r.raw_value or json.dumps(jsonable(r.value), ensure_ascii=False)
    return {"not_applicable": "N/A", "not_found": "Not found"}.get(r.state, "Not found")


PROPERTY_BY_KEY = {p.key: p for p in PROPERTIES}


def _text_of(r: PropertyResult) -> str:
    if isinstance(r.value, str) and r.value.strip():
        return r.value
    if r.raw_value:
        return r.raw_value
    return json.dumps(jsonable(r.value), ensure_ascii=False)


def _group_by_value(found: list[str], keys: dict, displays: dict) -> list[dict]:
    """Bucket found documents by comparison key. keys[doc] -> hashable-json string,
    displays[doc] -> text to show for the group."""
    buckets: dict[str, dict] = {}
    for doc_id in found:
        b = buckets.setdefault(keys[doc_id], {"value": displays[doc_id], "documents": []})
        b["documents"].append(doc_id)
    return list(buckets.values())


def _key_of(v) -> str:
    return json.dumps(jsonable(v), sort_keys=True, ensure_ascii=False)


def compare_property_n(p: Property, results: dict[str, PropertyResult],
                       doc_ids: list[str]) -> NRow:
    states = {d: (results[d].state or "not_found") for d in doc_ids}
    row = NRow(prop=p, statuses=states, normals={}, displays={}, results=results,
               review_reasons=[], groups=[], detail={}, judge_equal={})
    row.displays = {d: _display_for(results[d]) for d in doc_ids}

    for d in doc_ids:
        r = results[d]
        if r.flags & RETRYABLE_FLAGS:
            row.review_reasons.append(f"{d}: " + ("; ".join(r.issues) or "not verified"))
        if "low_confidence" in r.flags and r.note:
            row.review_reasons.append(f"{d}: low confidence ({r.note})")
    unreliable = bool(row.review_reasons)

    found = [d for d in doc_ids if states[d] == "found"]
    vals = set(states.values())
    row.method = "state"

    if not found:
        if vals == {"not_applicable"}:
            row.status, row.reason = ALL_NA, "every document states it does not apply"
        elif vals == {"not_found"}:
            row.status, row.reason = ALL_NOT_FOUND, "no document mentions it"
        else:
            row.status = NOT_COMPARABLE
            row.reason = "some documents say it does not apply, others are silent"
    elif len(found) < len(doc_ids):
        silent = [d for d in doc_ids if states[d] != "found"]
        na = [d for d in silent if states[d] == "not_applicable"]
        if na and len(na) != len(silent):
            row.status = DIFFERENT_N
            row.reason = (f"found in {', '.join(found)}; not applicable in {', '.join(na)}; "
                          f"silent in {', '.join(s for s in silent if s not in na)}")
        elif na:
            row.status = DIFFERENT_N
            row.reason = f"found in {', '.join(found)}; not applicable in {', '.join(na)}"
        else:
            row.status = MISSING_N
            row.reason = f"not mentioned in {', '.join(silent)}"
    else:
        # every document found a value: compare normalized values
        try:
            for d in doc_ids:
                row.normals[d] = normalize(p.type, results[d].value)
        except Exception as e:
            row.status, row.reason, row.method = NEEDS_REVIEW_N, f"could not normalize: {e}", "error"
            return _finalize(row, True)

        if p.compare == "judge":
            keys = {d: _key_of(_text_of_norm(results[d])) for d in found}
            displays = {d: row.displays[d] for d in found}
            row.groups = _group_by_value(found, keys, displays)
            if len(row.groups) == 1:
                row.status, row.reason, row.method = MATCH_N, "same text after normalization", "exact"
            else:
                pend = _text_pending(results, found)
                if pend is None:
                    row.status, row.method = DIFFERENT_N, "numeric_tokens"
                    row.reason = "numbers differ across documents"
                else:
                    row.status, row.method = None, "llm_judge"
                    row.pending = pend
                    row.reason = "wording differs; awaiting judge"
        else:
            keys = {d: _key_of(row.normals[d]) for d in found}
            displays = {d: row.displays[d] for d in found}
            row.groups = _group_by_value(found, keys, displays)
            if len(row.groups) == 1:
                row.status, row.reason, row.method = MATCH_N, "values are the same", p.compare
            else:
                row.status, row.method = DIFFERENT_N, p.compare
                row.reason = _describe_groups(row.groups)

    return _finalize(row, bool(row.review_reasons))


def _text_of_norm(r: PropertyResult) -> str:
    if isinstance(r.value, str):
        return " ".join(r.value.casefold().split())
    return _key_of(r.value)


def _text_pending(results, found) -> Optional[dict]:
    """Return {doc_id: text} for the judge, or None if the texts are numerically different."""
    from comparator import _numbers
    texts = {d: _text_of(results[d]) for d in found}
    nums = {d: _numbers(t) for d, t in texts.items()}
    numeric = {tuple(v) for v in nums.values() if v}
    if len(numeric) > 1:
        return None
    return texts


def _describe_groups(groups: list[dict]) -> str:
    parts = [f"{', '.join(g['documents'])}: {_short(g['value'])}" for g in groups]
    return "; ".join(parts[:4]) + (f" (+{len(parts) - 4} more)" if len(parts) > 4 else "")


def _short(s: str, n: int = 60) -> str:
    s = str(s).replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def _finalize(row: NRow, unreliable: bool) -> NRow:
    if row.status is None:
        row.status = NEEDS_REVIEW_N
    if unreliable and row.status != NEEDS_REVIEW_N:
        row.status = NEEDS_REVIEW_N
    return row


# --------------------------------------------------------------------------- #
# Full comparison
# --------------------------------------------------------------------------- #
def compare_n(llm: Optional[LLM], docs: list[DocInput],
              results: dict[str, dict[str, PropertyResult]],
              use_judge: bool = True) -> dict:
    """Compare every property across all documents. Returns a comparison dict with:
    meta, summary, rows (one per property, with `documents` in input order)."""
    _check_docs(docs)
    doc_ids = [d.document_id for d in docs]
    rows = [compare_property_n(p, {d: results[d].get(p.key) or _missing(p.key)
                                   for d in doc_ids}, doc_ids)
            for p in PROPERTIES]

    pending = [r for r in rows if r.pending]
    if pending:
        verdicts = _judge_pending(llm, pending, use_judge)
        for r in pending:
            status, reason = verdicts[r.prop.key]
            r.status, r.reason, r.method = status, reason, "llm_judge"
            r.groups = _judge_groups(r)

    for r in rows:
        if r.status is None:
            r.status = NEEDS_REVIEW_N
            r.reason = r.reason or "could not be decided"

    return {
        "meta": {"schema_version": SCHEMA_VERSION, "prompt_version": PROMPT_VERSION,
                 "documents": [{"document_id": d.document_id, "label": d.label,
                                "pages": len(d.pages)} for d in docs]},
        "summary": _summary_n(rows),
        "rows": [_row_dict(r, doc_ids) for r in rows],
    }


def _missing(key: str) -> PropertyResult:
    return PropertyResult(key=key, state="not_found", flags={"missing_key"},
                          issues=["no result for this key"], needs_review=True)


def _judge_pending(llm: Optional[LLM], pending: list[NRow], use_judge: bool) -> dict:
    """One batched call. Each other document is judged against a reference document."""
    items, meta = [], {}
    for r in pending:
        texts = r.pending
        ids = list(texts)
        ref = ids[0]
        for other in ids[1:]:
            key = f"{r.prop.key}__{other}"
            items.append({"key": key, "label": f"{r.prop.label} ({ref} vs {other})",
                          "meaning": r.prop.description,
                          "a": texts[ref], "b": texts[other]})
            meta[key] = (r.prop.key, ref, other)

    if not items:
        return {r.prop.key: (NEEDS_REVIEW_N, "judge had nothing to compare") for r in pending}
    if llm is None or not use_judge:
        return {r.prop.key: (NEEDS_REVIEW_N, "wording differs; LLM judge not run")
                for r in pending}

    verdicts = judge_batch(llm, items)
    per_prop: dict[str, list] = {}
    for key, (verdict, why) in verdicts.items():
        pkey, ref, other = meta[key]
        per_prop.setdefault(pkey, []).append((other, verdict, why))

    out = {}
    for r in pending:
        res = per_prop.get(r.prop.key, [])
        for other, v, _ in res:
            r.judge_equal[other] = (v == "equivalent")
        if any(v == "uncertain" for _, v, _ in res):
            out[r.prop.key] = (NEEDS_REVIEW_N, "judge was uncertain: " +
                               "; ".join(f"{o}: {w}" for o, v, w in res if v == "uncertain"))
        elif any(v == "different" for _, v, _ in res):
            out[r.prop.key] = (DIFFERENT_N, "; ".join(
                f"{o} differs from {list(r.pending)[0]}: {w}" for o, v, w in res if v == "different"))
        else:
            out[r.prop.key] = (MATCH_N, "judge found the texts equivalent")
    return out


def _judge_groups(r: NRow) -> list[dict]:
    """Judge verdicts are per document against the reference; the reference is the group
    of documents whose text the judge found equivalent to it."""
    ids = list(r.pending)
    ref = ids[0]
    equal = [ref] + [d for d in ids[1:] if r.judge_equal.get(d)]
    groups = [{"value": r.displays[ref], "documents": equal}]
    groups += [{"value": r.displays[d], "documents": [d]} for d in ids[1:] if d not in equal]
    return groups


def _summary_n(rows: list[NRow]) -> dict:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1
    counts["total"] = len(rows)
    counts["flagged_for_review"] = sum(1 for r in rows if r.review_reasons or r.status == NEEDS_REVIEW_N)
    return counts


def _row_dict(r: NRow, doc_ids: list[str]) -> dict:
    p = r.prop
    documents = []
    for d in doc_ids:
        res = r.results[d]
        documents.append({
            "document_id": d,
            "state": r.statuses[d],
            "display": r.displays[d],
            "value": jsonable(res.value) if res.state == "found" else None,
            "normalized": jsonable(r.normals.get(d)),
        })
    return {
        "key": p.key, "label": p.label, "order": p.order, "group": p.group,
        "status": r.status, "reason": r.reason, "method": r.method,
        "groups": r.groups or [],
        "review": bool(r.review_reasons) or r.status == NEEDS_REVIEW_N,
        "review_reasons": r.review_reasons or [],
        "documents": documents,
    }


# --------------------------------------------------------------------------- #
# Selftest (offline, 3 documents)
# --------------------------------------------------------------------------- #
def selftest() -> None:
    from group_prompts import PropertyResult as PR

    def R(state="found", raw=None, value=None, flags=(), issues=()):
        return PR(key="x", state=state, raw_value=raw, value=value,
                  evidence=[{"quote": "q", "page": 1, "verified": True}]
                  if state != "not_found" else [], confidence="high",
                  flags=set(flags), issues=list(issues))

    def one(key, **kw):
        return {key: R(**kw)}

    docs = [DocInput("gen", "Generated", ["p"]),
            DocInput("v1", "Vendor 1", ["p"]),
            DocInput("v2", "Vendor 2", ["p"])]
    ids = [d.document_id for d in docs]

    def run(prop_key, per_doc):
        p = PROPERTY_BY_KEY[prop_key]
        return compare_property_n(p, {d: per_doc[d] for d in ids}, ids)

    # match across three
    r = run("product_launch_date", {
        "gen": R(raw="6/30/2014", value="2014-06-30"),
        "v1": R(raw="6/30/2014", value="2014-06-30"),
        "v2": R(raw="6/30/2014", value="2014-06-30")})
    assert r.status == MATCH_N

    # different: groups show which documents agree
    r = run("product_launch_date", {
        "gen": R(raw="6/30/2014", value="2014-06-30"),
        "v1": R(raw="4/6/2026", value="2026-04-06"),
        "v2": R(raw="6/30/2014", value="2014-06-30")})
    assert r.status == DIFFERENT_N and len(r.groups) == 2
    assert sorted(map(tuple, (g["documents"] for g in r.groups))) == [("gen", "v2"), ("v1",)]

    # missing: found in two, silent in one
    r = run("upcoming_fixed_rates", {
        "gen": R(value={"rates_pct": [5.8], "guarantee_years": None, "effective_date": None}),
        "v1": R("not_found"),
        "v2": R(value={"rates_pct": [5.8], "guarantee_years": None, "effective_date": None})})
    assert r.status == MISSING_N and "v1" in r.reason

    # N/A in one and found in others is different
    r = run("bonus", {"gen": R("not_applicable"), "v1": R(value="5% bonus"),
                      "v2": R("not_applicable")})
    assert r.status == DIFFERENT_N

    # all N/A, all silent, mixed N/A + silent
    assert run("bonus", {"gen": R("not_applicable"), "v1": R("not_applicable"),
                         "v2": R("not_applicable")}).status == ALL_NA
    assert run("bonus", {"gen": R("not_found"), "v1": R("not_found"),
                         "v2": R("not_found")}).status == ALL_NOT_FOUND
    assert run("bonus", {"gen": R("not_applicable"), "v1": R("not_found"),
                         "v2": R("not_applicable")}).status == NOT_COMPARABLE

    # unverified result on one document -> needs_review
    r = run("surrender_charge_waivers", {
        "gen": R(value=["Nursing Home"]),
        "v1": R(value=["Nursing Home"]),
        "v2": R(value=["Nursing Home"], flags={"quote_not_found"}, issues=["quote missing"])})
    assert r.status == NEEDS_REVIEW_N and r.review_reasons

    # set comparison ignores order and case
    r = run("distribution_channels", {
        "gen": R(value=["Bank", "Independent"]),
        "v1": R(value=["independent", "Bank"]),
        "v2": R(value=["Bank", "Independent"])})
    assert r.status == MATCH_N

    # text: deterministic match, then judge only for the differing one
    judge_calls = []

    def fake_llm(messages, response_format):
        judge_calls.append(response_format["json_schema"]["schema"]["properties"])
        keys = list(response_format["json_schema"]["schema"]["properties"])
        return json.dumps({k: {"verdict": "equivalent", "reason": "same terms"} for k in keys})

    dummy_results = {
        "gen": {"penalty_free_withdrawals": R(value="10% of premiums paid immediately")},
        "v1": {"penalty_free_withdrawals": R(value="10% of premiums paid immediately")},
        "v2": {"penalty_free_withdrawals": R(value="10 percent of premiums paid right away")},
    }
    for d in ids:
        dummy_results[d].setdefault("bonus", R("not_applicable"))
    report = compare_n(fake_llm, docs, {d: {**dummy_results[d]} for d in ids})
    row = {r["key"]: r for r in report["rows"]}
    assert row["penalty_free_withdrawals"]["status"] == MATCH_N
    # one batched call; each non-reference document judged against the reference (gen)
    assert len(judge_calls) == 1
    assert sorted(judge_calls[0]) == ["penalty_free_withdrawals__v1", "penalty_free_withdrawals__v2"]

    # full report shape: N documents in meta and in every row, in input order
    assert [d["document_id"] for d in report["meta"]["documents"]] == ids
    assert all([x["document_id"] for x in r["documents"]] == ids for r in report["rows"])
    assert len(report["rows"]) == 38
    json.dumps(report)

    # extraction over N docs with one failing group -> needs_review, others unaffected
    def extract_llm(messages, response_format):
        keys = list(response_format["json_schema"]["schema"]["properties"])
        doc_text = messages[1]["content"]
        if "compensation" in response_format["json_schema"]["name"] and "Vendor 2" in doc_text:
            raise RuntimeError("simulated outage")
        out = {k: {"evidence": [], "state": "not_found", "raw_value": None, "value": None,
                   "confidence": "high", "note": None} for k in keys}
        if "bonus" in out:
            out["bonus"].update(state="not_applicable", evidence=[{"quote": "Bonus | N/A", "page": 1}])
        return json.dumps(out)

    ex_docs = [DocInput("gen", "Generated", ["Bonus | N/A"]),
               DocInput("v1", "Vendor 1", ["Bonus | N/A"]),
               DocInput("v2", "Vendor 2", ["Bonus | N/A"])]
    res = extract_n(extract_llm, ex_docs)
    assert set(res) == {"gen", "v1", "v2"} and all(len(v) == 38 for v in res.values())
    assert res["v2"]["street_level_compensation"].needs_review
    assert not res["gen"]["street_level_compensation"].needs_review
    assert res["gen"]["bonus"].state == "not_applicable"

    # validation
    for bad in ([docs[0]], [DocInput("a", "A", []), DocInput("a", "B", [])]):
        try:
            compare_n(None, bad, {}); raise AssertionError("should reject")
        except ValueError:
            pass

    print("compare_n selftest OK:", report["summary"])


if __name__ == "__main__":
    selftest()
