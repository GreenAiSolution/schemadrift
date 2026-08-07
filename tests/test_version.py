import unittest

import schemadrift


class VersionTests(unittest.TestCase):
    def test_version_is_exposed(self):
        self.assertRegex(schemadrift.__version__, r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
