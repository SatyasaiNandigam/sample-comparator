"""
Pydantic schema for LLM-generated property lists.

`Property` / `PropertyListResponse` mirror policy_schema.Property (the hardcoded
annuity registry) so generated lists are a drop-in replacement for it.

No field has a default: OpenAI strict structured output requires every field to be
`required`; optional fields are `str | None` and the model returns null.
"""
from __future__ import annotations

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from pydantic import BaseModel, Field

import policy_schema
from policy_schema import COMPARE, TYPES

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class Property(BaseModel):
    key: str
    label: str
    order: int
    group: str
    type: str
    description: str
    compare: str

    aliases: list[str]

    not_: list[str] = Field(alias="not_")

    format_hint: str | None
    na_means: str | None
    notes: str | None

    model_config = {
        "populate_by_name": True,
        "extra": "forbid",
    }

    def to_legacy(self) -> policy_schema.Property:
        """Convert to the frozen dataclass used by group_prompts / the pipeline."""
        return policy_schema.Property(
            key=self.key, label=self.label, order=self.order, group=self.group,
            type=self.type, description=self.description, compare=self.compare,
            aliases=tuple(self.aliases), not_=tuple(self.not_),
            format_hint=self.format_hint, na_means=self.na_means, notes=self.notes,
        )


class PropertyListResponse(BaseModel):
    properties: list[Property] = Field(
        description="Generated list of insurance product properties."
    )

    model_config = {
        "extra": "forbid",
    }


def response_format() -> dict:
    """OpenAI 'json_schema' structured-output response_format for PropertyListResponse."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "property_list",
            "strict": True,
            "schema": PropertyListResponse.model_json_schema(),
        },
    }


def validate_property_list(resp: PropertyListResponse, groups: list[str]) -> list[str]:
    """Same rules as policy_schema.validate(), against the dynamic group list."""
    errors: list[str] = []
    props = resp.properties
    if not props:
        return ["property list is empty"]

    keys = [p.key for p in props]
    if len(keys) != len(set(keys)):
        dupes = sorted({k for k in keys if keys.count(k) > 1})
        errors.append(f"duplicate keys: {dupes}")
    labels = [p.label for p in props]
    if len(labels) != len(set(labels)):
        errors.append("duplicate labels")

    # `order` is only a sort hint: gaps / interleaved groups are fine and are normalized
    # by normalize_order() after validation.
    key_set = set(keys)
    for p in props:
        if not _KEY_RE.match(p.key):
            errors.append(f"{p.key}: key must be snake_case")
        if p.group not in groups:
            errors.append(f"{p.key}: unknown group {p.group!r}, allowed: {groups}")
        if p.type not in TYPES:
            errors.append(f"{p.key}: unknown type {p.type!r}, allowed: {sorted(TYPES)}")
        if p.compare not in COMPARE:
            errors.append(f"{p.key}: unknown compare {p.compare!r}, allowed: {sorted(COMPARE)}")
        if not p.description.strip():
            errors.append(f"{p.key}: empty description")
        for ref in p.not_:
            if ref == p.key:
                errors.append(f"{p.key}: 'not_' references itself")
            elif ref not in key_set:
                errors.append(f"{p.key}: 'not_' references unknown key {ref!r}")

    return errors


def normalize_order(resp: PropertyListResponse, groups: list[str]) -> None:
    """Sort by (group layout position, LLM order) and renumber 1..N, in place."""
    pos = {g: i for i, g in enumerate(groups)}
    resp.properties.sort(key=lambda p: (pos.get(p.group, len(pos)), p.order))
    for i, p in enumerate(resp.properties, 1):
        p.order = i
