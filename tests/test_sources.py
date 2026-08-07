import unittest

from schemadrift.sources import SampleError, parse_samples


class SourceTests(unittest.TestCase):
    def test_ndjson(self):
        self.assertEqual(parse_samples('{"a":1}\n{"a":2}\n'), [{"a": 1}, {"a": 2}])

    def test_json_array_is_many_samples(self):
        self.assertEqual(parse_samples('[{"a":1},{"a":2}]'), [{"a": 1}, {"a": 2}])

    def test_single_object_is_one_sample(self):
        self.assertEqual(parse_samples('{"a":1}'), [{"a": 1}])

    def test_blank_lines_are_skipped(self):
        self.assertEqual(parse_samples('{"a":1}\n\n{"a":2}'), [{"a": 1}, {"a": 2}])

    def test_empty_input(self):
        self.assertEqual(parse_samples("   "), [])

    def test_broken_line_names_the_line_number(self):
        with self.assertRaises(SampleError) as ctx:
            parse_samples('{"a":1}\nnope\n', origin="cap.ndjson")
        self.assertIn("cap.ndjson:2", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
