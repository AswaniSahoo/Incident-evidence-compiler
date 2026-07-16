import unittest

import incident_evidence_compiler


class PackageTest(unittest.TestCase):
    def test_src_package_is_installed(self) -> None:
        self.assertEqual(incident_evidence_compiler.__name__, "incident_evidence_compiler")


if __name__ == "__main__":
    unittest.main()
