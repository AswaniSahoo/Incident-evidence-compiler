import unittest

import incident_evidence_compiler
from incident_evidence_compiler import domain
from incident_evidence_compiler.domain.errors import CanonicalSerializationError
from incident_evidence_compiler.domain.serialization import (
    CanonicalSerializationError as SerializationError,
)


class PackageTest(unittest.TestCase):
    def test_complete_phase2_domain_api_is_exported(self) -> None:
        expected = {
            "CanonicalSerializationError",
            "EVIDENCE_SCHEMA_VERSION",
            "ExpectedDirection",
            "HypothesisComposition",
            "HypothesisDocument",
            "HypothesisSemantics",
            "HypothesisVerificationResult",
            "InvalidEvidenceLedgerError",
            "InvalidHypothesisError",
            "MAX_PREDICATES",
            "MetricEvidenceLedger",
            "MetricShiftDecision",
            "MetricShiftDecisionKind",
            "MetricShiftEvidence",
            "MetricShiftPredicate",
            "ObservedDirection",
            "PredicateVerificationResult",
            "UnknownReason",
            "VERIFICATION_SCHEMA_VERSION",
            "VerificationReason",
            "VerificationVerdict",
            "compile_metric_shift_ledger",
            "ledger_json",
            "validate_hypothesis_document",
            "validate_metric_evidence_ledger",
            "verification_json",
            "verify_hypothesis",
        }
        self.assertTrue(expected.issubset(set(domain.__all__)))
        for name in expected:
            self.assertTrue(hasattr(domain, name), name)
        self.assertIs(SerializationError, CanonicalSerializationError)

    def test_src_package_is_installed(self) -> None:
        self.assertEqual(incident_evidence_compiler.__name__, "incident_evidence_compiler")


if __name__ == "__main__":
    unittest.main()
