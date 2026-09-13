import unittest
from datetime import datetime, timezone
from deepresearch_kb.version_policy import VersionCandidate, select_versions


def date(year):
    return datetime(year, 1, 1, tzinfo=timezone.utc)


class VersionPolicyTests(unittest.TestCase):
    def test_late_import_and_future_version_do_not_override_current(self):
        versions = [VersionCandidate("d", 1, date(2025)),
                    VersionCandidate("d", 2, date(2024), authority=100),
                    VersionCandidate("d", 3, date(2027))]
        self.assertEqual(select_versions(versions, at=date(2026))[0].candidate.version, 1)
        self.assertEqual(select_versions(versions, at=date(2024))[0].candidate.version, 2)
        self.assertEqual(select_versions(versions, at=date(2023)), [])

    def test_deprecation_does_not_resurrect_old_revision(self):
        versions = [VersionCandidate("d", 1, date(2024)),
                    VersionCandidate("d", 2, date(2025), date(2026))]
        self.assertEqual(select_versions(versions, at=date(2026)), [])
        self.assertEqual(select_versions(versions, at=date(2025))[0].status, "active")
        result = select_versions(versions, at=date(2026), include_deprecated=True)
        self.assertEqual(result[0].status, "deprecated")

    def test_history_requires_explicit_flags_and_ties_use_revision(self):
        versions = [VersionCandidate("d", 1, date(2025)), VersionCandidate("d", 2, date(2025))]
        result = select_versions(versions, at=date(2025), include_superseded=True)
        self.assertEqual([r.status for r in result], ["active", "superseded"])
        self.assertEqual(result[0].candidate.version, 2)

    def test_invalid_time_and_duplicate_identity_rejected(self):
        with self.assertRaises(ValueError):
            VersionCandidate("d", 1, datetime(2025, 1, 1))
        candidate = VersionCandidate("d", 1, date(2025))
        with self.assertRaises(ValueError):
            select_versions([candidate, candidate], at=date(2026))
