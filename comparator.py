"""
Comparator (v0.1): two sets of extraction results -> side-by-side rows.

    rows = compare_all(results_a, results_b, llm=llm)   # llm only needed for text judging
    print(rows_to_markdown(rows, "Doc A", "Doc B"))

Status logic
------------
Both sides 'found'                     -> compare values (deterministic first, LLM judge last)
found vs not_applicable                -> different      (one side has it, the other says none)
found vs not_found                     -> missing_in_a / missing_in_b (that side is silent)
not_applicable vs not_applicable       -> both_na
not_found vs not_found                 -> not_found_both
not_applicable vs not_found            -> not_comparable (cannot tell "none" from "silent")
extraction unreliable on either side   -> needs_review   (quote failed verification, etc.)

`review` is a separate flag: it is also set for low confidence, without changing the status.

Comparison strategy comes from Property.compare in policy_schema.py:
  exact / numeric / schedule / bands / by_key -> deep comparison of normalized values
  set                                         -> set difference
  judge                                       -> normalized-text equality, then number check,
                                                 then ONE batched LLM call for what is left
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from group_prompts import LLM, RETRYABLE_FLAGS, PropertyResult, _obj
from normalizers import jsonable, norm_text, normalize
from policy_schema import PROPERTIES, Property

# --------------------------------------------------------------------------- #
# Statuses
# --------------------------------------------------------------------------- #
MATCH = "match"
DIFFERENT = "different"
MISSING_A = "missing_in_a"
MISSING_B = "missing_in_b"
BOTH_NA = "both_na"
NOT_FOUND_BOTH = "not_found_both"
NOT_COMPARABLE = "not_comparable"
NEEDS_REVIEW = "needs_review"

STATUS_LABEL = {
    MATCH: "✅ Match",
    DIFFERENT: "❌ Different",
    MISSING_A: "➖ Missing in A",
    MISSING_B: "➖ Missing in B",
    BOTH_NA: "⚪ Both N/A",
    NOT_FOUND_BOTH: "⚪ Not found (both)",
    NOT_COMPARABLE: "❔ N/A vs not found",
    NEEDS_REVIEW: "⚠️ Needs review",
}

_ABSENT = "<absent>"


# --------------------------------------------------------------------------- #
# Deterministic comparison primitives
# --------------------------------------------------------------------------- #
def _is_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def deep_diff(a: Any, b: Any, path: str = "", tol: float = 1e-6) -> list[tuple]:
    """List of (path, a_value, b_value). Floats compare with a tolerance."""
    if isinstance(a, dict) and isinstance(b, dict):
        diffs: list[tuple] = []
        for k in sorted(set(a) | set(b), key=str):
            p = f"{path}.{k}" if path else str(k)
            diffs += deep_diff(a.get(k, _ABSENT), b.get(k, _ABSENT), p, tol)
        return diffs
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        same = len(a) == len(b) and all(not deep_diff(x, y, "", tol) for x, y in zip(a, b))
        return [] if same else [(path, list(a), list(b))]
    if _is_num(a) and _is_num(b):
        return [] if abs(a - b) <= tol else [(path, a, b)]
    return [] if a == b else [(path, a, b)]


def _fmt(v: Any) -> str:
    if v is None:
        return "not stated"
    if isinstance(v, float):
        return f"{v:g}"
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_fmt(x) for x in v) + "]"
    return str(v)


def _clip(items: list, limit: int = 15) -> str:
    s = ", ".join(str(i) for i in items[:limit])
    return s + (f" (+{len(items) - limit} more)" if len(items) > limit else "")


def cmp_deep(a: Any, b: Any):
    diffs = deep_diff(a, b)
    if not diffs:
        return True, "values are the same", {}
    shown = "; ".join(f"{p or 'value'}: {_fmt(x)} vs {_fmt(y)}" for p, x, y in diffs[:5])
    if len(diffs) > 5:
        shown += f" (+{len(diffs) - 5} more)"
    return False, shown, {"diffs": [{"path": p, "a": jsonable(x), "b": jsonable(y)}
                                    for p, x, y in diffs]}


def cmp_set(a: frozenset, b: frozenset):
    only_a, only_b = sorted(a - b), sorted(b - a)
    if not only_a and not only_b:
        return True, "same set", {}
    parts = []
    if only_a:
        parts.append(f"only in A ({len(only_a)}): {_clip(only_a)}")
    if only_b:
        parts.append(f"only in B ({len(only_b)}): {_clip(only_b)}")
    return False, "; ".join(parts), {"only_in_a": only_a, "only_in_b": only_b}


COMPARATORS = {
    "exact": cmp_deep,
    "numeric": cmp_deep,
    "schedule": cmp_deep,
    "bands": cmp_deep,
    "by_key": cmp_deep,
    "set": cmp_set,
}


# --------------------------------------------------------------------------- #
# Row model
# --------------------------------------------------------------------------- #
@dataclass
class Side:
    state: str
    display: str
    value: Any
    normalized: Any
    evidence: list
    confidence: str
    flags: list
    note: Optional[str]


@dataclass
class Row:
    key: str
    label: str
    order: int
    group: str
    status: Optional[str]
    base_status: Optional[str]
    reason: str
    method: str
    detail: dict
    a: Side
    b: Side
    review: bool = False
    review_reasons: list = field(default_factory=list)
    _pending: Optional[tuple] = field(default=None, repr=False)     # (text_a, text_b)
    _unreliable: bool = field(default=False, repr=False)

    def to_dict(self) -> dict:
        def side(s: Side) -> dict:
            return {"state": s.state, "display": s.display, "value": s.value,
                    "normalized": jsonable(s.normalized), "evidence": s.evidence,
                    "confidence": s.confidence, "flags": s.flags, "note": s.note}
        return {"key": self.key, "label": self.label, "order": self.order,
                "group": self.group, "status": self.status,
                "base_status": self.base_status, "reason": self.reason,
                "method": self.method, "detail": self.detail,
                "review": self.review, "review_reasons": self.review_reasons,
                "a": side(self.a), "b": side(self.b)}


def _missing_result(key: str) -> PropertyResult:
    return PropertyResult(key=key, state="not_found", flags={"missing_key"},
                          issues=["no result for this key"], needs_review=True)


def _display(r: PropertyResult) -> str:
    if r.state == "found":
        if r.raw_value:
            return r.raw_value
        return json.dumps(jsonable(r.value), ensure_ascii=False)
    if r.state == "not_applicable":
        return "N/A"
    return "Not found"


# --------------------------------------------------------------------------- #
# Text properties: deterministic checks before any LLM call
# --------------------------------------------------------------------------- #
_NUM_RE = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")


def _numbers(text: str) -> list[float]:
    return sorted(float(m.replace(",", "")) for m in _NUM_RE.findall(text or ""))


def _text_of(r: PropertyResult) -> str:
    if isinstance(r.value, str) and r.value.strip():
        return r.value
    if r.raw_value:
        return r.raw_value
    return json.dumps(jsonable(r.value), ensure_ascii=False)


def _compare_text(ra: PropertyResult, rb: PropertyResult):
    ta, tb = _text_of(ra), _text_of(rb)
    if norm_text(ta) == norm_text(tb):
        return MATCH, "same text after normalization", "exact", {}, None
    na, nb = _numbers(ta), _numbers(tb)
    if na and nb and na != nb:
        return (DIFFERENT, f"numbers differ: {_fmt(na)} vs {_fmt(nb)}", "numeric_tokens",
                {"numbers_a": na, "numbers_b": nb}, None)
    return None, "", "judge", {}, (ta, tb)       # leave to the LLM judge


# --------------------------------------------------------------------------- #
# Compare one property
# --------------------------------------------------------------------------- #
def compare_property(p: Property, ra: PropertyResult, rb: PropertyResult) -> Row:
    sa, sb = ra.state or "not_found", rb.state or "not_found"

    def mk_side(r: PropertyResult, state: str, norm: Any = None) -> Side:
        return Side(state=state, display=_display(r), value=r.value, normalized=norm,
                    evidence=r.evidence, confidence=r.confidence,
                    flags=sorted(r.flags), note=r.note)

    # review bookkeeping
    reasons: list[str] = []
    unreliable = False
    for name, r in (("A", ra), ("B", rb)):
        if r.flags & RETRYABLE_FLAGS:
            unreliable = True
            reasons.append(f"{name}: " + ("; ".join(r.issues) or "extraction not verified"))
        if r.confidence == "low" and "low_confidence" in r.flags:
            reasons.append(f"{name}: low confidence" + (f" ({r.note})" if r.note else ""))

    status: Optional[str] = None
    reason, method, detail, pending = "", "state", {}, None
    norm_a = norm_b = None

    if sa == "found" and sb == "found":
        try:
            norm_a, norm_b = normalize(p.type, ra.value), normalize(p.type, rb.value)
        except Exception as e:                          # malformed typed value
            status, reason, method = NEEDS_REVIEW, f"could not normalize value: {e}", "error"
            unreliable = True
        else:
            if p.compare == "judge":
                status, reason, method, detail, pending = _compare_text(ra, rb)
            else:
                same, reason, detail = COMPARATORS[p.compare](norm_a, norm_b)
                status, method = (MATCH if same else DIFFERENT), p.compare
    elif sa == "found" and sb == "not_applicable":
        status, reason = DIFFERENT, "A has a value; B states it does not apply"
    elif sa == "not_applicable" and sb == "found":
        status, reason = DIFFERENT, "A states it does not apply; B has a value"
    elif sa == "found" and sb == "not_found":
        status, reason = MISSING_B, "B does not mention it"
    elif sa == "not_found" and sb == "found":
        status, reason = MISSING_A, "A does not mention it"
    elif sa == "not_applicable" and sb == "not_applicable":
        status, reason = BOTH_NA, "both state it does not apply"
    elif sa == "not_found" and sb == "not_found":
        status, reason = NOT_FOUND_BOTH, "neither document mentions it"
    else:
        status = NOT_COMPARABLE
        reason = "one document says it does not apply, the other is silent"

    return Row(key=p.key, label=p.label, order=p.order, group=p.group, status=status,
               base_status=None, reason=reason, method=method, detail=detail,
               a=mk_side(ra, sa, norm_a), b=mk_side(rb, sb, norm_b),
               review_reasons=reasons, _pending=pending, _unreliable=unreliable)


# --------------------------------------------------------------------------- #
# LLM judge (one batched call per document pair)
# --------------------------------------------------------------------------- #
JUDGE_SYSTEM = """\
You compare the SAME property as stated in two different insurance annuity documents, \
A and B, to decide whether they say the same thing for a product comparison.

Verdicts:
- equivalent: same terms, amounts, periods, conditions and scope. Wording may differ.
- different: any difference in an amount, rate, period, condition, scope, or in an \
item that is included in one and not the other.
- uncertain: the two texts do not contain enough information to decide.

Be strict about numbers, conditions and scope. Be lenient about wording and word order. \
Use only the texts given. reason: one short sentence naming the difference, or why they \
are equivalent."""


def judge_batch(llm: LLM, items: list[dict]) -> dict[str, tuple[str, str]]:
    """items: [{key, label, meaning, a, b}] -> {key: (verdict, reason)}"""
    verdict_obj = _obj({
        "verdict": {"type": "string", "enum": ["equivalent", "different", "uncertain"]},
        "reason": {"type": "string"},
    })
    response_format = {"type": "json_schema", "json_schema": {
        "name": "judge_pairs", "strict": True,
        "schema": _obj({i["key"]: verdict_obj for i in items})}}

    lines = []
    for i in items:
        lines.append(f'<pair key="{i["key"]}" label="{i["label"]}">\n'
                     f'meaning: {i["meaning"]}\nA: {i["a"]}\nB: {i["b"]}\n</pair>')
    messages = [{"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user", "content": "Judge each pair.\n\n" + "\n".join(lines)}]

    try:
        data = json.loads(llm(messages, response_format))
    except Exception:
        data = {}
    out = {}
    for i in items:
        r = data.get(i["key"]) if isinstance(data, dict) else None
        if isinstance(r, dict) and r.get("verdict") in ("equivalent", "different", "uncertain"):
            out[i["key"]] = (r["verdict"], str(r.get("reason", "")))
        else:
            out[i["key"]] = ("uncertain", "judge returned no usable verdict")
    return out


# --------------------------------------------------------------------------- #
# Compare everything
# --------------------------------------------------------------------------- #
def compare_all(results_a: dict[str, PropertyResult],
                results_b: dict[str, PropertyResult],
                llm: Optional[LLM] = None) -> list[Row]:
    rows: list[Row] = []
    by_key = {p.key: p for p in PROPERTIES}
    for p in PROPERTIES:
        ra = results_a.get(p.key) or _missing_result(p.key)
        rb = results_b.get(p.key) or _missing_result(p.key)
        rows.append(compare_property(p, ra, rb))

    pending = [r for r in rows if r._pending]
    if pending and llm is not None:
        verdicts = judge_batch(llm, [
            {"key": r.key, "label": r.label, "meaning": by_key[r.key].description,
             "a": r._pending[0], "b": r._pending[1]} for r in pending])
        for r in pending:
            v, why = verdicts[r.key]
            r.status = {"equivalent": MATCH, "different": DIFFERENT,
                        "uncertain": NEEDS_REVIEW}[v]
            r.reason, r.method = why, "llm_judge"
    else:
        for r in pending:
            r.status, r.method = NEEDS_REVIEW, "judge_unavailable"
            r.reason = "texts differ in wording; LLM judge not run"

    for r in rows:                                   # finalize
        r.base_status = r.status
        if r._unreliable:
            r.status = NEEDS_REVIEW
        r.review = bool(r.review_reasons) or r.status == NEEDS_REVIEW
    return rows


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def summary(rows: list[Row]) -> dict:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1
    counts["total"] = len(rows)
    counts["flagged_for_review"] = sum(1 for r in rows if r.review)
    return counts


def _cell(s: Any, limit: int = 110) -> str:
    s = str(s).replace("|", "\\|").replace("\n", " ")
    return s if len(s) <= limit else s[: limit - 1] + "…"


def rows_to_markdown(rows: list[Row], name_a: str = "A", name_b: str = "B") -> str:
    out = [f"| # | Property | {name_a} | {name_b} | Status | Detail |",
           "|---|---|---|---|---|---|"]
    for r in rows:
        status = STATUS_LABEL[r.status] + (" ⚑" if r.review and r.status != NEEDS_REVIEW else "")
        detail = r.reason
        if r.review_reasons:
            detail += " | review: " + "; ".join(r.review_reasons)
        out.append(f"| {r.order} | {_cell(r.label)} | {_cell(r.a.display)} | "
                   f"{_cell(r.b.display)} | {status} | {_cell(detail, 160)} |")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Selftest (data modelled on the sample comparison table)
# --------------------------------------------------------------------------- #
def _R(key, state="found", raw=None, value=None, conf="high", flags=(), issues=()):
    return PropertyResult(key=key, state=state, raw_value=raw, value=value,
                          evidence=[{"quote": "x", "page": 1, "verified": True}]
                          if state != "not_found" else [],
                          confidence=conf, flags=set(flags), issues=list(issues))


def selftest() -> None:
    sched = lambda mva: {"years": 3, "schedule_pct": [8, 8, 7, 0], "mva": mva}
    chans = ["B/D: Full Service National", "B/D: Independent", "Bank", "Independent"]
    A = {r.key: r for r in [
        _R("product", raw="SecureFore™ 3 Fixed Annuity (SPDA)", value="SecureFore™ 3 Fixed Annuity (SPDA)"),
        _R("distribution_channels", raw="; ".join(chans), value=chans),
        _R("product_launch_date", raw="6/30/2014", value="2014-06-30"),
        _R("bonus", "not_applicable"),
        _R("surrender_charge", raw="3 Years 8,8,7,0", value=sched(None)),
        _R("other_charge", "not_found"),
        _R("state_approvals", raw="AK, AL, ... WY",
           value={"mode": "not_approved", "states": ["AK", "AL", "AR", "NY", "CA", "TX"]}),
        _R("street_level_compensation", raw="...", value=[
            {"category": None, "year": "YEAR ONE", "min_age": 0, "max_age": 80, "pct": 1.8},
            {"category": None, "year": "YEAR ONE", "min_age": 81, "max_age": 85, "pct": 0.9}]),
        _R("issue_ages", raw="Q/NQ 0-85; NQ Stretch 0-75", value=[
            {"category": "Q/NQ", "year": None, "min_age": 0, "max_age": 85, "pct": None},
            {"category": "NQ Stretch", "year": None, "min_age": 0, "max_age": 75, "pct": None}]),
        _R("death_benefit", raw="Full Account Value", value="Full Account Value"),
        _R("penalty_free_withdrawals", raw="10% of premiums paid immediately",
           value="10% of premiums paid immediately"),
        _R("surrender_charge_waivers", raw="Nursing Home; Terminal Illness",
           value=["Nursing Home", "Terminal Illness"]),
        _R("data_current_as_of", raw="10/12/2026", value="2026-10-12"),
        _R("current_fixed_rates", raw="5.45% / 5.65% for three years",
           value={"rates_pct": [5.45, 5.65], "guarantee_years": 3, "effective_date": None}),
        _R("upcoming_fixed_rates", raw="5.80%",
           value={"rates_pct": [5.8], "guarantee_years": None, "effective_date": None}),
        _R("glwb", "not_applicable"),
        _R("am_best_rating", raw="A", value="A"),
        _R("min_initial_premium", raw="Q/NQ $10,000", value=[{"category": "Q/NQ", "amount": 10000}]),
    ]}
    B = {r.key: r for r in [
        _R("product", raw="SecureFore II 3-Year (SPDA)", value="SecureFore II 3-Year (SPDA)"),
        _R("distribution_channels", raw="; ".join(reversed(chans)), value=list(reversed(chans))),
        _R("product_launch_date", raw="4/6/2026", value="2026-04-06"),
        _R("bonus", "not_applicable"),
        _R("surrender_charge", raw="3 Years 8,8,7,0 +/- MVA", value=sched("both")),
        _R("other_charge", "not_found"),
        _R("state_approvals", raw="CA, NY", value={"mode": "not_approved", "states": ["CA", "NY"]}),
        _R("street_level_compensation", raw="...", value=[
            {"category": None, "year": "YEAR ONE", "min_age": 0, "max_age": 80, "pct": 1.8},
            {"category": None, "year": "YEAR ONE", "min_age": 81, "max_age": None, "pct": 0.9}]),
        _R("issue_ages", raw="Q/NQ 0-85; NQ Stretch 0-75", value=[
            {"category": "NQ Stretch", "year": None, "min_age": 0, "max_age": 75, "pct": None},
            {"category": "Q/NQ", "year": None, "min_age": 0, "max_age": 85, "pct": None}]),
        _R("death_benefit", raw="full account value", value="full account value"),
        _R("penalty_free_withdrawals", raw="10% of premiums paid after year one",
           value="10% of premiums paid after year one"),
        _R("surrender_charge_waivers", raw="NH; TI; CI; ChI",
           value=["Nursing Home", "Terminal Illness", "Critical Illness", "Chronic Illness"]),
        _R("data_current_as_of", raw="10/12/2026", value="10/12/2026"),
        _R("current_fixed_rates", raw="5.45% / 5.65% for three years",
           value={"rates_pct": [5.45, 5.65], "guarantee_years": 3, "effective_date": None}),
        _R("upcoming_fixed_rates", "not_found"),
        _R("glwb", "not_found"),
        _R("am_best_rating", raw="A", value="A", flags={"quote_not_found"}, issues=["quote missing"]),
        _R("min_initial_premium", raw="$10,000 (Q/NQ)", value=[{"category": "q/nq", "amount": 10000.0}]),
    ]}

    judge_calls = []

    def fake_llm(messages, response_format):
        keys = list(response_format["json_schema"]["schema"]["properties"])
        judge_calls.append(keys)
        return json.dumps({k: {"verdict": "different", "reason": "timing differs"} for k in keys})

    rows = {r.key: r for r in compare_all(A, B, llm=fake_llm)}
    st = {k: r.status for k, r in rows.items()}

    assert st["product"] == DIFFERENT
    assert st["distribution_channels"] == MATCH                   # order-insensitive set
    assert st["product_launch_date"] == DIFFERENT
    assert st["bonus"] == BOTH_NA
    assert st["surrender_charge"] == DIFFERENT and "mva" in rows["surrender_charge"].reason
    assert st["other_charge"] == NOT_FOUND_BOTH
    assert st["state_approvals"] == DIFFERENT
    assert rows["state_approvals"].detail["only_in_a"] == ["AK", "AL", "AR", "TX"]
    assert st["street_level_compensation"] == DIFFERENT and "max_age" in rows["street_level_compensation"].reason
    assert st["issue_ages"] == MATCH                              # band order irrelevant
    assert st["death_benefit"] == MATCH                           # case-insensitive, no LLM
    assert st["penalty_free_withdrawals"] == DIFFERENT and rows["penalty_free_withdrawals"].method == "llm_judge"
    assert judge_calls == [["penalty_free_withdrawals"]], judge_calls   # only unresolved text hits the LLM
    assert st["surrender_charge_waivers"] == DIFFERENT
    assert st["data_current_as_of"] == MATCH                      # '10/12/2026' == ISO
    assert st["current_fixed_rates"] == MATCH
    assert st["upcoming_fixed_rates"] == MISSING_B
    assert st["glwb"] == NOT_COMPARABLE
    assert st["am_best_rating"] == NEEDS_REVIEW and rows["am_best_rating"].base_status == MATCH
    assert st["min_initial_premium"] == MATCH
    assert st["company"] == NEEDS_REVIEW and rows["company"].base_status == NOT_FOUND_BOTH  # key missing from both dicts
    json.dumps([r.to_dict() for r in rows.values()])              # serializable
    print("selftest OK:", summary(list(rows.values())))


if __name__ == "__main__":
    selftest()
