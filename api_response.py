"""
API response builder (v1.0): comparison.json -> slim, N-document-ready JSON for the UI.

    from api_response import to_api_response, validate_response

    resp = to_api_response(comparison)            # comparison = report dict / comparison.json
    validate_response(resp)                       # raises ValueError if the contract is broken

Response shape
--------------
{
  "format_version": "1.0",
  "meta": {
    "schema_version": "0.1", "prompt_version": "0.1",
    "documents": [ {"document_id": "doc_1", "label": "Generated", "pages": 13}, ... ]
  },
  "summary": {"total": 38, "flagged_for_review": 4,
              "by_status": {"match": 20, "different": 9, "missing": 2, ...}},
  "properties": [
    {
      "key": "company", "label": "Company", "order": 1, "group": "product_info",
      "status": "different",
      "documents": [      # same length and order as meta.documents
        {"document_id": "doc_1", "label": "Generated", "display": "...",
         "value": ..., "normalized": ...},
        ...
      ]
    }
  ]
}

Nothing in the contract depends on there being exactly two documents:
  * documents are an ordered array, identified by document_id (never "a"/"b"),
  * statuses are property-level and not tied to a document position
    (missing_in_a / missing_in_b become "missing"; both_na -> "all_na";
     not_found_both -> "all_not_found"),
  * the input may be the current pairwise format (row.a / row.b, meta.doc_a / meta.doc_b)
    or a future one (row.documents[], meta.documents[]).

CLI:
    python api_response.py comparison.json out.json     # convert
    python api_response.py --schema api_response.schema.json
    python api_response.py --selftest
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any, Optional

FORMAT_VERSION = "1.0"

# comparison.json status -> API status (position-independent names)
STATUS_MAP = {
    "match": "match",
    "different": "different",
    "both_na": "all_na",
    "not_found_both": "all_not_found",
    "not_comparable": "not_comparable",
    "needs_review": "needs_review",
}
API_STATUSES = ["match", "different", "missing", "all_na", "all_not_found",
                "not_comparable", "needs_review"]

_LEGACY_META_KEYS = {"doc_a", "doc_b", "pages_a", "pages_b", "documents"}


def map_status(status: str) -> str:
    if status in STATUS_MAP:
        return STATUS_MAP[status]
    if re.fullmatch(r"missing_in_\w+", status or ""):    # missing_in_a, _b, _c ...
        return "missing"
    return status


# --------------------------------------------------------------------------- #
# Input adapters (current pairwise format and future N-document format)
# --------------------------------------------------------------------------- #
def _documents(meta: dict, document_ids: Optional[list[str]]) -> list[dict]:
    if isinstance(meta.get("documents"), list):
        raw = [{"label": d.get("label") or d.get("name") or d.get("document"),
                "pages": d.get("pages"), "document_id": d.get("document_id")}
               for d in meta["documents"]]
    else:
        raw = [{"label": meta.get("doc_a"), "pages": meta.get("pages_a"), "document_id": None},
               {"label": meta.get("doc_b"), "pages": meta.get("pages_b"), "document_id": None}]

    if document_ids is not None and len(document_ids) != len(raw):
        raise ValueError(f"document_ids has {len(document_ids)} items, expected {len(raw)}")
    docs = []
    for i, d in enumerate(raw):
        doc_id = (document_ids[i] if document_ids else None) or d["document_id"] or f"doc_{i + 1}"
        docs.append({"document_id": doc_id, "label": d["label"] or doc_id, "pages": d["pages"]})
    return docs


def _sides(row: dict) -> list[dict]:
    if isinstance(row.get("documents"), list):
        return row["documents"]
    return [row["a"], row["b"]]


# --------------------------------------------------------------------------- #
# Builder
# --------------------------------------------------------------------------- #
def to_api_response(comparison: dict, document_ids: Optional[list[str]] = None) -> dict:
    meta_in = comparison.get("meta") or {}
    docs = _documents(meta_in, document_ids)

    meta = {k: v for k, v in meta_in.items() if k not in _LEGACY_META_KEYS}
    meta["documents"] = docs

    props = []
    for row in sorted(comparison["rows"], key=lambda r: r["order"]):
        sides = _sides(row)
        if len(sides) != len(docs):
            raise ValueError(f"{row['key']}: {len(sides)} document values for {len(docs)} documents")
        props.append({
            "key": row["key"],
            "label": row["label"],
            "order": row["order"],
            "group": row["group"],
            "status": map_status(row["status"]),
            "documents": [
                {"document_id": d["document_id"], "label": d["label"],
                 "display": s.get("display"), "value": s.get("value"),
                 "normalized": s.get("normalized")}
                for d, s in zip(docs, sides)],
        })

    summary_in = comparison.get("summary") or {}
    by_status = {s: 0 for s in API_STATUSES}
    for k, v in summary_in.items():
        if k in ("total", "flagged_for_review"):
            continue
        s = map_status(k)
        by_status[s] = by_status.get(s, 0) + v
    summary = {"total": summary_in.get("total", len(props)),
               "flagged_for_review": summary_in.get("flagged_for_review", 0),
               "by_status": by_status}

    return {"format_version": FORMAT_VERSION, "meta": meta,
            "summary": summary, "properties": props}


# --------------------------------------------------------------------------- #
# JSON Schema (draft 2020-12) for the UI / API contract
# --------------------------------------------------------------------------- #
def build_json_schema() -> dict:
    document_meta = {
        "type": "object",
        "required": ["document_id", "label", "pages"],
        "additionalProperties": False,
        "properties": {"document_id": {"type": "string", "minLength": 1},
                       "label": {"type": "string"},
                       "pages": {"type": ["integer", "null"]}},
    }
    document_value = {
        "type": "object",
        "required": ["document_id", "label", "display", "value", "normalized"],
        "additionalProperties": False,
        "properties": {
            "document_id": {"type": "string", "minLength": 1},
            "label": {"type": "string"},
            "display": {"type": ["string", "null"]},
            "value": {},          # any JSON: string, number, array, object or null
            "normalized": {},     # any JSON, canonical comparison form
        },
    }
    prop = {
        "type": "object",
        "required": ["key", "label", "order", "group", "status", "documents"],
        "additionalProperties": False,
        "properties": {
            "key": {"type": "string"},
            "label": {"type": "string"},
            "order": {"type": "integer", "minimum": 1},
            "group": {"type": "string"},
            "status": {"enum": API_STATUSES},
            "documents": {"type": "array", "minItems": 2, "items": document_value},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "PolicyComparisonResponse",
        "type": "object",
        "required": ["format_version", "meta", "summary", "properties"],
        "additionalProperties": False,
        "properties": {
            "format_version": {"const": FORMAT_VERSION},
            "meta": {
                "type": "object",
                "required": ["documents"],
                "additionalProperties": True,        # schema_version, prompt_version, ...
                "properties": {"documents": {"type": "array", "minItems": 2,
                                             "items": document_meta}},
            },
            "summary": {
                "type": "object",
                "required": ["total", "flagged_for_review", "by_status"],
                "additionalProperties": False,
                "properties": {
                    "total": {"type": "integer", "minimum": 0},
                    "flagged_for_review": {"type": "integer", "minimum": 0},
                    "by_status": {
                        "type": "object",
                        "required": API_STATUSES,
                        "additionalProperties": False,
                        "properties": {s: {"type": "integer", "minimum": 0}
                                       for s in API_STATUSES},
                    },
                },
            },
            "properties": {"type": "array", "items": prop},
        },
    }


def validate_response(resp: dict) -> None:
    """Contract check. Uses `jsonschema` if installed, plus consistency rules it cannot express."""
    try:
        import jsonschema
        jsonschema.validate(resp, build_json_schema())
    except ImportError:
        pass
    except Exception as e:                                    # jsonschema.ValidationError
        raise ValueError(f"schema violation: {getattr(e, 'message', e)}") from e

    ids = [d["document_id"] for d in resp["meta"]["documents"]]
    if len(set(ids)) != len(ids):
        raise ValueError("document_id values must be unique")
    keys = [p["key"] for p in resp["properties"]]
    if len(set(keys)) != len(keys):
        raise ValueError("property keys must be unique")
    for p in resp["properties"]:
        if [d["document_id"] for d in p["documents"]] != ids:
            raise ValueError(f"{p['key']}: documents must match meta.documents in id and order")
    if sum(resp["summary"]["by_status"].values()) != len(resp["properties"]):
        raise ValueError("summary.by_status does not add up to the number of properties")


# --------------------------------------------------------------------------- #
# Selftest / CLI
# --------------------------------------------------------------------------- #
def selftest() -> None:
    from comparator import compare_all, summary
    from group_prompts import PropertyResult

    def R(key, state="found", raw=None, value=None):
        return PropertyResult(key=key, state=state, raw_value=raw, value=value,
                              evidence=[{"quote": "x", "page": 1, "verified": True}]
                              if state != "not_found" else [], confidence="high")

    A = {r.key: r for r in [
        R("company", raw="Forethought Life", value="Forethought Life"),
        R("bonus", "not_applicable"),
        R("upcoming_fixed_rates", raw="5.80%",
          value={"rates_pct": [5.8], "guarantee_years": None, "effective_date": None}),
        R("product_launch_date", raw="6/30/2014", value="2014-06-30")]}
    B = {r.key: r for r in [
        R("company", raw="Forethought Life", value="Forethought Life"),
        R("bonus", "not_applicable"),
        R("upcoming_fixed_rates", "not_found"),
        R("product_launch_date", raw="4/6/2026", value="2026-04-06")]}
    rows = compare_all(A, B, llm=None)
    comparison = {"meta": {"schema_version": "0.1", "prompt_version": "0.1",
                           "doc_a": "Generated", "doc_b": "Third party",
                           "pages_a": 13, "pages_b": 11},
                  "summary": summary(rows), "rows": [r.to_dict() for r in rows]}
    comparison = json.loads(json.dumps(comparison))      # as read back from comparison.json

    resp = to_api_response(comparison)
    validate_response(resp)
    json.dumps(resp)

    p = {x["key"]: x for x in resp["properties"]}
    assert resp["meta"]["documents"][0] == {"document_id": "doc_1", "label": "Generated", "pages": 13}
    assert resp["meta"]["schema_version"] == "0.1" and "doc_a" not in resp["meta"]
    assert p["company"]["status"] == "match"
    assert p["bonus"]["status"] == "all_na"
    assert p["upcoming_fixed_rates"]["status"] == "missing"      # was missing_in_b
    assert p["product_launch_date"]["status"] == "different"
    d0, d1 = p["product_launch_date"]["documents"]
    assert d0["document_id"] == "doc_1" and d1["display"] == "4/6/2026" and d1["value"] == "2026-04-06"
    assert set(d0) == {"document_id", "label", "display", "value", "normalized"}
    assert set(p["company"]) == {"key", "label", "order", "group", "status", "documents"}
    assert [x["order"] for x in resp["properties"]] == sorted(x["order"] for x in resp["properties"])
    assert resp["summary"]["by_status"]["missing"] == 1 and resp["summary"]["total"] == 38
    assert resp["properties"][0]["documents"][0]["display"] is not None

    # custom ids
    resp2 = to_api_response(comparison, document_ids=["generated", "vendor"])
    validate_response(resp2)
    assert [d["document_id"] for d in resp2["meta"]["documents"]] == ["generated", "vendor"]

    # forward compatibility: three documents, future input format
    future = {"meta": {"schema_version": "0.1", "documents": [
                  {"label": "A", "pages": 1}, {"label": "B", "pages": 2}, {"label": "C", "pages": 3}]},
              "summary": {"match": 0, "different": 1, "missing_in_c": 0, "total": 1, "flagged_for_review": 0},
              "rows": [{"key": "company", "label": "Company", "order": 1, "group": "product_info",
                        "status": "different",
                        "documents": [{"display": "x", "value": "x", "normalized": "x"},
                                      {"display": "y", "value": "y", "normalized": "y"},
                                      {"display": "Not found", "value": None, "normalized": None}]}]}
    resp3 = to_api_response(future)
    resp3["summary"]["by_status"]["different"] = 1
    validate_response(resp3)
    assert [d["document_id"] for d in resp3["properties"][0]["documents"]] == ["doc_1", "doc_2", "doc_3"]

    # broken contract is caught
    bad = json.loads(json.dumps(resp))
    bad["properties"][0]["documents"].reverse()
    try:
        validate_response(bad)
        raise AssertionError("order violation not caught")
    except ValueError:
        pass
    print("api_response selftest OK (jsonschema",
          "used)" if _has_jsonschema() else "not installed: consistency checks only)")


def _has_jsonschema() -> bool:
    try:
        import jsonschema  # noqa: F401
        return True
    except ImportError:
        return False


def _main(argv: list[str]) -> None:
    if argv and argv[0] == "--selftest":
        selftest()
    elif argv and argv[0] == "--schema":
        path = argv[1] if len(argv) > 1 else "api_response.schema.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(build_json_schema(), f, indent=2)
        print("wrote", path)
    elif len(argv) >= 2:
        with open(argv[0], encoding="utf-8") as f:
            comparison = json.load(f)
        resp = to_api_response(comparison)
        validate_response(resp)
        with open(argv[1], "w", encoding="utf-8") as f:
            json.dump(resp, f, indent=2, ensure_ascii=False)
        print(f"wrote {argv[1]}: {resp['summary']['total']} properties, "
              f"{len(resp['meta']['documents'])} documents")
    else:
        print(__doc__)


if __name__ == "__main__":
    _main(sys.argv[1:])
