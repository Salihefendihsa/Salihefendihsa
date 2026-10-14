# Dynamic profile data

`scripts/update_profile.py` is the only scheduled README writer. One owner
credential supplies a complete paginated repository list. The same run then
measures default-branch authored commits, authored PRs, repository languages,
and public repository metadata. It renders the README's proof, portfolio, and
archive blocks plus their linked SVGs before writing any file. API, permission,
rate-limit, or validation failure leaves the published files unchanged.

## Automatically generated

- The proof card and its `How these numbers are measured` block: the selected
  calendar year's `contributionCalendar.totalContributions` from GitHub
  GraphQL, alongside distinct rolling-365-day authored-commit,
  contributed-repository, owned-repository, and evidenced collaboration
  measures. A contribution total is never labelled a commit count. The card
  shows both periods, scope, and the last published successful measurement.
- The marked `PORTFOLIO` and `ARCHIVE` README blocks, their generated Markdown
  copies, and the ecosystem/collaboration SVGs. Public repository links are
  shown only when `data/portfolio.json` permits them and the API confirms the
  repository is public. Uncurated public archive descriptions, language and
  archived state come from the API. Curated descriptions remain editorial.
- Partner product evidence is computed from configured opaque repository IDs:
  authored commits and PRs in the same 365-day interval. A product with no
  current-window evidence remains in the archive but leaves the verified
  collaboration board. No private repository name or URL is published.
- Product and archive counts are computed from the rendered collection.

`data/portfolio.json` is the single selection and visibility configuration:
product groups, public repository sources, excluded repositories, archive
overrides, and allowed private archive descriptions. It contains only opaque
IDs for partner repositories. The profile repository is included in the owned
snapshot but excluded from activity metrics, so the workflow cannot raise its
own card numbers.

Names, biography, product vision, manually checked delivery status, detailed
technical descriptions, the hero and engineering-method artwork remain
editorial. Repository activity never implies delivery, deployment, security,
or production readiness. Stars, forks, last activity, and CI badges are not
displayed; no stale status is implied. GitHub renders the generated Markdown
and committed SVGs directly.

The first metric uses the full UTC calendar year, January 1 through December
31, explicitly requested in GraphQL; it includes whatever contribution types
and private-activity visibility GitHub returns. URL `from`/`to` filters on a
profile page do not flow into an embedded README image. The other activity
metrics use a rolling 365-day UTC interval `[start_utc, end_utc)`.
Default-branch commits require GitHub's linked `author.login` to
match the profile owner; each SHA is globally deduplicated. An authored PR is
repository-level evidence, never an extra commit. The language distribution is
GitHub's language-byte count across credential-visible owned repositories.
The public/private classification comes only from repositories the credential
can see. The published measurement time advances only when the values or
rendered dynamic content change. Successful no-op runs are visible in Actions
history; the static card does not imply instant synchronization.

## Actions credential and verification

The workflow runs **hourly, around minute 11 Europe/Istanbul**, and supports manual
`workflow_dispatch`. It needs the repository Actions secret
`PROFILE_STATS_TOKEN`: a classic personal access token issued to
`Salihefendihsa` with the `repo` scope. Add `read:org` if organization
membership is needed, and authorize organization SSO where applicable.
The classic token scope is broad; keep its lifetime short. GitHub's default
`GITHUB_TOKEN` is limited to this profile repository and cannot be treated as
access to the owner's other private repositories.

Add the token at **Settings → Secrets and variables → Actions → New repository
secret**. Never put its value in a PR, local file, or log. Then run **Actions →
Update dynamic profile → Run workflow** and confirm both `verify` and `refresh`
jobs pass. `refresh` either commits changed generated files or reports a no-op.
Without the secret, it fails before writing; a restricted credential measures
only what it can see, which is explicitly labelled as token-visible scope.
