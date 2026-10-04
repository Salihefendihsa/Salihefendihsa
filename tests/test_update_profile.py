"""Coverage for the shared profile snapshot and private evidence mapping."""
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import update_profile as profile  # noqa: E402
import update_proof as proof  # noqa: E402


class FakeApi:
    def __init__(self, data):
        self.data = data

    def get(self, path):
        if path not in self.data:
            raise proof.MeasurementError("API unavailable")
        return self.data[path]


class SharedSnapshotTests(unittest.TestCase):
    def test_language_bytes_include_private_owned_but_not_partner(self):
        repos = [
            {"full_name": "Salihefendihsa/one", "owner": {"login": proof.OWNER}},
            {"full_name": "Salihefendihsa/two", "owner": {"login": proof.OWNER}},
            {"full_name": "Partner/three", "owner": {"login": "Partner"}},
        ]
        api = FakeApi({"repos/Salihefendihsa/one/languages": {"Python": 75, "Dart": 25},
                       "repos/Salihefendihsa/two/languages": {"Python": 25, "C#": 75}})
        self.assertEqual(profile.language_distribution(api, repos), [
            {"name": "Python", "share": 50.0},
            {"name": "C#", "share": 37.5},
            {"name": "Dart", "share": 12.5},
        ])

    def test_language_api_failure_cannot_publish_partial_distribution(self):
        repos = [{"full_name": "Salihefendihsa/private", "owner": {"login": proof.OWNER}}]
        with self.assertRaises(proof.MeasurementError):
            profile.language_distribution(FakeApi({}), repos)

    def test_collaboration_requires_access_and_current_evidence(self):
        config = {"products": [{"repository_sources": [{"kind": "collaboration", "repository_id": 7}],
                                "collaboration": {"label": "Collaboration", "evidence": "stale 99 commits"}}]}
        repo = {"id": 7, "owner": {"login": "Partner"}, "private": True}
        updated = profile.apply_collaboration_evidence(config, [repo], {7: {"commits": 3, "prs": 2}})
        self.assertEqual(updated["products"][0]["collaboration"]["evidence"], "3 authored commits · 2 PRs (12m)")
        self.assertEqual(config["products"][0]["collaboration"]["evidence"], "stale 99 commits")
        with self.assertRaises(proof.MeasurementError):
            profile.apply_collaboration_evidence(config, [], {})

    def test_zero_current_evidence_removes_verified_label(self):
        config = {"products": [{"repository_sources": [{"kind": "collaboration", "repository_id": 7}],
                                "collaboration": {"label": "Collaboration", "evidence": "stale"}}]}
        updated = profile.apply_collaboration_evidence(config, [{"id": 7, "owner": {"login": "Partner"}, "private": True}],
                                                       {7: {"commits": 0, "prs": 0}})
        self.assertIsNone(updated["products"][0]["collaboration"])


if __name__ == "__main__":
    unittest.main()
