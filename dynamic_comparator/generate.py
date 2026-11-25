"""
Generate the property list for a product type with an LLM.

    python -m dynamic_comparator.generate --print --category annuity --type fixed
    python -m dynamic_comparator.generate --category annuity --type fixed
    python -m dynamic_comparator.generate --category annuity --type fixed --validate
    python -m dynamic_comparator.generate --all
    python -m dynamic_comparator.generate --selftest
    python -m dynamic_comparator.generate --summarize --all   # rebuild summary/, no LLM call

Every generated list is also saved in short form (key, label, order, group only) to
summary/<category>/<type>.json, for sharing.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Callable

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from pydantic import ValidationError

from .catalog import CATEGORIES, DYNAMIC_GROUPS
from .prompt_builder import build_prompt, render_prompt_text, save_prompt
from .schema import (PropertyListResponse, normalize_order, response_format,
                     validate_property_list)

GENERATED_DIR = pathlib.Path(__file__).parent / "generated"
SUMMARY_DIR = pathlib.Path(__file__).parent / "summary"

LLM = Callable[[list, dict], str]


def generate_properties(llm: LLM, category: str, product_type: str,
                        max_retries: int = 1, save: bool = True,
                        validate: bool = False) -> PropertyListResponse:
    """Call the LLM and save the result as returned (one call, no checks).

    With validate=True: also run the rule checks, retry with feedback on failure, and
    sort by group/order and renumber before saving.
    """
    feedback: list[str] | None = None
    errors: list[str] = []
    if not validate:
        max_retries = 0
    print(f"[{category}/{product_type}] starting generation "
          f"(validation {'on' if validate else 'off'})", flush=True)
    for attempt in range(max_retries + 1):
        print(f"[{category}/{product_type}] attempt {attempt + 1}/{max_retries + 1}: "
              "calling LLM (this can take a minute)...", flush=True)
        raw = llm(build_prompt(category, product_type, feedback), response_format())
        print(f"[{category}/{product_type}] response received ({len(raw)} chars)", flush=True)
        print(f"----- RAW RESPONSE ({category}/{product_type}, attempt {attempt + 1}) -----\n"
              f"{raw}\n----- END RAW RESPONSE -----", flush=True)
        if save:
            debug = GENERATED_DIR / "_raw" / category / f"{product_type}_attempt{attempt + 1}.json"
            debug.parent.mkdir(parents=True, exist_ok=True)
            debug.write_text(raw, encoding="utf-8")
            print(f"[{category}/{product_type}] raw response saved to {debug}", flush=True)
        try:
            resp = PropertyListResponse.model_validate_json(raw)
        except (ValidationError, ValueError) as exc:
            errors = [f"response did not match the schema: {str(exc)[:500]}"]
            print(f"[{category}/{product_type}] schema error, will retry:\n{errors[0]}",
                  flush=True)
            feedback = errors
            continue
        errors = validate_property_list(resp, DYNAMIC_GROUPS) if validate else []
        if not errors:
            if validate:
                normalize_order(resp, DYNAMIC_GROUPS)
            if save:
                path = save_result(category, product_type, resp)
                print(f"[{category}/{product_type}] saved {len(resp.properties)} properties "
                      f"to {path}", flush=True)
                print(f"[{category}/{product_type}] summary saved to "
                      f"{save_summary(category, product_type, resp)}", flush=True)
            return resp
        print(f"[{category}/{product_type}] {len(errors)} validation error(s), will retry:",
              flush=True)
        for e in errors:
            print(f"  - {e}", flush=True)
        feedback = errors
    raise ValueError(f"{category}/{product_type}: invalid after retries: {errors}")


def save_result(category: str, product_type: str, resp: PropertyListResponse) -> pathlib.Path:
    path = GENERATED_DIR / category / f"{product_type}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(resp.model_dump(by_alias=True), indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return path


def save_summary(category: str, product_type: str, resp: PropertyListResponse) -> pathlib.Path:
    """Short form (key, label, order, group only) for sharing, in summary/<category>/."""
    path = SUMMARY_DIR / category / f"{product_type}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    short = {"properties": [{"key": p.key, "label": p.label, "order": p.order, "group": p.group}
                            for p in sorted(resp.properties, key=lambda p: p.order)]}
    path.write_text(json.dumps(short, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_result(category: str, product_type: str) -> PropertyListResponse:
    path = GENERATED_DIR / category / f"{product_type}.json"
    return PropertyListResponse.model_validate_json(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
def _check_strict(schema, path="root"):
    """Strict structured output: every object lists all props as required, no extras."""
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            assert schema.get("additionalProperties") is False, f"{path}: additionalProperties"
            assert set(schema["required"]) == set(schema["properties"]), f"{path}: required"
        for k, v in schema.items():
            _check_strict(v, f"{path}.{k}")
    elif isinstance(schema, list):
        for i, v in enumerate(schema):
            _check_strict(v, f"{path}[{i}]")


def _prop(key, order, group="product_info", type_="text", compare="judge", not_=()):
    return {"key": key, "label": key.title(), "order": order, "group": group, "type": type_,
            "description": f"desc {key}", "compare": compare, "aliases": ["a"],
            "not_": list(not_), "format_hint": None, "na_means": None, "notes": None}


def selftest() -> None:
    _check_strict(response_format()["json_schema"]["schema"])

    # every (category, type) prompt builds
    for cat, types in CATEGORIES.items():
        for t in types:
            build_prompt(cat, t)

    good = {"properties": [_prop("a", 1), _prop("b", 2, "benefits", not_=["a"])]}
    calls: list[list] = []

    def fake_llm(messages, rf):
        calls.append(messages)
        if len(calls) == 1:  # bad: unknown group/type, dangling not_, order gap
            bad = {"properties": [_prop("a", 1, group="nope"), _prop("b", 3, type_="zzz", not_=["ghost"])]}
            return json.dumps(bad)
        return json.dumps(good)

    resp = generate_properties(fake_llm, "annuity", "fixed", save=False, validate=True)
    assert len(calls) == 2 and "<corrections>" in calls[1][1]["content"]
    assert [p.key for p in resp.properties] == ["a", "b"]
    assert resp.properties[1].to_legacy().not_ == ("a",)

    try:
        generate_properties(lambda m, r: "not json", "life", "term", save=False)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid output must raise")
    print(f"selftest OK: strict schema, {sum(len(t) for t in CATEGORIES.values())} prompts build, "
          "validation + retry verified")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--category", choices=list(CATEGORIES))
    ap.add_argument("--type", dest="ptype")
    ap.add_argument("--all", action="store_true", help="generate every product type")
    ap.add_argument("--print", dest="show", action="store_true", help="print prompt, no LLM call")
    ap.add_argument("--save-prompts", action="store_true", help="write prompts/ files, no LLM call")
    ap.add_argument("--validate", action="store_true",
                    help="run rule checks (retry on failure) and normalize order; default: off")
    ap.add_argument("--summarize", action="store_true",
                    help="build summary/ files from existing generated/ JSON, no LLM call")
    ap.add_argument("--model")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    targets = ([(c, t) for c, ts in CATEGORIES.items() for t in ts] if a.all
               else [(a.category, a.ptype)])
    if not a.all and not (a.category and a.ptype):
        ap.error("give --category and --type, or --all")

    if a.summarize:
        for c, t in targets:
            if (GENERATED_DIR / c / f"{t}.json").exists():
                print("wrote", save_summary(c, t, load_result(c, t)))
            else:
                print(f"skipped {c}/{t}: not generated yet")
        return
    if a.show:
        for c, t in targets:
            print(render_prompt_text(build_prompt(c, t)))
        return
    if a.save_prompts:
        for c, t in targets:
            print("wrote", save_prompt(c, t))
        return

    from .llm import call_llm
    llm = (lambda m, r: call_llm(m, r, a.model))
    print(f"Generating {len(targets)} product type(s)...", flush=True)
    for i, (c, t) in enumerate(targets, 1):
        print(f"--- {i}/{len(targets)}: {c}/{t} ---", flush=True)
        print("prompt saved:", save_prompt(c, t), flush=True)
        resp = generate_properties(llm, c, t, validate=a.validate)
        print(f"{c}/{t}: {len(resp.properties)} properties -> {GENERATED_DIR / c / (t + '.json')}")


if __name__ == "__main__":
    main()
