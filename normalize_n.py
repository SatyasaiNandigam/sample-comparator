"""
Normalization step for N documents (v0.1). Runs after extract_n, before compare_n.

    from normalize_n import normalize_results

    results = extract_n(llm, docs)                 # {doc_id: {key: PropertyResult}}
    normalized = normalize_results(results)        # {doc_id: {key: NormalizedValue}}

Reuses normalizers.normalize() for the type-specific canonical form, and jsonable() so the
output is JSON-serializable. Only found values are normalized; not_applicable and
not_found are passed through with normalized=None.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from group_prompts import PropertyResult
from normalizers import jsonable, normalize
from policy_schema import BY_KEY


@dataclass
class NormalizedValue:
    key: str
    state: str                      # found | not_applicable | not_found
    normalized: Any                 # canonical comparable form (JSON-able), None if not found
    compare_key: Optional[str]      # canonical JSON string; equal strings == equal values
    error: Optional[str] = None     # set if the value could not be normalized

    def to_dict(self) -> dict:
        return {"key": self.key, "state": self.state, "normalized": self.normalized,
                "compare_key": self.compare_key, "error": self.error}


def normalize_one(key: str, result: PropertyResult) -> NormalizedValue:
    state = result.state or "not_found"
    if state != "found":
        return NormalizedValue(key, state, None, None)
    try:
        norm = jsonable(normalize(BY_KEY[key].type, result.value))
    except Exception as e:                              # malformed typed value
        return NormalizedValue(key, state, None, None, error=f"{type(e).__name__}: {e}")
    compare_key = json.dumps(norm, sort_keys=True, ensure_ascii=False)
    return NormalizedValue(key, state, norm, compare_key)


def normalize_results(results: dict[str, dict[str, PropertyResult]]
                      ) -> dict[str, dict[str, NormalizedValue]]:
    """{doc_id: {key: PropertyResult}} -> {doc_id: {key: NormalizedValue}}, same keys."""
    return {doc_id: {key: normalize_one(key, res) for key, res in props.items()}
            for doc_id, props in results.items()}


# --------------------------------------------------------------------------- #
# Selftest
# --------------------------------------------------------------------------- #
def selftest() -> None:
    def R(state="found", value=None, raw=None):
        return PropertyResult(key="x", state=state, value=value, raw_value=raw,
                              evidence=[], confidence="high")

    results = {
        "gen": {
            "product_launch_date": R(value="2014-06-30"),
            "distribution_channels": R(value=["Bank", "Independent"]),
            "bonus": R("not_applicable"),
            "surrender_charge": R(value={"years": 3, "schedule_pct": [8, 8, 7, 0], "mva": None}),
        },
        "v1": {
            "product_launch_date": R(value="6/30/2014"),          # same date, different text
            "distribution_channels": R(value=["independent", "Bank"]),
            "bonus": R("not_found"),
            "surrender_charge": R(value="garbage"),                # cannot be normalized
        },
    }
    n = normalize_results(results)

    assert set(n) == {"gen", "v1"} and set(n["gen"]) == set(results["gen"])
    assert n["gen"]["product_launch_date"].normalized == "2014-06-30"
    assert n["v1"]["product_launch_date"].normalized == "2014-06-30"
    assert n["gen"]["product_launch_date"].compare_key == n["v1"]["product_launch_date"].compare_key
    assert n["gen"]["distribution_channels"].compare_key == n["v1"]["distribution_channels"].compare_key
    assert n["gen"]["surrender_charge"].normalized["schedule_pct"] == [8.0, 8.0, 7.0]
    assert n["gen"]["bonus"].state == "not_applicable" and n["gen"]["bonus"].normalized is None
    assert n["v1"]["bonus"].state == "not_found" and n["v1"]["bonus"].compare_key is None
    assert n["v1"]["surrender_charge"].error and n["v1"]["surrender_charge"].normalized is None
    json.dumps({d: {k: v.to_dict() for k, v in props.items()} for d, props in n.items()})
    print("normalize_n selftest OK")


if __name__ == "__main__":
    selftest()
