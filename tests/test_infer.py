import unittest

from schemadrift.infer import (
    MAX_TRACKED_VALUES,
    Node,
    detect_formats,
    infer,
    type_of,
)


class TypeOfTests(unittest.TestCase):
    def test_bool_is_not_integer(self):
        # bool subclasses int in Python; getting this wrong makes every
        # boolean field look like an enum of 0 and 1.
        self.assertEqual(type_of(True), "boolean")
        self.assertEqual(type_of(1), "integer")

    def test_float_is_number(self):
        self.assertEqual(type_of(1.5), "number")

    def test_rejects_non_json(self):
        with self.assertRaises(TypeError):
            type_of(object())


class FormatTests(unittest.TestCase):
    def test_detects_uuid(self):
        self.assertIn("uuid", detect_formats("6f1e8e0c-3f1a-4a63-9d0e-6b1f4a2c8d10"))

    def test_date_time_is_not_a_date(self):
        matched = detect_formats("2026-08-07T12:30:00Z")
        self.assertEqual(matched, {"date-time"})

    def test_format_is_the_intersection_of_all_samples(self):
        node = infer(["2026-08-07", "not a date"])
        self.assertIsNone(node.format())

    def test_most_specific_format_wins(self):
        node = infer(["2026-08-07T12:30:00Z"] * 3)
        self.assertEqual(node.format(), "date-time")


class RequiredTests(unittest.TestCase):
    def test_key_in_every_sample_is_required(self):
        node = infer([{"a": 1}, {"a": 2}])
        self.assertEqual(node.required_keys(), ["a"])

    def test_missing_once_makes_it_optional(self):
        node = infer([{"a": 1}, {"a": 2}, {}])
        self.assertEqual(node.required_keys(), [])
        self.assertEqual(node.optional_keys(), ["a"])

    def test_explicit_null_still_counts_as_present(self):
        node = infer([{"a": 1}, {"a": None}])
        self.assertEqual(node.required_keys(), ["a"])
        self.assertEqual(node.properties["a"].types, {"integer", "null"})


class EnumTests(unittest.TestCase):
    def test_repeated_low_cardinality_strings_are_an_enum(self):
        node = infer(["open", "closed"] * 10)
        self.assertEqual(node.enum(), ("closed", "open"))

    def test_too_few_samples_is_not_evidence(self):
        # Two distinct values over two samples is not an enum, it is a coincidence.
        self.assertIsNone(infer(["open", "closed"]).enum())

    def test_free_form_strings_are_not_an_enum(self):
        self.assertIsNone(infer([f"user-{i}" for i in range(50)]).enum())

    def test_high_cardinality_stops_retaining_values(self):
        node = infer([f"v{i}" for i in range(MAX_TRACKED_VALUES + 5)])
        self.assertTrue(node.values_overflowed)
        self.assertEqual(node.values, set())

    def test_booleans_are_never_enums(self):
        self.assertIsNone(infer([True, False] * 20).enum())


class NestingTests(unittest.TestCase):
    def test_nested_objects_and_arrays(self):
        node = infer([{"tags": [{"name": "a"}]}, {"tags": [{"name": "b"}]}])
        tags = node.properties["tags"]
        self.assertEqual(tags.types, {"array"})
        self.assertEqual(tags.items.properties["name"].types, {"string"})

    def test_array_items_unify_across_samples(self):
        node = infer([{"v": [1]}, {"v": ["x"]}])
        self.assertEqual(node.properties["v"].items.types, {"integer", "string"})

    def test_empty_array_leaves_items_empty(self):
        node = infer([[]])
        self.assertEqual(node.types, {"array"})
        self.assertEqual(node.items.types, set())


class JsonSchemaTests(unittest.TestCase):
    def test_round_trip_shape(self):
        node = infer([{"id": i, "state": "open"} for i in range(40)])
        schema = node.to_json_schema()
        self.assertEqual(schema["type"], "object")
        self.assertEqual(schema["required"], ["id", "state"])
        self.assertEqual(schema["properties"]["state"]["enum"], ["open"])

    def test_union_type_is_a_list(self):
        schema = infer([1, None]).to_json_schema()
        self.assertEqual(schema["type"], ["integer", "null"])

    def test_empty_input_yields_empty_schema(self):
        self.assertEqual(infer([]).to_json_schema(), {})
        self.assertEqual(Node().count, 0)


if __name__ == "__main__":
    unittest.main()
