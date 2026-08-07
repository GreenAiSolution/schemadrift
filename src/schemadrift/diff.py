"""Classify the drift between two inferred schemas.

The central idea: *"breaking" is not a property of a change, it is a property
of a change plus who you are.* Adding ``null`` to a response field breaks every
consumer that reads it and costs the producer nothing. Adding a required
request field is the exact mirror. So each change kind carries a severity for
both roles, and the caller picks the role that matches the data direction.

That duality is why the table below is almost perfectly antisymmetric --
:func:`_severity` is a lookup, not a pile of special cases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator

from .infer import ARRAY, OBJECT, Node

BREAKING = "breaking"
ADDITIVE = "additive"
NEUTRAL = "neutral"

#: You read this data (typically an API response).
CONSUMER = "consumer"
#: You write this data (typically an API request body).
PRODUCER = "producer"
ROLES = (CONSUMER, PRODUCER)

SEVERITY_ORDER = {NEUTRAL: 0, ADDITIVE: 1, BREAKING: 2}

#: Below this many observations at the relevant node, a change is more likely
#: to be a sampling artifact than a real schema change.
DEFAULT_MIN_SAMPLES = 20

HIGH = "high"
LOW = "low"

# kind -> (severity for a consumer, severity for a producer)
_SEVERITY: dict[str, tuple[str, str]] = {
    "field_removed": (BREAKING, ADDITIVE),
    "field_added_required": (ADDITIVE, BREAKING),
    "field_added_optional": (ADDITIVE, ADDITIVE),
    "field_became_optional": (BREAKING, ADDITIVE),
    "field_became_required": (ADDITIVE, BREAKING),
    "type_added": (BREAKING, ADDITIVE),
    "type_removed": (ADDITIVE, BREAKING),
    "type_replaced": (BREAKING, BREAKING),
    "enum_value_added": (BREAKING, ADDITIVE),
    "enum_value_removed": (ADDITIVE, BREAKING),
    "enum_relaxed": (BREAKING, ADDITIVE),
    "enum_restricted": (ADDITIVE, BREAKING),
    "format_changed": (NEUTRAL, NEUTRAL),
}


@dataclass(frozen=True)
class Change:
    """One difference between the old and new schema."""

    path: str
    kind: str
    detail: str
    severity: str
    confidence: str

    def __str__(self) -> str:
        mark = "" if self.confidence == HIGH else " (low confidence)"
        return f"{self.severity.upper():8} {self.path}  {self.detail}{mark}"


@dataclass
class DiffReport:
    """The full set of changes, plus the knobs used to produce it."""

    changes: list[Change] = field(default_factory=list)
    role: str = CONSUMER
    min_samples: int = DEFAULT_MIN_SAMPLES

    def __iter__(self) -> Iterator[Change]:
        return iter(self.changes)

    def __len__(self) -> int:
        return len(self.changes)

    def of_severity(self, severity: str, *, include_low: bool = False) -> list[Change]:
        return [
            c
            for c in self.changes
            if c.severity == severity and (include_low or c.confidence == HIGH)
        ]

    def worst_severity(self, *, include_low: bool = False) -> str:
        worst = NEUTRAL
        for change in self.changes:
            if not include_low and change.confidence != HIGH:
                continue
            if SEVERITY_ORDER[change.severity] > SEVERITY_ORDER[worst]:
                worst = change.severity
        return worst

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "min_samples": self.min_samples,
            "worst_severity": self.worst_severity(),
            "counts": {
                severity: len(self.of_severity(severity))
                for severity in (BREAKING, ADDITIVE, NEUTRAL)
            },
            "changes": [
                {
                    "path": c.path,
                    "kind": c.kind,
                    "detail": c.detail,
                    "severity": c.severity,
                    "confidence": c.confidence,
                }
                for c in self.changes
            ],
        }


def _severity(kind: str, role: str) -> str:
    consumer, producer = _SEVERITY[kind]
    return consumer if role == CONSUMER else producer


def diff(
    old: Node,
    new: Node,
    *,
    role: str = CONSUMER,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    root: str = "$",
) -> DiffReport:
    """Compare two inferred schemas from the point of view of ``role``."""
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}, got {role!r}")
    report = DiffReport(role=role, min_samples=min_samples)
    _walk(old, new, root, report)
    return report


def _walk(old: Node, new: Node, path: str, report: DiffReport) -> None:
    _compare_types(old, new, path, report)
    _compare_enums(old, new, path, report)
    _compare_formats(old, new, path, report)

    if OBJECT in old.types and OBJECT in new.types:
        _compare_properties(old, new, path, report)

    if ARRAY in old.types and ARRAY in new.types:
        if old.items is not None and new.items is not None:
            _walk(old.items, new.items, f"{path}[]", report)


def _emit(report: DiffReport, path: str, kind: str, detail: str, evidence: int) -> None:
    report.changes.append(
        Change(
            path=path,
            kind=kind,
            detail=detail,
            severity=_severity(kind, report.role),
            confidence=HIGH if evidence >= report.min_samples else LOW,
        )
    )


def _compare_types(old: Node, new: Node, path: str, report: DiffReport) -> None:
    if not old.types or not new.types or old.types == new.types:
        return
    evidence = min(old.count, new.count)
    if not old.types & new.types:
        _emit(
            report,
            path,
            "type_replaced",
            f"type {_fmt(old.types)} -> {_fmt(new.types)}",
            evidence,
        )
        return
    added = new.types - old.types
    removed = old.types - new.types
    if added:
        _emit(report, path, "type_added", f"now also {_fmt(added)}", evidence)
    if removed:
        _emit(report, path, "type_removed", f"no longer {_fmt(removed)}", evidence)


def _compare_properties(old: Node, new: Node, path: str, report: DiffReport) -> None:
    evidence = min(old.object_count, new.object_count)
    for key in sorted(set(old.properties) | set(new.properties)):
        child_path = f"{path}.{key}"
        in_old = key in old.properties
        in_new = key in new.properties
        if in_old and not in_new:
            _emit(report, child_path, "field_removed", "field removed", evidence)
        elif in_new and not in_old:
            kind = (
                "field_added_required"
                if new.is_required(key)
                else "field_added_optional"
            )
            state = "required" if new.is_required(key) else "optional"
            _emit(report, child_path, kind, f"new {state} field", evidence)
        else:
            was, now = old.is_required(key), new.is_required(key)
            if was and not now:
                _emit(
                    report,
                    child_path,
                    "field_became_optional",
                    "required -> optional (sometimes absent)",
                    evidence,
                )
            elif now and not was:
                _emit(
                    report,
                    child_path,
                    "field_became_required",
                    "optional -> required (always present)",
                    evidence,
                )
            _walk(old.properties[key], new.properties[key], child_path, report)


def _compare_enums(old: Node, new: Node, path: str, report: DiffReport) -> None:
    old_enum, new_enum = old.enum(), new.enum()
    evidence = min(old.count, new.count)
    if old_enum is None and new_enum is None:
        return
    if old_enum is not None and new_enum is None:
        _emit(
            report,
            path,
            "enum_relaxed",
            f"no longer limited to {_fmt(old_enum)}",
            evidence,
        )
        return
    if old_enum is None and new_enum is not None:
        _emit(
            report,
            path,
            "enum_restricted",
            f"now limited to {_fmt(new_enum)}",
            evidence,
        )
        return
    assert old_enum is not None and new_enum is not None
    added = set(new_enum) - set(old_enum)
    removed = set(old_enum) - set(new_enum)
    if added:
        _emit(report, path, "enum_value_added", f"new values {_fmt(added)}", evidence)
    if removed:
        _emit(
            report, path, "enum_value_removed", f"values gone {_fmt(removed)}", evidence
        )


def _compare_formats(old: Node, new: Node, path: str, report: DiffReport) -> None:
    old_format, new_format = old.format(), new.format()
    if old_format == new_format:
        return
    _emit(
        report,
        path,
        "format_changed",
        f"format {old_format or 'none'} -> {new_format or 'none'}",
        min(old.count, new.count),
    )


def _fmt(values: Any) -> str:
    return ", ".join(sorted((str(v) for v in values), key=str))
