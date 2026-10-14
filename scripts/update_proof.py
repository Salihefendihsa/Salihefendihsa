#!/usr/bin/env python3
"""Refresh only the profile proof card from complete, token-visible GitHub data.

The authenticated user must be the profile owner. The count uses one rolling
365-day UTC interval [start, end), default-branch commits whose REST `author`
is linked to that user, and authored PRs as repository-level evidence. The
profile repository is excluded from activity counts to avoid an update loop.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import os
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

from render_assets import render_proof, write_if_changed

OWNER = "Salihefendihsa"
ROOT = Path(__file__).resolve().parents[1]
UTC = dt.timezone.utc
PAGE_SIZE = 100
MAX_PAGES = 10000
METRIC_KEYS = ("github_contributions", "commits_12m", "repos_contributed_12m", "owned_repos", "verified_collaborations")

CONTRIBUTIONS_QUERY = """query($login:String!,$from:DateTime!,$to:DateTime!){
  viewer{login}
  user(login:$login){contributionsCollection(from:$from,to:$to){
    startedAt endedAt restrictedContributionsCount totalCommitContributions
    contributionCalendar{totalContributions}
  }}
}"""


class MeasurementError(RuntimeError):
    """Safe, non-identifying failure message for CI logs."""


class EmptyRepository(MeasurementError):
    """GitHub's explicit 409 for a repository without a commit history."""


def parse_time(value: str) -> dt.datetime:
    try:
        result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError("timezone missing")
        return result.astimezone(UTC)
    except (TypeError, ValueError, AttributeError) as exc:
        raise MeasurementError("GitHub returned an invalid timestamp") from exc


def iso(value: dt.datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def in_window(value: str, start: dt.datetime, end: dt.datetime) -> bool:
    return start <= parse_time(value) < end


class GhApi:
    def __init__(self, *, require_secret: bool = False):
        if require_secret and not os.environ.get("GH_TOKEN", "").strip():
            raise MeasurementError("PROFILE_STATS_TOKEN is missing; existing card preserved")

    def _run(self, path: str, *, include_headers: bool = False) -> str:
        args = ["gh", "api", "--method", "GET"]
        if include_headers:
            args.append("--include")
        args.append(path)
        try:
            result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=90)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise MeasurementError("GitHub API request failed; existing card preserved") from exc
        if result.returncode:
            # Do not echo gh's stderr: a private repository name may appear in it.
            status = re.search(r"(?:HTTP|status)\s+(\d{3})", result.stderr, re.I)
            kind = "commits" if "/commits?" in path else "pull requests" if "/pulls?" in path else "repository list" if "user/repos" in path else "authentication"
            if kind == "commits" and status and status.group(1) == "409" and "Git Repository is empty" in result.stderr:
                raise EmptyRepository("GitHub repository has no commits")
            raise MeasurementError(f"GitHub API {status.group(1) if status else 'error'} while reading {kind}; existing card preserved")
        return result.stdout

    def get(self, path: str) -> object:
        try:
            return json.loads(self._run(path))
        except json.JSONDecodeError as exc:
            raise MeasurementError("GitHub API returned invalid JSON; existing card preserved") from exc

    def graphql(self, query: str, variables: dict[str, str]) -> dict:
        args = ["gh", "api", "graphql", "-f", f"query={query}"]
        for key, value in variables.items():
            args += ["-f", f"{key}={value}"]
        try:
            response = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=90)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise MeasurementError("GitHub GraphQL request failed; existing profile preserved") from exc
        if response.returncode:
            raise MeasurementError("GitHub GraphQL returned an error; existing profile preserved")
        try:
            data = json.loads(response.stdout)
        except json.JSONDecodeError as exc:
            raise MeasurementError("GitHub GraphQL returned invalid JSON; existing profile preserved") from exc
        if not isinstance(data, dict) or data.get("errors") or not isinstance(data.get("data"), dict):
            raise MeasurementError("GitHub GraphQL result is incomplete; existing profile preserved")
        return data["data"]

    def preflight(self, *, require_repo_scope: bool = False) -> None:
        raw = self._run("user", include_headers=True)
        parts = re.split(r"\r?\n\r?\n", raw, maxsplit=1)
        if len(parts) != 2:
            raise MeasurementError("GitHub authentication response is incomplete")
        try:
            user = json.loads(parts[1])
        except json.JSONDecodeError as exc:
            raise MeasurementError("GitHub authentication response is invalid") from exc
        if (user.get("login") or "").casefold() != OWNER.casefold():
            raise MeasurementError("Statistics credential is not the profile owner")
        if require_repo_scope:
            match = re.search(r"^x-oauth-scopes:\s*(.*)$", parts[0], re.I | re.M)
            scopes = {s.strip() for s in (match.group(1) if match else "").split(",")}
            if "repo" not in scopes:
                raise MeasurementError("Statistics credential needs classic PAT repo scope; existing card preserved")

    def pages(self, path: str) -> list[dict]:
        """Consume every REST page, including an empty page after an exact multiple of 100."""
        items: list[dict] = []
        for page in range(1, MAX_PAGES + 1):
            joiner = "&" if "?" in path else "?"
            data = self.get(f"{path}{joiner}per_page={PAGE_SIZE}&page={page}")
            if not isinstance(data, list) or len(data) > PAGE_SIZE or any(not isinstance(x, dict) for x in data):
                raise MeasurementError("GitHub pagination response is incomplete; existing card preserved")
            items.extend(data)
            if len(data) < PAGE_SIZE:
                return items
        raise MeasurementError("GitHub pagination limit reached; existing card preserved")


def measure_calendar(api: GhApi, end: dt.datetime) -> dict:
    """Use the exact calendar-year range shown by GitHub's year graph."""
    end = end.astimezone(UTC)
    year = end.year
    start_utc = f"{year}-01-01T00:00:00Z"
    end_utc = f"{year}-12-31T23:59:59Z"
    data = api.graphql(CONTRIBUTIONS_QUERY, {"login": OWNER, "from": start_utc, "to": end_utc})
    if not isinstance(data.get("viewer"), dict) or (data["viewer"].get("login") or "").casefold() != OWNER.casefold():
        raise MeasurementError("Contribution viewer is not the profile owner; profile preserved")
    user = data.get("user")
    collection = user.get("contributionsCollection") if isinstance(user, dict) else None
    if not isinstance(collection, dict) or collection.get("startedAt") != start_utc or collection.get("endedAt") != end_utc:
        raise MeasurementError("Contribution period differs from the requested calendar year; profile preserved")
    calendar = collection.get("contributionCalendar")
    total = calendar.get("totalContributions") if isinstance(calendar, dict) else None
    restricted = collection.get("restrictedContributionsCount")
    commit_contributions = collection.get("totalCommitContributions")
    if (any(not isinstance(value, int) or value < 0 for value in (total, restricted, commit_contributions))
            or restricted > total or commit_contributions > total):
        raise MeasurementError("Contribution totals are incomplete; profile preserved")
    return {
        "contribution_window": {"year": year, "from": f"{year}-01-01", "to": f"{year}-12-31",
                                "start_utc": start_utc, "end_utc": end_utc},
        "github_contributions": total,
        "restricted_contributions": restricted,
        "github_commit_contributions": commit_contributions,
    }


def measure(api: GhApi, end: dt.datetime, *, repos: list[dict] | None = None,
            evidence: dict[int, dict[str, int]] | None = None) -> dict:
    if end.tzinfo is None:
        raise ValueError("end must have a timezone")
    end = end.astimezone(UTC)
    start = end - dt.timedelta(days=365)
    if repos is None:
        repos = api.pages("user/repos?affiliation=owner,collaborator,organization_member&sort=full_name")
    by_id: dict[int, dict] = {}
    for repo in repos:
        if not isinstance(repo.get("id"), int) or not isinstance(repo.get("private"), bool):
            raise MeasurementError("GitHub repository metadata is incomplete")
        if not isinstance(repo.get("owner"), dict) or not repo["owner"].get("login"):
            raise MeasurementError("GitHub repository owner is missing")
        if not isinstance(repo.get("full_name"), str) or not repo.get("default_branch"):
            raise MeasurementError("GitHub repository identity is incomplete")
        by_id[repo["id"]] = repo

    owned = [r for r in by_id.values() if r["owner"]["login"].casefold() == OWNER.casefold()]
    sha_public: dict[str, bool] = {}
    contributed_owned = 0
    contributed_partner = 0
    for repo in sorted(by_id.values(), key=lambda x: x["id"]):
        # Profile automation's own commits never affect the activity metrics.
        is_owned = repo["owner"]["login"].casefold() == OWNER.casefold()
        if is_owned and repo["name"].casefold() == OWNER.casefold():
            continue
        full = urllib.parse.quote(repo["full_name"], safe="/")
        branch = urllib.parse.quote(repo["default_branch"], safe="")
        try:
            commits = api.pages(f"repos/{full}/commits?sha={branch}&author={OWNER}")
        except EmptyRepository:
            commits = []
        has_commit = False
        repo_shas: set[str] = set()
        for commit in commits:
            author = commit.get("author") or {}
            if not isinstance(author, dict) or (author.get("login") or "").casefold() != OWNER.casefold():
                continue
            timestamp = ((commit.get("commit") or {}).get("author") or {}).get("date")
            if not timestamp:
                raise MeasurementError("An associated commit has no author timestamp")
            if not in_window(timestamp, start, end):
                continue
            sha = commit.get("sha")
            if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40,64}", sha, re.I):
                raise MeasurementError("GitHub returned an invalid commit SHA")
            has_commit = True
            repo_shas.add(sha)
            sha_public[sha] = sha_public.get(sha, False) or not repo["private"]

        pulls = api.pages(f"repos/{full}/pulls?state=all&sort=created&direction=desc")
        has_pr = False
        authored_prs = 0
        for pull in pulls:
            if ((pull.get("user") or {}).get("login") or "").casefold() != OWNER.casefold():
                continue
            if not pull.get("created_at"):
                raise MeasurementError("An authored pull request has no creation timestamp")
            if in_window(pull["created_at"], start, end):
                has_pr = True
                authored_prs += 1
        if evidence is not None:
            evidence[repo["id"]] = {"commits": len(repo_shas), "prs": authored_prs}
        if has_commit or has_pr:
            if is_owned:
                contributed_owned += 1
            else:
                contributed_partner += 1

    public = sum(sha_public.values())
    result = {
        "measured_on": end.date().isoformat(),
        "measured_at_utc": iso(end),
        "window": {
            "from": start.date().isoformat(), "to": end.date().isoformat(),
            "start_utc": iso(start), "end_utc": iso(end),
            "label": f"{start:%b %Y} – {end:%b %Y}",
        },
        "scope": "Repositories visible to the authenticated owner; default-branch commits",
        "commits_12m": len(sha_public), "public": public, "private": len(sha_public) - public,
        "repos_contributed_12m": contributed_owned + contributed_partner,
        "repos_contributed_owned": contributed_owned,
        "repos_contributed_collab": contributed_partner,
        "owned_repos": len(owned),
        "owned_public": sum(not r["private"] for r in owned),
        "owned_private": sum(r["private"] for r in owned),
        "verified_collaborations": contributed_partner,
    }
    return result


def metric_values(result: dict) -> dict[str, tuple[int, str]]:
    return {
        "github_contributions": (result["github_contributions"], f"Jan–Dec {result['contribution_window']['year']}"),
        "commits_12m": (result["commits_12m"], f"365d · {result['public']} public"),
        "repos_contributed_12m": (result["repos_contributed_12m"], f"{result['repos_contributed_owned']} owned · {result['repos_contributed_collab']} partner"),
        "owned_repos": (result["owned_repos"], f"{result['owned_public']} public · {result['owned_private']} priv."),
        "verified_collaborations": (result["verified_collaborations"], "12m · commit/PR proof"),
    }


def prepare(old: dict, result: dict, readme: str, *, languages: list[dict] | None = None) -> tuple[dict, str, dict[str, str], bool]:
    values = metric_values(result)
    if set(values) != set(METRIC_KEYS):
        raise MeasurementError("Metric configuration is incomplete")
    previous = {m["key"]: (m["value"], m.get("note")) for m in old["metrics"]}
    same = previous == values and old.get("scope") == result["scope"] and (languages is None or old.get("languages") == languages) and old.get("measurement") == {
        k: result[k] for k in result if k not in ("measured_on", "measured_at_utc", "window")
    }
    if same:
        # Keep the last published *valid* date/window when the numbers did not
        # change. This prevents the card's own daily run from creating commits.
        return old, readme, {}, False

    footprint = copy.deepcopy(old)
    footprint["$comment"] = "GitHub contribution calendar uses a UTC calendar year. Other activity uses token-visible repositories in rolling UTC 365-day window [start_utc,end_utc). GitHub-linked author on default-branch commits; globally unique SHA. Profile repository excluded from activity; owned count includes it. Partner evidence is authored commit or PR. No private names stored."
    footprint["measured_on"] = result["measured_on"]
    footprint["measured_at_utc"] = result["measured_at_utc"]
    footprint["window"] = result["window"]
    footprint["contribution_window"] = result["contribution_window"]
    footprint["scope"] = result["scope"]
    footprint["measurement"] = {k: result[k] for k in result if k not in ("measured_on", "measured_at_utc", "window")}
    if languages is not None:
        footprint["languages"] = languages
    footprint["method_note"] = "Default-branch, GitHub-linked authored commits; SHA deduplicated globally. Authored PRs are repository evidence, never extra commits. Token-visible scope; profile repository excluded from activity."
    existing_metrics = {metric["key"]: metric for metric in footprint["metrics"]}
    footprint["metrics"] = []
    for key in METRIC_KEYS:
        metric = copy.deepcopy(existing_metrics.get(key, {}))
        metric["key"] = key
        if key == "github_contributions":
            metric["label"] = f"{result['contribution_window']['year']} GitHub contributions"
            metric["short_label"] = metric["label"]
        metric["value"], metric["note"] = values[key]
        footprint["metrics"].append(metric)

    a = result
    languages = ", ".join(f"{item['name']} {item['share']:.1f} %" for item in footprint["languages"])
    year = a["contribution_window"]["year"]
    graph_url = f"https://github.com/{OWNER}?from={year}-01-01&to={year}-12-31"
    detail = ("<details>\n<summary>How these numbers are measured</summary>\n\n<br>\n\n"
              f"- **{a['github_contributions']:,} GitHub contributions in {year}** — The GitHub GraphQL "
              "`contributionsCollection` calendar `totalContributions` for the full UTC calendar year "
              f"[{a['contribution_window']['start_utc']}, {a['contribution_window']['end_utc']}]. "
              f"GitHub reports {a['restricted_contributions']:,} restricted contributions in this collection; "
              "their repository identities are not published here. This total follows GitHub's contribution rules and is not a commit count. "
              f"[View the {year} graph]({graph_url}).\n"
              f"- **{a['commits_12m']:,} commits authored in the last 365 days** — {a['public']:,} public and {a['private']:,} private. "
              "GitHub-linked author login on accessible repositories' default branches; each SHA counted once across repositories. "
              "This authored-commit measure has a different time window and eligibility rules from the contribution graph.\n"
              f"- **{a['repos_contributed_12m']:,} repositories contributed to** — {a['repos_contributed_owned']:,} owned and {a['repos_contributed_collab']:,} partner-owned. "
              "A qualifying authored default-branch commit or authored pull request in the period is required.\n"
              f"- **{a['owned_repos']:,} owned repositories** — {a['owned_public']:,} public and {a['owned_private']:,} private, "
              "as visible to the statistics credential at measurement time; this snapshot includes the profile repository.\n"
              f"- **{a['verified_collaborations']:,} verified collaborations** — partner-owned repositories with a qualifying "
              "commit or pull request in the period. Mere access is not evidence.\n"
              f"- **Authored activity period:** UTC [{a['window']['start_utc']}, {a['window']['end_utc']}) (365 days). "
              f"Last published successful measurement: {a['measured_at_utc']}. Access scope: repositories visible to the owner's credential. "
              "The profile repository is excluded from activity counts so automated card commits cannot raise them. "
              "Hourly runs are not instant synchronization. If values have not changed, the last published successful time stays visible and no commit is made; newer successful no-op runs appear in Actions history.\n"
              f"- The year shown on this card is {year}. Profile URL `from`/`to` filters are not passed into README images; "
              "the workflow explicitly requests the calendar-year range above. Private contribution visibility and credential access can change which contributions GitHub returns.\n"
              f"- **Code by language** across token-visible owned repositories: {languages}. GitHub language bytes measured with the same credential on {a['measured_on']}.\n\n"
              "</details>")
    marked = re.compile(r"<!-- PROOF:START -->.*?<!-- PROOF:END -->", re.S)
    matches = list(marked.finditer(readme))
    if len(matches) != 1:
        raise MeasurementError("README proof markers are missing")
    section = matches[0].group(0)
    block = re.compile(r"<details>\s*<summary>How these numbers are measured</summary>.*?</details>", re.S)
    if len(block.findall(section)) != 1:
        raise MeasurementError("README measurement explanation markers are missing")
    section = block.sub(detail, section)
    alt = (f"Verified engineering footprint: {a['github_contributions']:,} GitHub contributions in {year} (calendar year), "
           f"{a['commits_12m']:,} commits authored in the last 365 days, "
           f"{a['repos_contributed_12m']:,} repositories contributed to, {a['owned_repos']:,} owned repositories, "
           f"{a['verified_collaborations']:,} verified collaborations; last published successful measurement {a['measured_at_utc']}")
    image = re.compile(r'(<img alt=")[^"]*(" src="assets/v5/proof-desktop-light\.svg")')
    if len(image.findall(section)) != 1:
        raise MeasurementError("README proof card image is missing")
    section = image.sub(lambda m: m.group(1) + alt + m.group(2), section)
    updated = readme[:matches[0].start()] + section + readme[matches[0].end():]
    assets = {
        str(Path("assets") / "v5" / f"proof-{bp}-{theme}.svg"): render_proof(footprint, theme, mobile=bp == "mobile")
        for bp in ("desktop", "mobile") for theme in ("light", "dark")
    }
    return footprint, updated, assets, True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ci", action="store_true", help="require the dedicated Actions secret and classic PAT repo scope")
    parser.add_argument("--as-of", help="test-only UTC timestamp override")
    args = parser.parse_args(argv)
    try:
        api = GhApi(require_secret=args.ci)
        api.preflight(require_repo_scope=args.ci)
        end = parse_time(args.as_of) if args.as_of else dt.datetime.now(UTC)
        result = measure(api, end)
        result.update(measure_calendar(api, end))
        footprint_path = ROOT / "data" / "footprint.json"
        readme_path = ROOT / "README.md"
        old = json.loads(footprint_path.read_text(encoding="utf-8"))
        readme = readme_path.read_text(encoding="utf-8")
        footprint, updated, assets, changed = prepare(old, result, readme)
        if not changed:
            print("proof: metrics unchanged; existing measurement retained")
            return 0
        write_if_changed(str(footprint_path), json.dumps(footprint, indent=2, ensure_ascii=False) + "\n")
        write_if_changed(str(readme_path), updated)
        for rel, content in assets.items():
            write_if_changed(str(ROOT / rel), content)
        print("proof: aggregate card refreshed (no repository identities logged)")
        return 0
    except (MeasurementError, KeyError, ValueError, TypeError) as exc:
        print(f"proof: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
