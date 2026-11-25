"""
Builds the property-generation prompt for one (category, product_type).

Layers: static system prompt -> category/type block from the catalog -> few-shot
exemplars taken from the hardcoded annuity registry (policy_schema.py).
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import policy_schema
from group_prompts import VALUE_SHAPES

from .catalog import (CATEGORIES, CATEGORY_NAMES, DYNAMIC_GROUPS, PROVISION_ROWS,
                      ROW_TO_GROUP, TYPE_EMPHASIS)

PROMPTS_DIR = pathlib.Path(__file__).parent / "prompts"

FEWSHOT_KEYS = ["company", "surrender_charge", "other_charge", "penalty_free_withdrawals",
                "min_initial_premium", "state_approvals"]


def _compare_for(type_: str) -> str:
    """Default type -> compare pairing used in policy_schema (judge for free text)."""
    return {
        "enum_text": "exact", "date": "exact", "list_text": "set", "currency": "numeric",
        "currency_by_category": "by_key", "schedule": "schedule", "age_bands": "bands",
        "state_set": "set", "rate_by_term": "numeric", "count_pair": "exact",
        "pct_formula": "exact", "rate_band": "exact", "text": "judge",
    }[type_]


def _system_prompt() -> str:
    type_lines = "\n".join(f"  - {t}: {VALUE_SHAPES[t][1]}" for t in sorted(policy_schema.TYPES))
    pairing = "\n".join(f"  - {t} -> {_compare_for(t)}" for t in sorted(policy_schema.TYPES))
    compare_lines = "\n".join(f"  - {c}" for c in sorted(policy_schema.COMPARE))
    group_lines = "\n".join(f"  - {g}" for g in DYNAMIC_GROUPS)
    return f"""\
You design the property schema used to extract and compare insurance product \
specification documents. Given an insurance category and a product type, you return \
the list of properties that a specification document for that product type would \
state and that are worth comparing side by side across carriers.

Each property has these fields:
- key: unique snake_case identifier.
- label: human-readable name as it would appear in a side-by-side comparison.
- order: unique integer used only for sorting. Prefer keeping properties of the same \
group together, following the group order below.
- group: one of the allowed groups.
- type: one of the allowed types (it drives the normalizer and the output shape).
- description: one or two sentences stating exactly what to extract. Specific, \
unambiguous, self-contained.
- compare: one of the allowed compare modes.
- aliases: other names the document may use for it (3-6 short strings, never empty \
unless there truly are none).
- not_: keys of sibling properties this one must NOT capture. Use it wherever two \
properties could be confused (for example a base benefit vs a rider, current vs \
upcoming value, or a catch-all "Other" property vs the specific ones). Every entry \
must be the key of another property in your list.
- format_hint: how the value should look (e.g. "ISO date yyyy-mm-dd"), or null.
- na_means: what "N/A" means for this property, or null.
- notes: extra extraction guidance for pitfalls, or null.

ALLOWED GROUPS (in layout order)
{group_lines}

ALLOWED TYPES and the value shape each one produces
{type_lines}

ALLOWED COMPARE MODES
{compare_lines}

TYPE -> COMPARE PAIRING (follow it)
{pairing}
  Use "judge" for free-text properties whose wording varies between carriers.

RULES
1. Include only properties a product specification document would actually state. \
Never invent properties for features the product type does not have.
2. One fact per property. Split combined facts (e.g. minimum and maximum issue age \
are one age_bands property, but premium minimums and maximums are separate).
3. Cover every group that has relevant provisions, and make the list complete enough \
for a full comparison (typically 25-45 properties).
4. If the category data marks a provision area "not applicable", generate nothing \
for it.
5. Properties derived from administrative or meta areas (claims processing steps, \
transactions, data requirements, regulations) must still be things a spec document \
states, such as claim filing limits, state variations or form numbers. Skip the area \
if nothing comparable exists.
6. Keys and labels must be unique. Do not output any text outside the \
required JSON.
"""


def _category_block(category: str, product_type: str) -> str:
    cat_name = CATEGORY_NAMES[category]
    type_name = CATEGORIES[category][product_type]
    lines = [
        "<target>",
        f"category: {cat_name}",
        f"product_type: {type_name}",
        "</target>",
        "",
        f"<category_provisions category=\"{cat_name}\">",
        "Business provision areas for this category and the group each feeds:",
    ]
    for row, by_cat in PROVISION_ROWS.items():
        text = by_cat[category]
        group = ROW_TO_GROUP.get(row)
        target = f"group={group}" if group else "context only, no group"
        lines.append(f"- {row} [{target}]: {text if text else 'NOT APPLICABLE, generate nothing'}")
    lines.append("</category_provisions>")
    emphasis = TYPE_EMPHASIS.get((category, product_type))
    if emphasis:
        lines += ["", "<product_type_emphasis>", emphasis, "</product_type_emphasis>"]
    return "\n".join(lines)


def _fewshot_block() -> str:
    examples = [policy_schema.BY_KEY[k].to_dict() for k in FEWSHOT_KEYS]
    for e in examples:  # match the response schema's field name
        e["not_"] = e.pop("not")
    return ("<examples>\nExisting properties from a hardcoded annuity registry, showing the "
            "expected style and level of detail (do not copy them unless they fit the "
            "target product type):\n"
            + json.dumps(examples, indent=2, ensure_ascii=False) + "\n</examples>")


def build_prompt(category: str, product_type: str,
                 feedback: list[str] | None = None) -> list[dict]:
    if category not in CATEGORIES or product_type not in CATEGORIES[category]:
        raise ValueError(f"unknown category/product type: {category!r}/{product_type!r}")
    user = (_category_block(category, product_type) + "\n\n" + _fewshot_block() + "\n\n"
            "<task>\nGenerate the complete property list for the target product type, "
            "following the rules and response schema exactly.\n</task>")
    if feedback:
        user += ("\n\n<corrections>\nYour previous answer was invalid. Fix every problem "
                 "and return the full corrected list:\n"
                 + "\n".join(f"- {f}" for f in feedback) + "\n</corrections>")
    return [{"role": "system", "content": _system_prompt()},
            {"role": "user", "content": user}]


def render_prompt_text(messages: list[dict]) -> str:
    return "\n\n".join(f"===== {m['role'].upper()} =====\n{m['content']}" for m in messages)


def save_prompt(category: str, product_type: str) -> pathlib.Path:
    path = PROMPTS_DIR / category / f"{product_type}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_prompt_text(build_prompt(category, product_type)), encoding="utf-8")
    return path
