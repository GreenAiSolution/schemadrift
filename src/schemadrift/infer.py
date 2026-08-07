"""Infer a structural schema from real JSON payloads.

The inferred schema is a tree of :class:`Node` objects. Each node records every
JSON type it was ever observed as, how many samples reached it, and enough
detail (property presence counts, scalar cardinality, string formats) to answer
the only question that matters downstream: *did the shape of this data change,
and does the change break somebody?*

Nothing here talks to the network and nothing outside the standard library is
imported. Feed it samples, get a schema.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

# JSON Schema type names. `integer` is tracked separately from `number` because
# a consumer that parses a field as an int genuinely breaks when floats appear.
NULL = "null"
BOOLEAN = "boolean"
INTEGER = "integer"
NUMBER = "number"
STRING = "string"
ARRAY = "array"
OBJECT = "object"

#: Above this many distinct scalar values a field is no longer enum-like.
MAX_ENUM_VALUES = 12
#: Below this many samples there is not enough evidence to call anything an enum.
MIN_ENUM_SAMPLES = 8
#: Stop retaining distinct values once a field is obviously free-form.
MAX_TRACKED_VALUES = 128

_FORMAT_PATTERNS: dict[str, re.Pattern[str]] = {
    "uuid": re.compile(
        r"\A[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
        r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z"
    ),
    "date-time": re.compile(
        r"\A\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}:\d{2}"
        r"(\.\d+)?([Zz]|[+-]\d{2}:\d{2})\Z"
    ),
    "date": re.compile(r"\A\d{4}-\d{2}-\d{2}\Z"),
    "time": re.compile(r"\A\d{2}:\d{2}:\d{2}(\.\d+)?\Z"),
    "email": re.compile(r"\A[^@\s]+@[^@\s.]+\.[^@\s]+\Z"),
    "uri": re.compile(r"\A[a-zA-Z][a-zA-Z0-9+.-]*://[^\s]+\Z"),
    "ipv4": re.compile(r"\A(\d{1,3}\.){3}\d{1,3}\Z"),
}

# Checked in order; the first match wins so `date-time` beats the looser rules.
_FORMAT_ORDER = ("uuid", "date-time", "date", "time", "email", "uri", "ipv4")


def detect_formats(value: str) -> frozenset[str]:
    """Return every named format ``value`` satisfies."""
    return frozenset(
        name for name in _FORMAT_ORDER if _FORMAT_PATTERNS[name].fullmatch(value)
    )


@dataclass
class Node:
    """Everything observed at one position in the payload tree."""

    #: JSON type names seen at this position, e.g. ``{"string", "null"}``.
    types: set[str] = field(default_factory=set)
    #: How many samples reached this position at all.
    count: int = 0
    #: How many of those samples were objects (the denominator for `required`).
    object_count: int = 0
    #: How many of those samples were arrays.
    array_count: int = 0
    #: Child schema per object key. Absence from a sample is what makes a
    #: property optional, so child ``count`` is compared against ``object_count``.
    properties: dict[str, "Node"] = field(default_factory=dict)
    #: Unified schema of every array element ever seen.
    items: "Node | None" = None
    #: Distinct scalar values, retained only while the field stays low-cardinality.
    values: set[Any] = field(default_factory=set)
    #: Set once the field blows past :data:`MAX_TRACKED_VALUES`.
    values_overflowed: bool = False
    #: Intersection of formats matched by every string sample. ``None`` until the
    #: first string arrives.
    formats: frozenset[str] | None = None

    # -- observation ----------------------------------------------------

    def observe(self, value: Any) -> None:
        """Fold one sample into this node."""
        self.count += 1
        kind = type_of(value)
        self.types.add(kind)

        if kind == OBJECT:
            self.object_count += 1
            for key, child_value in value.items():
                child = self.properties.get(key)
                if child is None:
                    child = self.properties[key] = Node()
                child.observe(child_value)
        elif kind == ARRAY:
            self.array_count += 1
            if self.items is None:
                self.items = Node()
            for element in value:
                self.items.observe(element)
        else:
            self._track_scalar(kind, value)

    def _track_scalar(self, kind: str, value: Any) -> None:
        if kind == STRING:
            matched = detect_formats(value)
            self.formats = matched if self.formats is None else self.formats & matched
        if kind in (NULL, BOOLEAN):
            return  # `null`/`bool` cardinality carries no information
        if self.values_overflowed:
            return
        self.values.add(value)
        if len(self.values) > MAX_TRACKED_VALUES:
            self.values_overflowed = True
            self.values.clear()

    # -- derived facts --------------------------------------------------

    def is_required(self, key: str) -> bool:
        """True when ``key`` was present in *every* object sample here."""
        child = self.properties.get(key)
        if child is None or self.object_count == 0:
            return False
        return child.count == self.object_count

    def required_keys(self) -> list[str]:
        return sorted(k for k in self.properties if self.is_required(k))

    def optional_keys(self) -> list[str]:
        return sorted(k for k in self.properties if not self.is_required(k))

    def enum(self) -> tuple[Any, ...] | None:
        """Candidate enum values, or ``None`` if the field is free-form.

        A field is enum-like when it is a low-cardinality scalar *and* the
        values repeat enough that the small set is evidence rather than an
        artifact of a small sample.
        """
        if self.values_overflowed or not self.values:
            return None
        if not self.types <= {STRING, INTEGER, NULL}:
            return None
        distinct = len(self.values)
        if distinct > MAX_ENUM_VALUES:
            return None
        if self.count < max(MIN_ENUM_SAMPLES, 3 * distinct):
            return None
        return tuple(sorted(self.values, key=repr))

    def format(self) -> str | None:
        """The single most specific format every string sample matched."""
        if not self.formats:
            return None
        for name in _FORMAT_ORDER:
            if name in self.formats:
                return name
        return None

    # -- export ---------------------------------------------------------

    def to_json_schema(self) -> dict[str, Any]:
        """Render as a JSON Schema 2020-12 fragment."""
        schema: dict[str, Any] = {}
        types = sorted(self.types)
        if len(types) == 1:
            schema["type"] = types[0]
        elif types:
            schema["type"] = types

        fmt = self.format()
        if fmt:
            schema["format"] = fmt

        enum = self.enum()
        if enum is not None:
            schema["enum"] = list(enum)

        if OBJECT in self.types:
            schema["properties"] = {
                key: child.to_json_schema()
                for key, child in sorted(self.properties.items())
            }
            required = self.required_keys()
            if required:
                schema["required"] = required

        if ARRAY in self.types and self.items is not None:
            schema["items"] = self.items.to_json_schema()

        return schema


def type_of(value: Any) -> str:
    """JSON Schema type name for a decoded Python value."""
    if value is None:
        return NULL
    if isinstance(value, bool):  # must precede int: bool subclasses int
        return BOOLEAN
    if isinstance(value, int):
        return INTEGER
    if isinstance(value, float):
        return NUMBER
    if isinstance(value, str):
        return STRING
    if isinstance(value, (list, tuple)):
        return ARRAY
    if isinstance(value, dict):
        return OBJECT
    raise TypeError(f"not a JSON value: {type(value).__name__}")


def infer(samples: Iterable[Any]) -> Node:
    """Infer one schema covering every sample."""
    root = Node()
    for sample in samples:
        root.observe(sample)
    return root
