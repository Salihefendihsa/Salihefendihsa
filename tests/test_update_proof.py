"""Meaningful failure and boundary tests for the aggregate proof card."""
from __future__ import annotations

import datetime as dt
import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import update_proof as proof  # noqa: E402


def repo(repo_id: int, name: str, owner: str = proof.OWNER, private: bool = False) -> dict:
    return {"id": repo_id, "name": name, "full_name": f"{owner}/{name}",
            "owner": {"login": owner}, "private": private, "default_branch": "main"}


def commit(number: int, date: str, login: str = proof.OWNER) -> dict:
    return {"sha": f"{number:040x}", "author": {"login": login},
            "commit": {"author": {"date": date}}}


def pull(date: str, login: str = proof.OWNER) -> dict:
    return {"user": {"login": login}, "created_at": date}


class FakeApi:
    def __init__(self, repos: list[dict], commits: dict[str, list[dict]], pulls: dict[str, list[dict]]):
        self.repos, self.commits, self.pulls = repos, commits, pulls

    def pages(self, path: str) -> list[dict]:
        if path.startswith("user/repos?"):
            return self.repos
        name = path.split("/")[1] + "/" + path.split("/")[2]
        if "/commits?" in path:
            return self.commits.get(name, [])
        if "/pulls?" in path:
            return self.pulls.get(name, [])
        raise AssertionError(path)


class PaginationTests(unittest.TestCase):
    def test_exact_page_size_requests_next_page_and_never_truncates(self):
        api = proof.GhApi()
        requested = []

        def get(path):
            requested.append(path)
            if "&page=1" in path:
                return [{"id": i} for i in range(100)]
            if "&page=2" in path:
                return [{"id": 100}]
            raise AssertionError(path)

        api.get = get
        self.assertEqual(len(api.pages("user/repos?sort=full_name")), 101)
        self.assertEqual(len(requested), 2)

    def test_invalid_page_fails_without_partial_measurement(self):
        api = proof.GhApi()
        api.get = lambda _: {"message": "rate limit exceeded"}
        with self.assertRaises(proof.MeasurementError):
            api.pages("user/repos")

    def test_missing_actions_secret_fails_before_api(self):
        with patch.dict(os.environ, {"GH_TOKEN": ""}):
            with self.assertRaises(proof.MeasurementError):
                proof.GhApi(require_secret=True)

    def test_wrong_owner_or_missing_repo_scope_fails(self):
        api = proof.GhApi()
        api._run = lambda *_, **__: 'HTTP/2 200\nx-oauth-scopes: public_repo\n\n{"login":"Salihefendihsa"}'
        with self.assertRaises(proof.MeasurementError):
            api.preflight(require_repo_scope=True)
        api._run = lambda *_, **__: 'HTTP/2 200\nx-oauth-scopes: repo\n\n{"login":"someone-else"}'
        with self.assertRaises(proof.MeasurementError):
            api.preflight(require_repo_scope=True)


class MeasurementTests(unittest.TestCase):
    END = dt.datetime(2026, 10, 4, 6, 0, tzinfo=proof.UTC)
    START = END - dt.timedelta(days=365)

    def test_boundaries_unique_sha_owner_partner_pr_and_profile_exclusion(self):
        owner = repo(1, "product", private=True)
        mirror = repo(2, "mirror", private=False)
        partner = repo(3, "partner", owner="Partner", private=True)
        profile = repo(4, proof.OWNER)
        api = FakeApi(
            [owner, mirror, partner, profile],
            {
                owner["full_name"]: [commit(1, proof.iso(self.START)), commit(2, proof.iso(self.END)),
                                     commit(3, proof.iso(self.START - dt.timedelta(seconds=1))),
                                     commit(4, proof.iso(self.START), login="someone-else")],
                mirror["full_name"]: [commit(1, proof.iso(self.START))],
                profile["full_name"]: [commit(5, proof.iso(self.START))],
            },
            {partner["full_name"]: [pull(proof.iso(self.START)), pull(proof.iso(self.END))]},
        )
        result = proof.measure(api, self.END)
        self.assertEqual(result["commits_12m"], 1)  # same SHA in two repositories
        self.assertEqual((result["public"], result["private"]), (1, 0))
        self.assertEqual(result["repos_contributed_12m"], 3)
        self.assertEqual(result["repos_contributed_owned"], 2)
        self.assertEqual(result["verified_collaborations"], 1)
        self.assertEqual(result["owned_repos"], 3)  # profile counted only here
        self.assertEqual(result["window"]["start_utc"], proof.iso(self.START))

    def test_api_failure_cannot_be_interpreted_as_zero(self):
        class Broken(FakeApi):
            def pages(self, path):
                if "/commits?" in path:
                    raise proof.MeasurementError("rate limited")
                return super().pages(path)

        with self.assertRaises(proof.MeasurementError):
            proof.measure(Broken([repo(1, "work")], {}, {}), self.END)

    def test_explicit_empty_git_repository_is_zero_commits(self):
        class Empty(FakeApi):
            def pages(self, path):
                if "/commits?" in path:
                    raise proof.EmptyRepository("Git Repository is empty")
                return super().pages(path)

        result = proof.measure(Empty([repo(1, "empty")], {}, {}), self.END)
        self.assertEqual(result["commits_12m"], 0)
        self.assertEqual(result["owned_repos"], 1)

    def test_unchanged_values_keep_previous_date_and_generate_no_files(self):
        result = proof.measure(FakeApi([repo(1, proof.OWNER)], {}, {}), self.END)
        result.update({"contribution_window": {"year": 2026, "from": "2026-01-01", "to": "2026-12-31",
                                               "start_utc": "2026-01-01T00:00:00Z", "end_utc": "2026-12-31T23:59:59Z"},
                       "github_contributions": 4, "restricted_contributions": 2,
                       "github_commit_contributions": 1})
        old = {"metrics": [{"key": k, "value": v, "note": n, "label": k} for k, (v, n) in proof.metric_values(result).items()],
               "scope": result["scope"],
               "measurement": {k: result[k] for k in result if k not in ("measured_on", "measured_at_utc", "window")},
               "measured_on": "2026-10-03", "window": {"from": "2025-10-03", "to": "2026-10-03"}}
        fp, readme, assets, changed = proof.prepare(old, result, "existing README")
        self.assertFalse(changed)
        self.assertEqual(fp["measured_on"], "2026-10-03")
        self.assertEqual(readme, "existing README")
        self.assertFalse(assets)


class CalendarTests(unittest.TestCase):
    END = dt.datetime(2026, 10, 4, 7, 0, tzinfo=proof.UTC)

    class Api:
        def __init__(self, collection, viewer=proof.OWNER):
            self.collection, self.viewer = collection, viewer
            self.variables = None

        def graphql(self, query, variables):
            self.variables = variables
            self.query = query
            return {"viewer": {"login": self.viewer},
                    "user": {"contributionsCollection": self.collection}}

    def collection(self, *, total=1581, restricted=1252):
        return {"startedAt": "2026-01-01T00:00:00Z", "endedAt": "2026-12-31T23:59:59Z",
                "restrictedContributionsCount": restricted, "totalCommitContributions": 311,
                "contributionCalendar": {"totalContributions": total}}

    def test_exact_calendar_year_and_distinct_total(self):
        api = self.Api(self.collection())
        result = proof.measure_calendar(api, self.END)
        self.assertEqual(api.variables, {"login": proof.OWNER, "from": "2026-01-01T00:00:00Z",
                                         "to": "2026-12-31T23:59:59Z"})
        self.assertIn("contributionCalendar", api.query)
        self.assertEqual(result["github_contributions"], 1581)
        self.assertEqual(result["restricted_contributions"], 1252)
        self.assertEqual(result["contribution_window"]["year"], 2026)

    def test_wrong_viewer_or_period_or_missing_total_fails_closed(self):
        for api in (self.Api(self.collection(), viewer="other"),
                    self.Api({**self.collection(), "endedAt": "2026-10-04T00:00:00Z"}),
                    self.Api(self.collection(total=None))):
            with self.assertRaises(proof.MeasurementError):
                proof.measure_calendar(api, self.END)


if __name__ == "__main__":
    unittest.main()
