"""
Normalizers (v0.1): typed extraction value -> canonical, comparable form.

Input is the `value` produced under group_prompts.VALUE_SHAPES; output is plain Python
(str, float, tuple, frozenset, dict) so comparators never parse text.

    normalize("state_set", {"mode": "approved", "states": ["TX", "FL"]})
    -> frozenset of NOT-approved codes over the 50 states + DC

Decisions baked in (change here, nowhere else):
  * state_set is always converted to the NOT-approved set.
  * surrender schedules ignore a trailing 0% year ("8,8,7,0" == "8,8,7").
  * mva=None ("not mentioned") stays distinct from "none" ("stated not to apply").
  * currency ignores `basis` (it is shown in the UI, not compared).
  * list items are canonicalized through TERM_SYNONYMS. Extend it from real outputs.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Callable, Optional


# --------------------------------------------------------------------------- #
# Text
# --------------------------------------------------------------------------- #
_SYMBOLS = re.compile(r"[\u2122\u00ae\u00a9]")  # TM, R, C


def norm_text(s: Any) -> Optional[str]:
    """Casefold, drop trademark symbols, unify dashes/ampersands/spacing.
    Keeps + - / % $ so 'A+' != 'A' and '0-85' stays readable."""
    if s is None:
        return None
    s = str(s).casefold()
    s = _SYMBOLS.sub("", s)
    s = s.replace("&", " and ")
    for a, b in (("\u2013", "-"), ("\u2014", "-"), ("\u2019", "'"), ("\u00a0", " ")):
        s = s.replace(a, b)
    s = re.sub(r"\s*([/\-])\s*", r"\1", s)     # 'q / nq' -> 'q/nq', '0 - 85' -> '0-85'
    s = re.sub(r"\s+", " ", s).strip(" .,;:")
    return s


# Whole-item synonyms, applied after norm_text. Starter set: extend from real outputs.
TERM_SYNONYMS = {
    "non-qualified": "nq",
    "nonqualified": "nq",
    "non qualified": "nq",
    "non-qualified (nq)": "nq",
    "qualified": "q",
    "traditional ira": "ira",
    "inherited non-qualified": "inherited nq",
    "inherited nonqualified": "inherited nq",
    "nursing home confinement": "nursing home",
    "confinement to a nursing home": "nursing home",
    "terminal": "terminal illness",
    "terminally ill": "terminal illness",
}


def canon_item(s: Any) -> Optional[str]:
    n = norm_text(s)
    if n is None:
        return None
    return TERM_SYNONYMS.get(n, n)


# --------------------------------------------------------------------------- #
# Numbers and dates
# --------------------------------------------------------------------------- #
def _num(x: Any) -> Optional[float]:
    if x is None:
        return None
    return round(float(x), 6)


_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y",
                 "%B %d %Y", "%d %B %Y", "%Y/%m/%d")


def norm_date(v: Any) -> Optional[str]:
    """ISO yyyy-mm-dd. Ambiguous numeric dates are read as US month/day/year."""
    if v is None:
        return None
    s = str(v).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return norm_text(s)     # unparseable: fall back to text so it still compares


# --------------------------------------------------------------------------- #
# States
# --------------------------------------------------------------------------- #
STATE_NAMES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI",
    "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
    "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY",
}
ALL_STATES = frozenset(STATE_NAMES.values())          # 50 states + DC
_NAME_TO_CODE = {norm_text(k): v for k, v in STATE_NAMES.items()}


def to_state_code(s: Any) -> Optional[str]:
    t = str(s).strip().strip(".").strip()
    if not t:
        return None
    if t.upper() in ALL_STATES:
        return t.upper()
    n = norm_text(t)
    if n in _NAME_TO_CODE:
        return _NAME_TO_CODE[n]
    return t.upper() if re.fullmatch(r"[A-Za-z]{2}", t) else None   # e.g. PR, GU


def norm_state_set(v: dict) -> frozenset:
    """Always return the NOT-approved set so both documents compare on one basis."""
    codes = {c for c in (to_state_code(s) for s in v.get("states") or []) if c}
    if v.get("mode") == "approved":
        return frozenset(ALL_STATES - codes)
    return frozenset(codes)


# --------------------------------------------------------------------------- #
# Structured types
# --------------------------------------------------------------------------- #
def norm_list_text(v: list) -> frozenset:
    return frozenset(c for c in (canon_item(x) for x in v or []) if c)


def norm_currency(v: dict) -> dict:
    return {"amount": _num(v.get("amount"))}


def norm_currency_by_category(v: list) -> dict:
    out: dict[str, Optional[float]] = {}
    for item in v or []:
        cat = canon_item(item.get("category")) or "all"
        out[cat] = _num(item.get("amount"))
    return out


def norm_schedule(v: dict) -> dict:
    pct = [float(x) for x in v.get("schedule_pct") or []]
    while pct and pct[-1] == 0:          # trailing 0% year only marks the end of the period
        pct.pop()
    years = v.get("years")
    if years is None and pct:
        years = len(pct)
    return {"years": years,
            "schedule_pct": tuple(round(x, 4) for x in pct),
            "mva": v.get("mva")}


def norm_age_bands(v: list) -> dict:
    """Keyed by category|year|min_age so bands align across documents."""
    out: dict[str, dict] = {}
    for b in v or []:
        cat = canon_item(b.get("category")) if b.get("category") else "-"
        yr = norm_text(b.get("year")) if b.get("year") else "-"
        lo = b.get("min_age")
        key = f"{cat}|{yr}|{lo if lo is not None else '-'}"
        n = 2
        while key in out:                # duplicate band keys: keep both
            key = f"{key}#{n}"
            n += 1
        out[key] = {"min_age": lo, "max_age": b.get("max_age"), "pct": _num(b.get("pct"))}
    return out


def norm_rate_by_term(v: dict) -> dict:
    return {"rates_pct": tuple(round(float(x), 4) for x in v.get("rates_pct") or []),
            "guarantee_years": v.get("guarantee_years"),
            "effective_date": norm_date(v.get("effective_date"))}


def norm_count_pair(v: dict) -> dict:
    return {"indexed": v.get("indexed"), "fixed": v.get("fixed")}


def norm_pct_formula(v: dict) -> dict:
    return {"varies": bool(v.get("varies")),
            "pct_of_premium": _num(v.get("pct_of_premium")),
            "rate_min": _num(v.get("rate_min")),
            "rate_max": _num(v.get("rate_max"))}


def norm_rate_band(v: dict) -> dict:
    return {"band": norm_text(v.get("band")), "threshold": _num(v.get("threshold"))}


NORMALIZERS: dict[str, Callable[[Any], Any]] = {
    "text": norm_text,
    "enum_text": norm_text,
    "date": norm_date,
    "list_text": norm_list_text,
    "currency": norm_currency,
    "currency_by_category": norm_currency_by_category,
    "schedule": norm_schedule,
    "age_bands": norm_age_bands,
    "state_set": norm_state_set,
    "rate_by_term": norm_rate_by_term,
    "count_pair": norm_count_pair,
    "pct_formula": norm_pct_formula,
    "rate_band": norm_rate_band,
}


def normalize(type_: str, value: Any) -> Any:
    """Normalize one extracted value. Raises on malformed input; callers flag it."""
    if value is None:
        return None
    return NORMALIZERS[type_](value)


def jsonable(x: Any) -> Any:
    """Make normalized values JSON-serializable (frozenset/tuple -> sorted list/list)."""
    if isinstance(x, (set, frozenset)):
        return sorted(x, key=str)
    if isinstance(x, tuple):
        return [jsonable(i) for i in x]
    if isinstance(x, list):
        return [jsonable(i) for i in x]
    if isinstance(x, dict):
        return {k: jsonable(v) for k, v in x.items()}
    return x
