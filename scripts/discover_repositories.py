#!/usr/bin/env python3
"""Read-only inventory of every repository the authenticated account can access.

Writes a LOCAL audit (default: audit/, git-ignored) that is never committed:

  audit/inventory.json   one row per repository: visibility, owner, relationship
                         (owner / contributor / collaborator-access), archived and
                         fork flags, default branch, languages, latest activity,
                         description, verified contribution evidence (commits on
                         the default branch authored by the account, pull
                         requests) and the portfolio tier suggested by the rules
                         below.
  audit/footprint.json   the remeasured footprint metrics (same method as
                         data/footprint.json), with the per-repository breakdown.

`--write-footprint` copies the remeasured aggregates into data/footprint.json;
no repository name is written there.

Authentication: uses `gh` (GitHub CLI) when it is installed and logged in;
otherwise an optional token from PROFILE_DISCOVERY_TOKEN or GITHUB_TOKEN. The
token is never printed. Without any credential only public repositories are
visible and the script says so. Nothing is ever written to GitHub.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

OWNER = "Salihefendihsa"
PROFILE_REPO = OWNER
API_BASE = "https://api.github.com"
DEFAULT_OUT = "audit"
COURSEWORK_HINTS = ("lab", "odev", "ntp", "hafta", "oryantasyon")


# --------------------------------------------------------------------------- API access

def _token() -> str:
    return (os.environ.get("PROFILE_DISCOVERY_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()


def api(path: str, paginate: bool = False) -> object:
    """GET a REST path; returns parsed JSON (a list when paginated)."""
    if shutil.which("gh"):
        args = ["gh", "api"] + (["--paginate", "--slurp"] if paginate else []) + [path]
        run = subprocess.run(args, capture_output=True, text=True, encoding="utf-8")
        if run.returncode != 0:
            raise RuntimeError(f"gh api failed for {path.split('?')[0]}")
        data = json.loads(run.stdout)
        if paginate:  # --slurp returns a list of pages
            return [item for page in data for item in (page if isinstance(page, list) else [page])]
        return data
    token = _token()
    out: list = []
    url = f"{API_BASE}/{path}"
    while url:
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                   "User-Agent": f"{OWNER}-discover"})
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                link = resp.headers.get("Link", "")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"GitHub API HTTP {exc.code} for {path.split('?')[0]}") from None
        if not paginate:
            return data
        out.extend(data)
        url = ""
        for part in link.split(","):
            if 'rel="next"' in part:
                url = part[part.find("<") + 1:part.find(">")]
    return out


def list_accessible_repos() -> list[dict]:
    if shutil.which("gh") or _token():
        return api("user/repos?per_page=100&affiliation=owner,collaborator,organization_member&sort=full_name", paginate=True)
    print("discover: no credential — only public repositories are visible", file=sys.stderr)
    return api(f"users/{OWNER}/repos?type=owner&per_page=100&sort=full_name", paginate=True)


def commits_by_owner(full_name: str, branch: str, since: str = "", until: str = "") -> list[dict]:
    q = f"repos/{full_name}/commits?sha={urllib.parse.quote(branch, safe='')}&author={OWNER}&per_page=100"
    if since:
        q += f"&since={since}T00:00:00Z&until={until}T23:59:59Z"
    return [c for c in api(q, paginate=True) if (c.get("author") or {}).get("login") == OWNER]


def count_commits(full_name: str, branch: str) -> int:
    return len(api(f"repos/{full_name}/commits?sha={urllib.parse.quote(branch, safe='')}&per_page=100", paginate=True))


def count_prs(full_name: str) -> int:
    data = api(f"search/issues?q=repo:{full_name}+type:pr+author:{OWNER}")
    return int(data.get("total_count", 0)) if isinstance(data, dict) else 0


# --------------------------------------------------------------------------- classification

def relationship(repo: dict, my_commits: int, my_prs: int) -> str:
    if (repo.get("owner") or {}).get("login") == OWNER:
        return "owner"
    return "contributor" if (my_commits or my_prs) else "collaborator-access only"


def suggested_tier(repo: dict, rel: str, my_commits: int) -> str:
    name = repo["name"]
    if name == PROFILE_REPO:
        return "excluded: profile repository"
    if rel == "collaborator-access only":
        return "excluded: no verifiable contribution"
    if repo.get("fork"):
        return "excluded: fork"
    if int(repo.get("size") or 0) == 0 and not repo.get("language"):
        return "excluded: empty repository"
    if rel == "contributor":
        return "collaboration"
    low = name.lower()
    if any(h in low for h in COURSEWORK_HINTS):
        return "archive: coursework"
    if repo.get("archived"):
        return "archive: earlier work"
    return "candidate: product (curate in data/portfolio.json)" if my_commits >= 5 else "archive: tools & research"


# --------------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only repository inventory and footprint measurement")
    parser.add_argument("--out", default=DEFAULT_OUT, help="local, git-ignored output directory")
    parser.add_argument("--months", type=int, default=12)
    parser.add_argument("--write-footprint", action="store_true", help="update data/footprint.json aggregates")
    parser.add_argument("--footprint", default=os.path.join("data", "footprint.json"))
    args = parser.parse_args(argv)

    today = dt.date.today()
    since = (today - dt.timedelta(days=365 * args.months // 12)).isoformat()
    until = today.isoformat()

    try:
        repos = list_accessible_repos()
    except RuntimeError as exc:
        print(f"discover: {exc}", file=sys.stderr)
        return 1

    rows: list[dict] = []
    shas: set[str] = set()
    public_shas: set[str] = set()
    merges = 0
    per_repo: dict[str, int] = {}
    for r in sorted(repos, key=lambda x: x["full_name"].lower()):
        fn, branch = r["full_name"], r.get("default_branch") or "main"
        try:
            mine_all = commits_by_owner(fn, branch)
            total = count_commits(fn, branch) if mine_all else 0
            prs = count_prs(fn)
            window = commits_by_owner(fn, branch, since, until)
            langs = api(f"repos/{fn}/languages") or {}
        except RuntimeError as exc:
            print(f"discover: skipping {fn}: {exc}", file=sys.stderr)
            continue
        n = 0
        for c in window:
            if c["sha"] in shas:
                continue
            shas.add(c["sha"])
            n += 1
            merges += 1 if len(c.get("parents") or []) > 1 else 0
            if not r.get("private"):
                public_shas.add(c["sha"])
        if n:
            per_repo[fn] = n
        rel = relationship(r, len(mine_all), prs)
        rows.append({
            "repository": fn, "visibility": "private" if r.get("private") else "public",
            "owner": r["owner"]["login"], "relationship": rel, "archived": bool(r.get("archived")),
            "fork": bool(r.get("fork")), "default_branch": branch,
            "primary_languages": sorted(langs, key=langs.get, reverse=True)[:3],
            "latest_activity": (r.get("pushed_at") or "")[:10], "description": r.get("description") or "",
            "verified_contribution": {"default_branch_commits": len(mine_all), "total_commits": total, "pull_requests": prs},
            "public_display_safety": "public name ok" if not r.get("private") else "allowlisted display text only",
            "suggested_tier": suggested_tier(r, rel, len(mine_all)),
        })
        print(f"{fn:48} {rows[-1]['visibility']:7} {rel:26} commits={len(mine_all)}/{total} prs={prs}")

    owned = [r for r in repos if r["owner"]["login"] == OWNER]
    footprint = {
        "measured_on": until,
        "window": {"from": since, "to": until, "label": f"{dt.date.fromisoformat(since):%b %Y} – {today:%b %Y}"},
        "commits_12m": len(shas), "public": len(public_shas), "private": len(shas) - len(public_shas),
        "merge_commits": merges,
        "repos_contributed": len(per_repo),
        "repos_contributed_owned": sum(1 for k in per_repo if k.startswith(OWNER + "/")),
        "repos_contributed_collab": sum(1 for k in per_repo if not k.startswith(OWNER + "/")),
        "owned": len(owned), "owned_public": sum(1 for r in owned if not r.get("private")),
        "owned_private": sum(1 for r in owned if r.get("private")),
        "verified_collaborations": sum(1 for row in rows if row["relationship"] == "contributor"),
        "per_repository": per_repo,
    }
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "inventory.json"), "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=1, ensure_ascii=False)
    with open(os.path.join(args.out, "footprint.json"), "w", encoding="utf-8") as fh:
        json.dump(footprint, fh, indent=1)
    print(f"discover: {len(rows)} repositories inventoried → {args.out}/ (local only)")
    print(f"discover: {footprint['commits_12m']} commits ({footprint['public']} public · {footprint['private']} private), "
          f"{footprint['repos_contributed']} repositories, {footprint['owned']} owned, "
          f"{footprint['verified_collaborations']} verified collaborations")

    if args.write_footprint:
        with open(args.footprint, encoding="utf-8") as fh:
            data = json.load(fh)
        values = {
            "commits_12m": (footprint["commits_12m"], f"12 months · {footprint['public']} public · {footprint['private']} private"),
            "repos_contributed_12m": (footprint["repos_contributed"], f"12 months · {footprint['repos_contributed_owned']} owned · {footprint['repos_contributed_collab']} collaborative"),
            "owned_repos": (footprint["owned"], f"{footprint['owned_public']} public · {footprint['owned_private']} private"),
            "verified_collaborations": (footprint["verified_collaborations"], "commit / pull-request evidence only"),
        }
        for m in data["metrics"]:
            if m["key"] in values:
                m["value"], m["note"] = values[m["key"]]
        data["measured_on"] = until
        data["window"] = footprint["window"]
        with open(args.footprint, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        print(f"discover: aggregates written to {args.footprint} (no repository names)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
