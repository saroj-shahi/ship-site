# Release flow (step 11)

## Conventional commits

`<type>(<scope>): <imperative summary>` — types: `feat`, `fix`, `chore`, `docs`, `refactor` (plus `perf`, `test`, `style` if the repo history uses them). Scope = area (`seo`, `csp`, `analytics`, `contact`, `a11y`, `ui`, `release`). Check `git log --oneline -20` and match the repo's existing style. Body explains *why*. Release commit is exactly `chore(release): vX.Y.Z`.

Before every commit:
```bash
git status --short
```
Unstage `next-env.d.ts`, `package-lock.json` (in a yarn/pnpm repo), `.env*`, `test-results/`, `playwright-report/`, `.next/`. Stage files by name, not `git add -A`.

## Branch flow (dev = staging, main = production)

The names are the common convention; use the repo's actual staging and production branches from step 0. No staging branch? See [Without a staging branch](#without-a-staging-branch).

```
feature/*  ──PR──▶  dev  (auto-deploys staging)  ──PR──▶  main  (auto-deploys production)
```

Each ⏸ = stop, show the evidence, ask for an explicit yes for *that* action.

1. **Gate**: `<pm> lint && <pm> format:check && <pm> build` green on the feature branch. Playwright green.
2. ⏸ `git push -u origin <feature-branch>` (never `--force`; if rejected, fetch and rebase/merge, then ask again).
3. ⏸ `gh pr create --base dev --title "<conventional title>" --body "<summary + test evidence>"`.
4. After merge into `dev`, wait for the staging deploy (see hosting.md for how to check). Run step 12 against staging including the real form submission.
5. On `dev` (pulled, clean):
   - Check there is something to promote: `git diff main dev --stat`. If empty (features already reached `main` without a version bump), say so — the release is then just a version/tag for what's live, and the `dev → main` PR contains only the version line. Proceed only if the user still wants that.
   - Pick level: `patch` = fixes only; `minor` = new features/pages; `major` = breaking URL/IA changes. Derive from commits since the last tag (`git log $(git describe --tags --abbrev=0)..HEAD --oneline`) and propose it. If the user asked for `patch` but there are `feat:` commits, point out the mismatch with the evidence and let them choose — don't silently override either way.
   - ⏸ `<pm> release:<level>` (bumps package.json only, no tag).
   - Commit `chore(release): vX.Y.Z` (package.json only — if the bump touched a lockfile the repo doesn't use, discard it).
   - ⏸ `git push origin dev`.
6. ⏸ `gh pr create --base main --head dev --title "chore(release): vX.Y.Z" --body "<release notes draft>"`.
7. ⏸ Merge (`gh pr merge --merge` — match the repo's history: merge commits vs squash). Or let the user merge in the UI.
8. Wait for the production deploy. ⏸ `<pm> release:publish` (tags `vX.Y.Z`, pushes the tag, `gh release create --generate-notes`). If there's no such script: `git tag vX.Y.Z <main-sha> && git push origin vX.Y.Z && gh release create vX.Y.Z --title vX.Y.Z --generate-notes` — each an approval.
9. Step 12 against production.

## Without a staging branch

Preview-per-PR hosts (Vercel, Netlify deploy previews) often run feature → `main` directly:

1. Gate green → ⏸ push → ⏸ PR into `main`. Run step 12 against the PR's preview URL (with `--env staging` — previews must be noindex too).
2. ⏸ Version bump: on the feature branch before merge, or as its own `chore(release): vX.Y.Z` PR afterwards — follow what `git log` shows the repo doing.
3. ⏸ Merge. After the production deploy, ⏸ tag + `gh release create`, then step 12 against production.

## If something fails mid-release

Stop. Don't try to "finish" by skipping a gate. Report the state precisely (which branch has which commit, whether the tag exists, whether prod deployed) and the options: fix-forward on a `fix/*` branch through the same flow, or revert the merge PR. Never delete a published tag/release without explicit instruction.

## Release notes

Group commits since the last tag by type (Features / Fixes / Chores). Link PRs. Include the smoke-test result for staging and production. This doubles as `docs/release-notes/vX.Y.Z.md` if the user chose that location.
