#!/usr/bin/env python3
"""Refresh every GitHub-derived README block from one complete API snapshot."""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import sys
import urllib.parse

import generate_portfolio as portfolio_gen
import update_proof as proof
from render_assets import render_all, write_if_changed


def language_distribution(api: proof.GhApi, repos: list[dict]) -> list[dict]:
    totals: dict[str, int] = {}
    for repo in repos:
        if repo["owner"]["login"].casefold() != proof.OWNER.casefold():
            continue
        full = urllib.parse.quote(repo["full_name"], safe="/")
        data = api.get(f"repos/{full}/languages")
        if not isinstance(data, dict) or any(
            not isinstance(name, str) or not isinstance(size, int) or size < 0
            for name, size in data.items()
        ):
            raise proof.MeasurementError("GitHub language response is incomplete; profile preserved")
        for name, size in data.items():
            totals[name] = totals.get(name, 0) + size
    total = sum(totals.values())
    if not total:
        raise proof.MeasurementError("No owned repository language data is available; profile preserved")
    ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    shown = ranked[:6]
    rest = sum(size for _, size in ranked[6:])
    if rest:
        shown.append(("Other", rest))
    return [{"name": name, "share": round(100 * size / total, 1)} for name, size in shown]


def apply_collaboration_evidence(config: dict, repos: list[dict], evidence: dict[int, dict[str, int]]) -> dict:
    updated = copy.deepcopy(config)
    by_id = {repo["id"]: repo for repo in repos}
    used_ids: set[int] = set()
    for product in updated["products"]:
        if product.get("collaboration") is None:
            continue
        sources = [s for s in product["repository_sources"] if s["kind"] == "collaboration"]
        if not sources or any("repository_id" not in source for source in sources):
            raise proof.MeasurementError("A collaboration lacks a configured repository ID; profile preserved")
        commits = prs = 0
        visibilities: set[str] = set()
        for source in sources:
            repo_id = source["repository_id"]
            if repo_id in used_ids:
                raise proof.MeasurementError("A collaboration repository is assigned twice; profile preserved")
            used_ids.add(repo_id)
            repo = by_id.get(repo_id)
            if repo is None or repo["owner"]["login"].casefold() == proof.OWNER.casefold():
                raise proof.MeasurementError("A partner repository is inaccessible or has changed ownership; profile preserved")
            visibilities.add("private" if repo["private"] else "public")
            item = evidence.get(repo_id)
            if item is None:
                raise proof.MeasurementError("Partner contribution evidence is unavailable; profile preserved")
            commits += item["commits"]
            prs += item["prs"]
        product["access"] = "Partner-owned · " + (next(iter(visibilities)) if len(visibilities) == 1 else "mixed visibility")
        if commits or prs:
            product["collaboration"]["evidence"] = f"{commits} authored commits · {prs} PRs (12m)"
            product["collaboration"]["visual_evidence"] = f"{commits} commits · {prs} PRs"
        else:
            # The curated product remains in the archive and ecosystem; it is
            # no longer described as a verified current-window collaboration.
            product["collaboration"] = None
    return updated


def build_outputs(api: proof.GhApi, end: dt.datetime, readme: str, old: dict,
                  config: dict) -> dict[str, str]:
    calendar = proof.measure_calendar(api, end)
    repos = api.pages("user/repos?affiliation=owner,collaborator,organization_member&sort=full_name")
    evidence: dict[int, dict[str, int]] = {}
    measured = proof.measure(api, end, repos=repos, evidence=evidence)
    measured.update(calendar)
    languages = language_distribution(api, repos)
    curated = apply_collaboration_evidence(config, repos, evidence)
    products, archive = portfolio_gen.build(repos, curated)
    groups = portfolio_gen.archive_groups(curated)
    portfolio_block = portfolio_gen.render_portfolio_block(products)
    archive_block = portfolio_gen.render_archive_block(archive, groups, products)
    # The fingerprint contains only rendered public-safe output. A moving
    # clock alone does not change it, so daily no-op runs create no commit.
    measured["profile_fingerprint"] = hashlib.sha256(
        (portfolio_block + "\n" + archive_block).encode("utf-8")
    ).hexdigest()
    footprint, proof_readme, _, _ = proof.prepare(old, measured, readme, languages=languages)
    footprint["collaboration_evidence"] = {
        product["product_id"]: product["collaboration"]
        for product in curated["products"]
        if any(source["kind"] == "collaboration" for source in product["repository_sources"])
    }
    updated = portfolio_gen.update_readme_text(proof_readme, products, archive, groups)
    listed = {str(r.get("name", "")).lower() for r in repos if portfolio_gen.is_listed(r, curated)}
    portfolio_gen.check_generated_text(updated, curated, listed)
    result = {
        "README.md": updated,
        "data/footprint.json": json.dumps(footprint, indent=2, ensure_ascii=False) + "\n",
        "generated/portfolio.md": portfolio_block + "\n",
        "generated/project-archive.md": archive_block + "\n",
    }
    result.update(render_all(footprint, curated))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ci", action="store_true")
    args = parser.parse_args(argv)
    try:
        api = proof.GhApi(require_secret=args.ci)
        api.preflight(require_repo_scope=args.ci)
        readme = (proof.ROOT / "README.md").read_text(encoding="utf-8")
        old = json.loads((proof.ROOT / "data/footprint.json").read_text(encoding="utf-8"))
        config = portfolio_gen.load_portfolio(str(proof.ROOT / "data/portfolio.json"))
        outputs = build_outputs(api, dt.datetime.now(proof.UTC), readme, old, config)
        changed = [path for path, content in outputs.items()
                   if write_if_changed(str(proof.ROOT / path), content)]
        print(f"profile: {len(changed)} generated file(s) updated" if changed else "profile: data unchanged; no commit needed")
        return 0
    except (proof.MeasurementError, portfolio_gen.PortfolioError) as exc:
        # These errors are either generic or refer only to already public
        # curated content. Never print raw API responses or private names.
        print(f"profile: {exc}", file=sys.stderr)
        return 1
    except (OSError, KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"profile: validation failed ({exc.__class__.__name__}); existing profile preserved", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
