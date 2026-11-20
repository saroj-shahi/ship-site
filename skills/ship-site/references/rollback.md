# Rollback (production is broken after a release)

The goal is the last good build serving production, with proof, and git and the host left in a state where the next deploy doesn't silently undo the rollback. Every action that changes production, git remotes or the host is a ⏸. Diagnosis isn't.

## 1. Confirm and size it (no approval needed)

- `smoke_test.py <prod-url> --env production --json <run>/logs/smoke-production-broken.json`, plus the failing page in the browser (console, network). A report from the user is a symptom, not a diagnosis. Reproduce it.
- What changed: `git log <last-good-tag>..<prod-branch> --oneline`, and the host's deploy list (below). Also ask about, or check, changes that aren't in git: env vars or headers edited in the host console, a DNS or CDN change, a CMS publish, an expired API key, a third-party outage.
- Last good build: the previous tag (`git describe --tags --abbrev=0 <bad-tag>^`) and its deploy ID on the host.

Tell the user in three lines: what is broken and for whom, since when (which deploy), and the last good build.

## 2. Choose the route

| Situation | Route |
|---|---|
| Users are hit, the cause is in the new build, and the host keeps old builds | **Host rollback**: seconds, git untouched |
| Host can't roll back, or the release must leave git history too | **Revert**: `git revert` through the normal PR flow |
| The fix is one obvious line, already verified locally, and the breakage is cosmetic | **Fix forward** on `fix/*` through the release flow; no rollback |
| Cause is outside the build (console env var, DNS, third party, expired key, CMS content) | Neither: fix it where it lives. A code rollback won't help, so say so |

Recommend one route with the reason, and ask.

## 3. Host rollback, per host

Use only the section for the host step 0 detected. Each command or console action is a ⏸.

**Vercel.** `vercel ls --prod` (or the dashboard's Deployments) to find the last good production deployment, then `vercel rollback <deployment-url-or-id>` or Instant Rollback in the dashboard. After a rollback, Vercel stops auto-assigning the production domain to new deployments until you undo the rollback or promote one (`vercel promote <url>`). That's useful (the next push can't re-ship the bug) but easy to forget: put "undo rollback / promote the fixed deploy" in the plan. The Hobby plan can only roll back to the immediately previous production deployment.

**Netlify.** Deploys → the last good deploy → **Publish deploy** (or `netlify api restoreSiteDeploy --data '{"site_id":"<id>","deploy_id":"<id>"}'`). Publishing an older deploy locks auto-publishing, so new builds won't go live until someone starts auto-publishing again. Add that step to the plan.

**AWS Amplify.** Console → app → production branch → the last good build → **Redeploy this version**. With only the CLI, `aws amplify start-job --app-id <id> --branch-name <prod-branch> --job-type RELEASE --commit-id <good-sha>` rebuilds that commit. It's a full build, not an instant swap, so expect minutes. The next push to the branch deploys normally, so revert or fix forward in git before anyone pushes.

**Cloudflare Workers (OpenNext).** `npx wrangler deployments list` (or `npx wrangler versions list`) to find the last good version, then `npx wrangler rollback <version-id> --message "rollback vX.Y.Z"`. A rollback restores code and config, not data in bound resources (KV, D1, R2), and secrets changed since then stay changed. The next Workers Build from git redeploys the broken commit, so sync git before then.

**Firebase Hosting.** Console → Hosting → Release history → the last good release → **Rollback**. Previous releases can also be cloned to live with `firebase hosting:clone` (check `firebase hosting:clone --help` for the source syntax). The next `firebase deploy` replaces live again, so revert or fix forward in git first.

**GitHub Pages.** Re-run the deploy workflow on the last good commit (Actions → the run → Re-run), or revert in git and let the workflow redeploy. There is no instant swap; expect the length of a build.

**Unknown host or no access.** Use the revert route, or ask the user to roll back in their console and give them the exact build or commit to restore.

## 4. Revert route

1. From the production branch (pulled, clean): `git switch -c revert/vX.Y.Z` then `git revert -m 1 <merge-sha>`. For a squash-merge, drop `-m 1`. Reverting several releases: revert newest first.
2. Build gate (step 10) on the revert branch.
3. ⏸ push → ⏸ PR into the production branch (title `revert: vX.Y.Z <summary>`) → ⏸ merge.
4. **Staging branch too.** In a `dev → main` flow, the bad commits are still on `dev`, and the next promotion re-ships them. Bring the revert into `dev` (merge `main` back, or the same revert on `dev`, whichever the repo's history shows) as its own ⏸ push or PR.

## 5. Prove it, then record it

- Smoke production again: `smoke_test.py <prod-url> --env production --expect-build <restored-build-marker> --json <run>/logs/smoke-production.json`. Record `smoke-production` in `gates.json`. Open the page that was broken and check the console.
- `state.json`: `"rollback": {"from": "<bad version/sha>", "to": "<restored version/sha/deploy>", "route": "host|revert", "at": "<ISO time>", "unlock": "<what must be re-enabled, if anything>"}`.
- Plan follow-ups, as agent or owner items: the root-cause fix on `fix/*` through the full release flow (it ships as the next patch); re-syncing git or re-enabling auto-publish/auto-assign after a host rollback; a regression test (Playwright spec or smoke check) that would have caught it.
- Tags and releases: never delete the bad tag or GitHub release. Offer (⏸, it's public) to prepend "Rolled back on <date>, superseded by vX.Y.Z+1" to its release notes.

## What to tell the user

Three to five lines: what was broken, what is serving now (with the smoke result), what's locked or out of sync until the fix ships, and the next step with its ID in `plan.md`.
