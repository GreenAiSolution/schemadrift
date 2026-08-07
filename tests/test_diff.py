import unittest

from schemadrift.diff import (
    ADDITIVE,
    BREAKING,
    CONSUMER,
    NEUTRAL,
    PRODUCER,
    _SEVERITY,
    diff,
)
from schemadrift.infer import infer

N = 40  # comfortably above the default min-samples threshold


def kinds(report):
    return {c.kind for c in report}


def by_path(report, path):
    return [c for c in report if c.path == path]


class DualityTests(unittest.TestCase):
    """The consumer/producer table is the core claim; guard its shape."""

    def test_every_kind_has_both_roles(self):
        for kind, severities in _SEVERITY.items():
            with self.subTest(kind=kind):
                self.assertEqual(len(severities), 2, kind)
                for severity in severities:
                    self.assertIn(severity, (BREAKING, ADDITIVE, NEUTRAL))

    def test_presence_and_type_changes_are_mirrored(self):
        # Only a wholesale type replacement and a pure-noise change should
        # land on the same severity for both roles.
        same = {k for k, (c, p) in _SEVERITY.items() if c == p}
        self.assertEqual(same, {"type_replaced", "field_added_optional",
                                "format_changed"})


class FieldPresenceTests(unittest.TestCase):
    def test_removed_field_breaks_consumers_only(self):
        old = infer([{"a": 1, "b": 2}] * N)
        new = infer([{"a": 1}] * N)
        self.assertEqual(by_path(diff(old, new), "$.b")[0].severity, BREAKING)
        self.assertEqual(
            by_path(diff(old, new, role=PRODUCER), "$.b")[0].severity, ADDITIVE
        )

    def test_new_required_field_breaks_producers_only(self):
        old = infer([{"a": 1}] * N)
        new = infer([{"a": 1, "b": 2}] * N)
        change = by_path(diff(old, new, role=PRODUCER), "$.b")[0]
        self.assertEqual(change.kind, "field_added_required")
        self.assertEqual(change.severity, BREAKING)
        self.assertEqual(by_path(diff(old, new), "$.b")[0].severity, ADDITIVE)

    def test_new_optional_field_breaks_nobody(self):
        old = infer([{"a": 1}] * N)
        new = infer([{"a": 1}] * N + [{"a": 1, "b": 2}] * N)
        for role in (CONSUMER, PRODUCER):
            change = by_path(diff(old, new, role=role), "$.b")[0]
            self.assertEqual(change.kind, "field_added_optional")
            self.assertEqual(change.severity, ADDITIVE)

    def test_field_becoming_optional_breaks_consumers(self):
        old = infer([{"a": 1, "b": 2}] * N)
        new = infer([{"a": 1, "b": 2}] * N + [{"a": 1}] * N)
        change = by_path(diff(old, new), "$.b")[0]
        self.assertEqual(change.kind, "field_became_optional")
        self.assertEqual(change.severity, BREAKING)

    def test_field_becoming_required_breaks_producers(self):
        old = infer([{"a": 1, "b": 2}] * N + [{"a": 1}] * N)
        new = infer([{"a": 1, "b": 2}] * N)
        change = by_path(diff(old, new, role=PRODUCER), "$.b")[0]
        self.assertEqual(change.kind, "field_became_required")
        self.assertEqual(change.severity, BREAKING)


class TypeTests(unittest.TestCase):
    def test_going_nullable_breaks_consumers(self):
        old = infer([{"a": 1}] * N)
        new = infer([{"a": 1}] * N + [{"a": None}] * N)
        change = by_path(diff(old, new), "$.a")[0]
        self.assertEqual(change.kind, "type_added")
        self.assertEqual(change.severity, BREAKING)

    def test_dropping_a_type_breaks_producers(self):
        old = infer([{"a": 1}] * N + [{"a": None}] * N)
        new = infer([{"a": 1}] * N)
        change = by_path(diff(old, new, role=PRODUCER), "$.a")[0]
        self.assertEqual(change.kind, "type_removed")
        self.assertEqual(change.severity, BREAKING)

    def test_disjoint_types_break_everyone(self):
        old = infer([{"a": 1}] * N)
        new = infer([{"a": "one"}] * N)
        for role in (CONSUMER, PRODUCER):
            change = by_path(diff(old, new, role=role), "$.a")[0]
            self.assertEqual(change.kind, "type_replaced")
            self.assertEqual(change.severity, BREAKING)

    def test_int_to_float_is_a_real_change(self):
        old = infer([{"a": 1}] * N)
        new = infer([{"a": 1.5}] * N)
        self.assertIn("type_replaced", kinds(diff(old, new)))


class EnumTests(unittest.TestCase):
    def test_new_enum_value_breaks_consumers(self):
        old = infer([{"s": "open"}, {"s": "closed"}] * N)
        new = infer([{"s": "open"}, {"s": "closed"}, {"s": "merged"}] * N)
        change = by_path(diff(old, new), "$.s")[0]
        self.assertEqual(change.kind, "enum_value_added")
        self.assertEqual(change.severity, BREAKING)
        self.assertIn("merged", change.detail)

    def test_dropped_enum_value_breaks_producers(self):
        old = infer([{"s": "open"}, {"s": "closed"}] * N)
        new = infer([{"s": "open"}] * N)
        change = by_path(diff(old, new, role=PRODUCER), "$.s")[0]
        self.assertEqual(change.kind, "enum_value_removed")
        self.assertEqual(change.severity, BREAKING)

    def test_opening_a_closed_set_breaks_consumers(self):
        old = infer([{"s": "open"}, {"s": "closed"}] * N)
        new = infer([{"s": f"state-{i}"} for i in range(N)])
        change = by_path(diff(old, new), "$.s")[0]
        self.assertEqual(change.kind, "enum_relaxed")
        self.assertEqual(change.severity, BREAKING)


class NestingTests(unittest.TestCase):
    def test_changes_inside_arrays_are_reported_with_a_path(self):
        old = infer([{"items": [{"id": 1, "name": "x"}]}] * N)
        new = infer([{"items": [{"id": 1}]}] * N)
        change = by_path(diff(old, new), "$.items[].name")[0]
        self.assertEqual(change.kind, "field_removed")

    def test_deeply_nested_paths(self):
        old = infer([{"a": {"b": {"c": 1}}}] * N)
        new = infer([{"a": {"b": {}}}] * N)
        self.assertTrue(by_path(diff(old, new), "$.a.b.c"))


class ConfidenceTests(unittest.TestCase):
    def test_small_samples_are_low_confidence(self):
        old = infer([{"a": 1, "b": 2}] * 3)
        new = infer([{"a": 1}] * 3)
        report = diff(old, new)
        self.assertEqual(report.changes[0].confidence, "low")
        # ...and low-confidence findings do not raise the reported severity.
        self.assertEqual(report.worst_severity(), NEUTRAL)
        self.assertEqual(report.worst_severity(include_low=True), BREAKING)

    def test_threshold_is_configurable(self):
        old = infer([{"a": 1, "b": 2}] * 3)
        new = infer([{"a": 1}] * 3)
        report = diff(old, new, min_samples=2)
        self.assertEqual(report.changes[0].confidence, "high")


class ReportTests(unittest.TestCase):
    def test_identical_schemas_produce_nothing(self):
        node = infer([{"a": 1, "b": [1, 2]}] * N)
        self.assertEqual(len(diff(node, node)), 0)

    def test_bad_role_is_rejected(self):
        node = infer([{"a": 1}])
        with self.assertRaises(ValueError):
            diff(node, node, role="everyone")

    def test_to_dict_is_json_ready(self):
        import json

        old = infer([{"a": 1, "b": 2}] * N)
        new = infer([{"a": 1}] * N)
        payload = diff(old, new).to_dict()
        self.assertEqual(payload["worst_severity"], BREAKING)
        self.assertEqual(payload["counts"][BREAKING], 1)
        json.dumps(payload)  # must not raise


if __name__ == "__main__":
    unittest.main()
