---
name: ship-site
description: Release-readiness orchestrator for Next.js marketing sites — takes a site from "feature done" to "released in production" as one checkpointed pipeline. Runs knowledge-base sync, design/code/security/SEO/analytics/a11y/perf audits, launch-content and replatform checks, real-browser verification, Playwright, the lint/format/build gate, the conventional-commit → staging → release PR → tag flow, and post-deploy smoke tests, then writes a go/no-go report and an ordered launch plan. Use whenever the user says "ship it", "release readiness", "pre-launch check", "launch checklist", "is this ready to deploy", "what's left before launch", "deploy to prod", "cut a release", "promote dev to main", "smoke test staging/prod", "replace the live site", "continue the release", or invokes ship-site, even for one slice ("just smoke test the live site"). Not for single-topic tasks like "fix this CSS bug".
---

# ship-site

One pipeline that replaces the hand-run sequence: knowledge base → audits → browser proof → tests → build gate → release → smoke test. Orchestrate; don't re-implement what an installed skill already does. Stack-specific checklists live in `references/`, deterministic checks in `scripts/`.

**`SKILL_DIR`** below means the directory containing this file. It differs per agent and install (`~/.agents/skills/ship-site`, `~/.claude/skills/ship-site`, `.cursor/skills/ship-site`, `.github/skills/ship-site`, a plugin cache path…), so resolve it once from where you loaded this file and use the absolute path in every command.

## Host notes

This is a portable Agent Skill. It runs in Claude Code, Codex, Gemini CLI, Cursor, GitHub Copilot, OpenCode and other agents that load `SKILL.md`. Where hosts differ:

- **Invocation.** Modes are written `/ship-site <mode>` below. Hosts without that slash command select the mode from the words: "ship-site audit", "run ship-site in release mode", or a mention such as `$ship-site smoke`.
- **Project instructions.** "The repo's instructions" means whichever of these exist: `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.cursor/rules/`, `.github/copilot-instructions.md`, plus `docs/`. Read all of them, whichever agent you are.
- **Approvals (⏸).** If the host can pause for the user's answer, ask. If it can't (non-interactive or `exec` mode, CI), stop at the first ⏸, finish the report, and end with the exact pending command and its evidence. A missing answer is never a yes.
- **Delegation.** "Subagent" means whatever the host offers for parallel delegated work. With none, run the audits in sequence yourself.
- **Companion skills** are named by role (code review, security review, design audit). Use whichever the host has installed, and fall back to the reference files when there are none.
- **Run folder.** Use a host-provided scratch directory if there is one, else `./.ship-site/`.

## Modes

Parse the first argument:

| Invocation | Runs | Writes code? | Outward-facing? |
|---|---|---|---|
| `/ship-site audit` | Steps 0–10, read-only report + plan | No | No |
| `/ship-site fix` | `audit`, then work the plan, re-verify | Yes (local only) | No |
| `/ship-site release [patch\|minor\|major]` | Steps 0, 10–12 | Version bump | Yes — every step gated |
| `/ship-site smoke [url]` | Step 12 only | No | No |
| `/ship-site resume` | Continue the latest unfinished run from its `state.json` | As the original mode | As the original mode |
| `/ship-site` (no arg) | Everything, pausing before anything outward-facing | Yes | Yes — gated |

Natural-language requests map the same way: "pre-launch check" / "what's left before launch" / "give me a launch plan" → `audit`; "ship it" / "deploy to prod" → no-arg full run; "smoke test staging" → `smoke` with the staging URL from the repo's instructions/docs; "release a patch" → `release patch`; "continue the release" / "where were we" after a cut-off → `resume`. `smoke` with no URL: take staging/production URLs from the repo docs, and ask only if none are written down. Don't open with scoping questions — the user wants you measuring. Start, and bring a plan.

## Hard rules (each one exists because it broke a real release)

- **Stop and ask** before: `git push`, PR creation, PR merge, version bump, git tag, `gh release`, and any real form submission that reaches a human inbox. One approval covers one action — a yes to "push the branch" is not a yes to "open the PR". Batch the question with the evidence the user needs to decide (diff stat, test result, target branch).
- Never force-push on your own initiative. The one exception is the user asking you to push their own feature branch after a rebase: `--force-with-lease`, never on a shared or base branch. Never delete a published tag or release.
- Never invent content to clear a finding: no made-up copy, bios, metrics, certifications, badges or legal text. Remove it, or list it for the owner to supply. A claim you can't trace to the repo or the content doc is reported, not "fixed". Never commit `next-env.d.ts`, a lockfile for a package manager the repo doesn't use, `.env*`, or run artifacts. Check `git status` before every commit and stage files by name.
- Every "fixed" or "passes" claim needs evidence in the report: a screenshot path, test output, or build log excerpt. If you couldn't verify, say "unverified" — don't round up.
- The repo's own instructions file's (AGENTS.md, CLAUDE.md, …) **Don'ts** and **Known inconsistencies** (or equivalent sections in `docs/`) are rules. A known inconsistency is reported as "known, pre-existing" rather than as a new Blocker, and you don't fix it incidentally in `fix` mode without flagging that you did.
- `audit` and `smoke` never modify tracked files. If you must change something to run a check (a test port, a launch config), say so and revert it, or do it in a throwaway clone.

## Step 0 — Read the repo (always, every mode)

1. **Applicability.** Confirm `next` is in package.json and find the app dir (`src/app` or `app`). Pages Router only, or not Next.js at all: say so in one line, skip the Next-specific checks (metadata API, `next.config` CSP, `next-env.d.ts`), and run the rest — the build gate, browser, a11y, release and smoke steps are framework-neutral.
2. Read the project instructions files (see Host notes), `README.md` and every file in `docs/` that exist. Extract: Don'ts, Known inconsistencies, production/staging URLs, base branch, release commands, and the **working rules** (who pushes, whether to branch, commit straight to main or not, folders not to touch). Those rules, and any the user states in this conversation, override the default flow in `references/release.md`.
3. Package manager: `packageManager` field in package.json wins; else lockfile (`yarn.lock` → yarn, `pnpm-lock.yaml` → pnpm, `bun.lock`/`bun.lockb` → bun, `package-lock.json` → npm). Use `<pm>` for every command below. A second lockfile for another manager (a stale `package-lock.json` in a pnpm repo is typical after a switch) is a Should-fix: CI and the host may install from the wrong one.
4. Host: `amplify.yml` → AWS Amplify, `vercel.json` or `.vercel/` → Vercel, `netlify.toml` → Netlify, `wrangler.toml`/`wrangler.jsonc`/`open-next.config.ts` → Cloudflare Workers (OpenNext). Read only the matching section of `references/hosting.md`. Several host configs present → the project moved hosts; ask which one is live and treat the others as stale.
5. Git host and branches: `git remote get-url origin` → GitHub / Bitbucket / other, which decides how PRs and CI are checked (`references/release.md` § Git host; no `gh` on Bitbucket). Base = `dev` (or `develop`/`staging`) if it exists, else the default branch. `git fetch` first and say if the local base is behind its remote. Diff with `git diff <base>...HEAD --stat`.
6. Routes: `find src/app app \( -name 'page.tsx' -o -name 'page.ts' -o -name 'page.jsx' -o -name 'page.js' -o -name 'page.mdx' \) 2>/dev/null`. Drop route groups `(x)` and private `_x` folders from the URL; expand dynamic segments from `generateStaticParams` / data files.
7. Sanity-check the environment before trusting a red result: `node_modules` missing → install first (ask if it's a large download); `node_modules` symlinked outside the repo → Turbopack refuses to build, which is an environment problem, not a project Blocker (build in a clone, or report "could not run"). If Playwright's `baseURL` hardcodes a port you can't use, expect crawl failures that aren't real.
8. **Replatform?** If the docs or the user say this site replaces a live one (a rebuild taking over an existing domain, a WordPress cutover), note the old host and the old sitemap URL. Steps 1b, 5 and 12 then add the checks in `references/migration.md`.
9. Run folder: the session scratchpad if you have one, else `./.ship-site/<timestamp>/` — and add `.ship-site/` to `.git/info/exclude` so it can never be committed. Subfolders `screenshots/`, `logs/`, `findings/`. Write `state.json` there now (see [Checkpoints](#checkpoints-and-resume)). If an earlier run folder for this repo has a `findings.json`, note its path: the report compares against it.

Tell the user in two lines what you detected (pm, host, git host, base branch, N routes, diff size, replatform or not, which companion skills are available) and which mode you're running. Then go.

## Step 1 — Knowledge base

Check an instructions file (AGENTS.md or the host's equivalent) and the repo's docs exist and cover architecture, design tokens, content, and conventions (the names vary — `docs/ARCHITECTURE.md`, `DESIGN.md`, etc.). Missing coverage → `audit` reports it (Should-fix); `fix` drafts a missing instructions file (the host's own init command if it has one, e.g. `/init`; else write `AGENTS.md`, which most agents read) and missing docs from code. For existing docs, diff their claims against the code the branch touched (file paths, route lists, token names, commands) and list the stale ones with file:line. Also diff the stack claims against step 0: host, package manager, git host, branch names, CI. Projects switch these mid-flight (Vercel → Cloudflare → Amplify, npm → pnpm, GitHub → Bitbucket) and the docs lag. Patch stale lines — don't rewrite docs wholesale. If the repo is being handed to a client or another team, also run the hygiene check in `references/launch-essentials.md` §7.

## Step 1b — Launch essentials

Run `scripts/launch_content.py <repo>` (add `--legacy-host <old-host>` on a replatform) and work through `references/launch-essentials.md`: placeholder and unconfirmed content, favicon/app icons, OG image freshness, 404/error/global-error pages, form consent and privacy notice, external and legacy links, image fit and orphaned words. These are the checks clients notice on day one and no build tool catches. Do this yourself, not in a subagent: triage needs the rendered pages from step 8.

## Steps 2–7 — Parallel audits

Launch these as **parallel subagents in a single message**. Each gets: the repo path, base branch, route list, the Don'ts/Known-inconsistencies from step 0, the absolute path of its reference file, the dev-server URL if it needs one, and the instruction to return findings JSON in the schema from `references/report-format.md` (including `owner`, `effort` and `verify` per finding, and `not_checked` for anything it couldn't reach). Save each agent's JSON as `<run>/findings/<area>.json` as it arrives. Each subagent is read-only — it reports, it doesn't edit.

| Agent | Scope | Primary method | Fallback if the skill isn't installed |
|---|---|---|---|
| design | Step 2 — typography, spacing, hierarchy, motion, `prefers-reduced-motion`, touch targets ≥44px, dark mode if supported | a design-audit skill (e.g. `impeccable`, `web-design-guidelines`) | Review screenshots from step 8 and the components on the diff against the repo's design docs/tokens |
| code | Step 3 — correctness on the diff vs base, then reuse/simplification | `code-review` on the diff, then `simplify` framed as report-only | Read the diff file by file: logic errors, unhandled states, dead code, duplicated utilities |
| security | Step 4 — generic review + stack checks | `security-review` + `references/security.md` + `scripts/csp_hosts.py` | `references/security.md` alone covers the stack-specific checks |
| seo-analytics | Steps 5–6 (+ 5b replatform parity when step 0 found one) | `references/seo.md` + `references/analytics.md` (+ `references/migration.md`) | — |
| a11y-perf | Step 7 — axe wcag2a/2aa per route, contrast, CWV, media | `references/a11y-perf.md` | — |

If you can't spawn subagents, run the same audits sequentially yourself — same scope, same JSON output.

Only the design and a11y-perf agents need a running server: start it yourself first (step 8) and pass them the URL so two agents don't race to start servers. While they run, do step 8 yourself — a shared browser can't be driven by several agents at once.

## Step 8 — Browser verification (you, not a subagent)

Follow `references/browser.md`. In short: start the dev server; visit every route at desktop (1440) and mobile (375) widths; read console and network after each for CSP violations, 404s, hydration errors; exercise the main form end to end; screenshot each route at both widths into the run folder.

Use whichever browser tooling the session has, in this order: a built-in preview/browser pane, a browser MCP (Chrome DevTools, Playwright MCP), then a throwaway Playwright script run with `npx playwright` from the run folder. If none can run, say "browser verification not performed" in the report — never infer rendered behaviour from source.

## Step 9 — Test suite

Run the repo's Playwright suite (`npx playwright test`, all configured projects). Save the summary line and any failures to `logs/playwright.log`, and record the result in `<run>/gates.json` (schema in `references/report-format.md`). No Playwright config or no specs → `audit` reports Should-fix; `fix` scaffolds `tests/deployment-verification.spec.ts` from `references/playwright-scaffold.md` and runs it. Also run the repo's unit tests if a `test` script exists.

A failure that passes on retry is reported as flaky, not as a pass.

## Step 10 — Build gate

If the repo has an aggregate script (`ci`, `verify`, `check`), run that: it's what the repo's own CI runs. Otherwise run in order: `<pm> lint`, `<pm> format:check` (or `npx prettier --check .` if the script is missing and Prettier is configured), a typecheck if there's a script for it, then `<pm> build`. Save the tail of each log to `logs/`. Also run the host-specific build when it differs from `next build` (e.g. `opennextjs-cloudflare build`), since that's the one that fails in deploy. A missing script is reported, not invented (record it as `not-run` in `gates.json`). Any non-zero exit is a Blocker and a `fail` gate. `next build` rewrites `next-env.d.ts` — make sure it's still unstaged afterwards.

`next dev` and `next build` share `.next/`. If a dev server is running from this checkout (yours from step 8, or the user's), build in a scratch worktree (`git worktree add <run>/build HEAD`) instead of stopping their server, and remove the worktree afterwards. If the repo runs Lighthouse CI (`lighthouserc.*`), run it after the build and report scores against its budgets.

## Report and plan

Write your own step 1/1b/8 findings to `<run>/findings/<area>.json` (`knowledge-base`, `launch-content`, `browser`) in the same schema, and every gate (lint, format, typecheck, build, host build, Playwright, unit tests, smoke) to `<run>/gates.json`. Then build both documents in one go:

```bash
python3 "$SKILL_DIR/scripts/build_report.py" <run> [--previous <earlier-run>] [--summary "<one sentence>"]
```

It dedupes (same file:line + same title → one finding, highest severity, all sources listed), assigns IDs (`B1`, `S2`, `N3`, `K1` for known pre-existing) that stay stable when you re-run it in the same folder, and computes the verdict:

- **NO-GO** — any open Blocker, or any gate `fail`.
- **GO pending** — no open Blocker, but a gate is `not-run`/`flaky`, or a Blocker fix is `could-not-verify`.
- **GO** — zero open Blockers and every recorded gate passed.

It writes `report.md` (verdict, counts, findings, what passed, **what was not checked**, evidence index, and new/resolved/still-open with `--previous`), `plan.md`, and the merged `findings.json`. A standard audit area with no findings file is listed as "not run" — never treat a missing file as clean.

Severity, owner and effort are your calls, so get them right before running it:

- **Blocker** — ships broken, insecure, deindexed, or illegal (a11y AA fail on a primary flow, failed build, secret exposure, missing CSP host that breaks a feature, og:image missing, staging indexable, production noindexed, form doesn't reach backend). **Should-fix** — real defect with limited blast radius. **Nice-to-have** — polish.
- **owner**: `agent` if you can fix it from the repo; `owner` if it needs content, credentials, assets or access only the site owner has; `decision` if there are two valid fixes and the choice isn't yours. Don't mark something `agent` that you'd have to invent content to close.
- **effort**: `S` under ~15 min, `M` under ~2 h, `L` more. **verify**: the exact command, test or page check that proves it's fixed.

Every finding needs `file:line`, what's wrong, a concrete fix (code-level, not "consider improving"), and evidence. Format and full schema: `references/report-format.md`.

**The plan** (`plan.md`) is the ordered route to GO: required items the agent can fix (cheapest first), required items waiting on the owner, recommended Should-fixes, one "owner inputs" list to forward to the client, the gates to re-run, the release steps from `state.json` (`release.steps`, each ⏸ marked), and a post-launch backlog. In release and no-arg runs, write the concrete release steps for *this* repo (from step 0's workflow rules and `references/release.md`) into `state.json` before building, so the plan shows the real branch names and commands.

Read both files once before presenting them: fix a wrong severity or owner in the findings JSON and re-run rather than hand-editing the output. Then tell the user the verdict, the path to GO, the top plan items, and what you need from them, with the paths to `report.md` and `plan.md`. If a version is known and the repo keeps release notes (e.g. `docs/release-notes/`), offer to save a copy there — don't write into the repo unasked.

## `fix` mode

After the audit report, work through `plan.md` in order: section 1 (Blockers the agent can fix), then Should-fixes. Skip Nice-to-haves unless trivial, and never close an `owner` item by inventing content. For each fix: edit, run its `verify` check (the script, the axe run, the browser page, the test), then set `status` (`fixed` / `skipped` / `could-not-verify`) and `fix_evidence` on that finding in its `findings/<area>.json`. Commit locally with conventional commits (see `references/release.md`); don't push. Then re-run steps 9 and 10 in full, update `gates.json`, and re-run `build_report.py`: the same IDs come back with their outcomes, the plan's boxes are ticked, and the verdict is recomputed.

## Step 11 — Release (`release` mode and no-arg run)

Follow `references/release.md` and the host section of `references/hosting.md`. Shape of the flow (each ⏸ is a stop-and-ask):

1. Build gate (step 10) must be green on the current branch.
2. Feature branch → ⏸ push → ⏸ PR into the staging branch. Wait for the staging deploy, then run step 12 against staging — including a **real** form submission (⏸ if it reaches a human), since a mocked submission can't catch a backend 403.
3. On the staging branch: ⏸ `<pm> release:<level>` → commit `chore(release): vX.Y.Z` → ⏸ push.
4. ⏸ PR staging → production branch. ⏸ merge (or the user merges).
5. After the production deploy: ⏸ `<pm> release:publish` (tag + `gh release create --generate-notes`).
6. Step 12 against production.

Repos without a staging branch (e.g. Vercel preview-per-PR) skip step 3's separate branch: bump on the feature branch or after merge, per `references/release.md`. If the repo lacks `release:*` scripts, propose the equivalent commands (`npm version <level> --no-git-tag-version`, `git tag`, `gh release create`) and ask before each.

## Step 12 — Smoke test

```bash
python3 "$SKILL_DIR/scripts/smoke_test.py" <base-url> --env <staging|production> \
  [--routes /,/about,...] [--expect-build <sha>] [--canonical-host <prod-host>] \
  [--json <run>/logs/smoke-<env>.json] [--legacy-urls <old-sitemap-url|file>]
```

It checks status codes, `og:image`/`twitter:image` (and that the image resolves), robots meta + robots.txt per environment, canonical host, unknown-path 404, http→https redirect, first-party static assets, CSP and security headers, and exits non-zero on any failure. On staging pass `--canonical-host` with the production host. Pass `--expect-build` with a string unique to the new deploy (the commit SHA when `generateBuildId` uses it) to prove it's live rather than inferring it. Sites behind basic auth: pass `--header "Authorization: Basic …"` with credentials the user supplies — never commit or echo them. On a replatform, pass `--legacy-urls` with the old site's sitemap: every old URL must reach a 200 on the new site, and redirecting to the home page fails.

Then, in the browser, open the home page and the form page and read the console for CSP/JS errors. On staging, submit the real form (ask first if it notifies a human inbox — it's a message sent on the user's behalf). Report the script output verbatim, and record it in `gates.json` as `smoke-<env>` (`pass` on exit 0, `fail` on 1, `not-run` with the reason on 2).

## Checkpoints and resume

Runs get cut off: usage limits, context resets, a deploy that takes an hour. Keep `<run>/state.json` current so the next session can pick up without redoing work or re-asking approvals it already used:

```json
{"mode": "release", "level": "patch", "repo": "/abs/path", "base": "develop", "head_sha": "abc1234",
 "steps": {"0": "done", "1": "done", "1b": "done", "2-7": "done", "8": "done", "9": "done", "10": "done", "11": "in_progress"},
 "release": {"pushed": true, "pr": "https://…/pull/12", "merged": false, "version": "1.4.1", "tagged": false,
             "steps": [{"step": "Push feat/launch", "command": "git push -u origin feat/launch", "approval": true, "done": true},
                       {"step": "PR into develop", "command": "gh pr create --base develop", "approval": true, "done": false}]},
 "report": "<run>/report.md", "plan": "<run>/plan.md", "next": "wait for the staging deploy, then step 12 on staging"}
```

Update it after every step and every outward-facing action (tick `release.steps[].done`, then re-run `build_report.py` so `plan.md` matches). On `/ship-site resume` (or "continue the release", "what's remaining"), find the newest run folder with an unfinished `state.json`. Re-check what may have changed since (`git fetch`, PR state, whether the tag exists, `head_sha` vs `HEAD`), say in two lines where things stand (the unticked items in `plan.md` are the remaining work), then continue from `next`. Approvals are not carried over: a ⏸ that wasn't executed before the cut-off is asked again. If `HEAD` moved, re-run the build gate before any release step.

## Scripts (Python 3.9+, stdlib only)

- `scripts/build_report.py <run> [--previous <run>] [--summary ...] [--json]` — merges `findings/*.json` and `gates.json` into `report.md`, `plan.md` and `findings.json` with stable IDs and a computed verdict. Exit 0 GO, 1 NO-GO or GO pending, 2 bad input.
- `scripts/smoke_test.py <url> --env staging|production [...]` — HTTP-level smoke checks; human output plus optional JSON. `--legacy-urls` checks a replaced site's URLs resolve on the new one. Exit 0 pass, 1 check failed, 2 site unreachable. `--help` lists every flag.
- `scripts/launch_content.py [repo] [--legacy-host old.example.com] [--json]` — placeholder and unconfirmed copy, create-next-app leftovers, and links back to the old site or `/wp-content/`. Every hit is a candidate to confirm on the rendered page. Exit 0 clean, 1 findings.
- `scripts/csp_hosts.py [repo] [--config next.config.ts] [--json]` — extracts every external host referenced in client code and diffs it against the CSP in the Next config. Missing hosts are likely Blockers; unused allowlisted hosts are Nice-to-have cleanups. Exit 0 clean, 1 missing hosts, 2 no config/CSP found.

## Reference files (read when you reach the step)

- `references/launch-essentials.md` — unfinished content, icons/OG, error pages, form consent, links, handover hygiene
- `references/migration.md` — replatform parity: URL inventory and redirects, carried-over SEO fields, hotlinks, cutover
- `references/security.md` — CSP, `NEXT_PUBLIC_` secrets, headers, form hardening, server-only imports
- `references/seo.md` — metadata, OG/Twitter shallow-merge trap, sitemap/robots, JSON-LD, headings, alt text
- `references/analytics.md` — GA4, consent mode, `trackEvent()` wrapper, CSP hosts
- `references/a11y-perf.md` — axe, contrast, keyboard, reduced motion, CWV, images, video
- `references/browser.md` — the click-through protocol and what to look for
- `references/playwright-scaffold.md` — spec template when a repo has no suite
- `references/release.md` — commit conventions, branch flow, checkpoints
- `references/hosting.md` — Amplify / Vercel / Netlify / Cloudflare Workers differences
- `references/report-format.md` — findings and gates JSON schema, report and plan layout
