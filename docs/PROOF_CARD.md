# Proof card measurement

`scripts/update_proof.py` updates only `data/footprint.json`, the proof section
of `README.md`, and the four existing `assets/v5/proof-*.svg` files. The visual
geometry, theme, and other profile assets stay the same.

## Method

- A rolling 365-day UTC interval `[start_utc, end_utc)` is written to
  `data/footprint.json` and explained in the README. The four card values use
  the same interval, except owned repositories, which is a snapshot at the
  measurement time.
- The repository universe is `/user/repos` for the authenticated profile owner:
  owned repositories plus accessible collaborator/organization repositories.
  The count describes **token-visible** data; it does not claim to include
  repositories the credential cannot see.
- `Commits authored` counts default-branch commit SHAs with GitHub's linked
  `author.login` equal to `Salihefendihsa`. Each SHA is counted once even if
  reachable in multiple repositories. Public/private is based on visible
  repository metadata; a SHA visible in both is public.
- `Repositories contributed to` counts distinct token-visible repositories
  with such a commit or a pull request authored in the interval. `Verified
  collaborations` is the partner-owned subset. Access alone is not proof.
- The profile repository is included in owned repositories, but excluded from
  commits and contributed repositories. Automated card commits cannot increase
  the card's own activity numbers. PRs provide repository evidence, not extra
  commits.
- The card is different from GitHub's contribution graph, whose eligibility
  and visibility rules differ. Its contribution total is never described here
  as a commit count.
- All REST pages are consumed. Any authentication, pagination, rate-limit, or
  API failure stops before files are written. When values and scope have not
  changed, the last valid date and period remain visible and no commit is made.

The `Code by language` sentence in the README is a separately dated
2026-09-22 snapshot; this workflow does not remeasure it.

## Actions credential

The daily workflow runs around **09:11 Europe/Istanbul** and also accepts
`workflow_dispatch`. It needs one repository Actions secret:

1. Create a **classic personal access token** for `Salihefendihsa` with the
   `repo` scope. Add `read:org` only if organization membership is needed to
   see relevant repositories. Authorize organization SSO where applicable.
2. In `Salihefendihsa/Salihefendihsa`, open **Settings → Secrets and variables
   → Actions → New repository secret**. Name it `PROFILE_STATS_TOKEN` and paste
   the token value there. Never put the token in the repository, a PR, or a log.
3. Run **Actions → Update proof card → Run workflow** once. Confirm the
   `refresh` job succeeds and either commits changed card values or prints
   `No metric change; no commit`.

The script verifies the authenticated login and classic PAT `repo` scope.
GitHub's default `GITHUB_TOKEN` is limited to this repository and is not a
substitute. Without `PROFILE_STATS_TOKEN`, the update job fails and leaves the
previous card intact. A newly restricted credential can only measure the
repositories it sees; compare its visibility with the intended coverage before
trusting a changed count. The workflow never publishes private repository names,
email addresses, tokens, or a per-repository breakdown.
