import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import schemadrift
from schemadrift.cli import EXIT_DRIFT, EXIT_ERROR, EXIT_OK, main


class CliTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def write(self, name, samples):
        path = Path(self.dir.name) / name
        path.write_text("\n".join(json.dumps(s) for s in samples), encoding="utf-8")
        return str(path)

    def run_cli(self, *argv):
        out = io.StringIO()
        code = main(list(argv), out=out)
        return code, out.getvalue()

    def test_infer_prints_a_schema(self):
        path = self.write("v1.ndjson", [{"id": i, "state": "open"} for i in range(30)])
        code, output = self.run_cli("infer", path)
        schema = json.loads(output)
        self.assertEqual(code, EXIT_OK)
        self.assertIn("json-schema.org", schema["$schema"])
        self.assertEqual(schema["required"], ["id", "state"])

    def test_diff_exits_nonzero_on_breaking_change(self):
        old = self.write("v1", [{"a": 1, "b": 2}] * 40)
        new = self.write("v2", [{"a": 1}] * 40)
        code, output = self.run_cli("diff", old, new)
        self.assertEqual(code, EXIT_DRIFT)
        self.assertIn("BREAKING", output)
        self.assertIn("$.b", output)

    def test_same_change_is_clean_for_the_other_role(self):
        old = self.write("v1", [{"a": 1, "b": 2}] * 40)
        new = self.write("v2", [{"a": 1}] * 40)
        code, output = self.run_cli("diff", old, new, "--role", "producer")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("ADDITIVE", output)

    def test_no_drift_exits_zero(self):
        old = self.write("v1", [{"a": 1}] * 40)
        new = self.write("v2", [{"a": 1}] * 40)
        code, output = self.run_cli("diff", old, new)
        self.assertEqual(code, EXIT_OK)
        self.assertIn("No drift detected", output)

    def test_low_confidence_does_not_fail_the_build_by_default(self):
        old = self.write("v1", [{"a": 1, "b": 2}] * 3)
        new = self.write("v2", [{"a": 1}] * 3)
        self.assertEqual(self.run_cli("diff", old, new)[0], EXIT_OK)
        self.assertEqual(
            self.run_cli("diff", old, new, "--include-low-confidence")[0], EXIT_DRIFT
        )

    def test_fail_on_additive_is_stricter(self):
        old = self.write("v1", [{"a": 1}] * 40)
        new = self.write("v2", [{"a": 1, "b": 2}] * 40)
        self.assertEqual(self.run_cli("diff", old, new)[0], EXIT_OK)
        self.assertEqual(
            self.run_cli("diff", old, new, "--fail-on", "additive")[0], EXIT_DRIFT
        )

    def test_fail_on_never_always_succeeds(self):
        old = self.write("v1", [{"a": 1, "b": 2}] * 40)
        new = self.write("v2", [{"a": 1}] * 40)
        self.assertEqual(
            self.run_cli("diff", old, new, "--fail-on", "never")[0], EXIT_OK
        )

    def test_json_output_is_machine_readable(self):
        old = self.write("v1", [{"a": 1, "b": 2}] * 40)
        new = self.write("v2", [{"a": 1}] * 40)
        code, output = self.run_cli("diff", old, new, "--json")
        payload = json.loads(output)
        self.assertEqual(code, EXIT_DRIFT)
        self.assertEqual(payload["role"], "consumer")
        self.assertEqual(payload["changes"][0]["kind"], "field_removed")

    def test_version_names_the_program(self):
        buf = io.StringIO()
        with self.assertRaises(SystemExit) as ctx:
            with contextlib.redirect_stdout(buf):
                main(["--version"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertEqual(buf.getvalue().strip(), f"schemadrift {schemadrift.__version__}")

    def test_missing_file_is_an_error_not_a_crash(self):
        good = self.write("v1", [{"a": 1}])
        code, _ = self.run_cli("diff", good, "/nonexistent/nope.ndjson")
        self.assertEqual(code, EXIT_ERROR)


if __name__ == "__main__":
    unittest.main()
