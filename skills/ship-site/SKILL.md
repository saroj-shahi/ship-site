---
name: ship-site
description: Release-readiness orchestrator for Next.js marketing sites — takes a site from "feature done" to "released in production" as one checkpointed pipeline. Runs knowledge-base sync, design/code/security/SEO/analytics/a11y/perf audits in parallel, real-browser verification, Playwright, the lint/format/build gate, the conventional-commit → staging → release PR → tag flow, and post-deploy smoke tests, then writes a go/no-go report. Use this whenever the user says "ship it", "ship the site", "release readiness", "pre-launch check", "launch checklist", "is this ready to deploy", "deploy to prod", "cut a release", "bump the version and release", "promote dev to main", "smoke test staging/prod", or runs /ship-site — even if they only name one slice (e.g. "just smoke test the live site" or "do a pre-release audit"). Not for single-topic questions like "fix this CSS bug" or "write one test".
---

# ship-site

One pipeline that replaces the hand-run sequence: knowledge base → audits → browser proof → tests → build gate → release → smoke test. Orchestrate; don't re-implement what an installed skill already does. Stack-specific checklists live in `references/`, deterministic checks in `scripts/`.

**`SKILL_DIR`** below means the directory containing this file. It differs per install (`~/.claude/skills/ship-site`, a plugin cache path, a project `.claude/skills/`), so resolve it once from where you loaded this file and use the absolute path in every command.

## Modes

Parse the first argument:

| Invocation | Runs | Writes code? | Outward-facing? |
|---|---|---|---|
| `/ship-site audit` | Steps 0–10, read-only report | No | No |
| `/ship-site fix` | `audit`, then apply fixes, re-verify | Yes (local only) | No |
| `/ship-site release [patch\|minor\|major]` | Steps 0, 10–12 | Version bump | Yes — every step gated |
| `/ship-site smoke [url]` | Step 12 only | No | No |
| `/ship-site` (no arg) | Everything, pausing before anything outward-facing | Yes | Yes — gated |

Natural-language requests map the same way: "pre-launch check" → `audit`; "ship it" / "deploy to prod" → no-arg full run; "smoke test staging" → `smoke` with the staging URL from CLAUDE.md/docs; "release a patch" → `release patch`. `smoke` with no URL: take staging/production URLs from the repo docs, and ask only if none are written down. Don't open with scoping questions — the user wants you measuring. Start, and bring a plan.

## Hard rules (each one exists because it broke a real release)

- **Stop and ask** before: `git push`, PR creation, PR merge, version bump, git tag, `gh release`, and any real form submission that reaches a human inbox. One approval covers one action — a yes to "push the branch" is not a yes to "open the PR". Batch the question with the evidence the user needs to decide (diff stat, test result, target branch).
- Never force-push. Never delete a published tag or release. Never commit `next-env.d.ts`, a lockfile for a package manager the repo doesn't use, `.env*`, or run artifacts. Check `git status` before every commit and stage files by name.
- Every "fixed" or "passes" claim needs evidence in the report: a screenshot path, test output, or build log excerpt. If you couldn't verify, say "unverified" — don't round up.
- The repo's own CLAUDE.md **Don'ts** and **Known inconsistencies** (or equivalent sections in `docs/`) are rules. A known inconsistency is reported as "known, pre-existing" rather than as a new Blocker, and you don't fix it incidentally in `fix` mode without flagging that you did.
- `audit` and `smoke` never modify tracked files. If you must change something to run a check (a test port, a launch config), say so and revert it, or do it in a throwaway clone.

## Step 0 — Read the repo (always, every mode)

1. **Applicability.** Confirm `next` is in package.json and find the app dir (`src/app` or `app`). Pages Router only, or not Next.js at all: say so in one line, skip the Next-specific checks (metadata API, `next.config` CSP, `next-env.d.ts`), and run the rest — the build gate, browser, a11y, release and smoke steps are framework-neutral.
2. Read `CLAUDE.md`, `AGENTS.md`, `README.md` and every file in `docs/` that exists. Extract: Don'ts, Known inconsistencies, production/staging URLs, base branch, release commands.
3. Package manager: `packageManager` field in package.json wins; else lockfile (`yarn.lock` → yarn, `pnpm-lock.yaml` → pnpm, `bun.lock`/`bun.lockb` → bun, `package-lock.json` → npm). Use `<pm>` for every command below.
4. Host: `amplify.yml` → AWS Amplify, `vercel.json` or `.vercel/` → Vercel, `netlify.toml` → Netlify. Read only the matching section of `references/hosting.md`.
5. Branches: base = `dev` (or `develop`/`staging`) if it exists, else the default branch. Diff with `git diff <base>...HEAD --stat`.
6. Routes: `find src/app app \( -name 'page.tsx' -o -name 'page.ts' -o -name 'page.jsx' -o -name 'page.js' -o -name 'page.mdx' \) 2>/dev/null`. Drop route groups `(x)` and private `_x` folders from the URL; expand dynamic segments from `generateStaticParams` / data files.
7. Sanity-check the environment before trusting a red result: `node_modules` missing → install first (ask if it's a large download); `node_modules` symlinked outside the repo → Turbopack refuses to build, which is an environment problem, not a project Blocker (build in a clone, or report "could not run"). If Playwright's `baseURL` hardcodes a port you can't use, expect crawl failures that aren't real.
8. Run folder: the session scratchpad if you have one, else `./.ship-site/<timestamp>/` — and add `.ship-site/` to `.git/info/exclude` so it can never be committed. Subfolders `screenshots/`, `logs/`, `findings/`.

Tell the user in two lines what you detected (pm, host, base branch, N routes, diff size, which companion skills are available) and which mode you're running. Then go.

## Step 1 — Knowledge base

Check CLAUDE.md and the repo's docs exist and cover architecture, design tokens, content, and conventions (the names vary — `docs/ARCHITECTURE.md`, `DESIGN.md`, etc.). Missing coverage → `audit` reports it (Should-fix); `fix` runs the `init` skill for CLAUDE.md if available and drafts missing docs from code. For existing docs, diff their claims against the code the branch touched (file paths, route lists, token names, commands) and list the stale ones with file:line. Patch stale lines — don't rewrite docs wholesale.

## Steps 2–7 — Parallel audits

Launch these as **parallel subagents in a single message**. Each gets: the repo path, base branch, route list, the Don'ts/Known-inconsistencies from step 0, the absolute path of its reference file, the dev-server URL if it needs one, and the instruction to return findings JSON in the schema from `references/report-format.md`. Each subagent is read-only — it reports, it doesn't edit.

| Agent | Scope | Primary method | Fallback if the skill isn't installed |
|---|---|---|---|
| design | Step 2 — typography, spacing, hierarchy, motion, `prefers-reduced-motion`, touch targets ≥44px, dark mode if supported | a design-audit skill (e.g. `impeccable`, `web-design-guidelines`) | Review screenshots from step 8 and the components on the diff against the repo's design docs/tokens |
| code | Step 3 — correctness on the diff vs base, then reuse/simplification | `code-review` on the diff, then `simplify` framed as report-only | Read the diff file by file: logic errors, unhandled states, dead code, duplicated utilities |
| security | Step 4 — generic review + stack checks | `security-review` + `references/security.md` + `scripts/csp_hosts.py` | `references/security.md` alone covers the stack-specific checks |
| seo-analytics | Steps 5–6 | `references/seo.md` + `references/analytics.md` | — |
| a11y-perf | Step 7 — axe wcag2a/2aa per route, contrast, CWV, media | `references/a11y-perf.md` | — |

If you can't spawn subagents, run the same audits sequentially yourself — same scope, same JSON output.

Only the design and a11y-perf agents need a running server: start it yourself first (step 8) and pass them the URL so two agents don't race to start servers. While they run, do step 8 yourself — a shared browser can't be driven by several agents at once.

## Step 8 — Browser verification (you, not a subagent)

Follow `references/browser.md`. In short: start the dev server; visit every route at desktop (1440) and mobile (375) widths; read console and network after each for CSP violations, 404s, hydration errors; exercise the main form end to end; screenshot each route at both widths into the run folder.

Use whichever browser tooling the session has, in this order: a built-in preview/browser pane, a browser MCP (Chrome DevTools, Playwright MCP), then a throwaway Playwright script run with `npx playwright` from the run folder. If none can run, say "browser verification not performed" in the report — never infer rendered behaviour from source.

## Step 9 — Test suite

Run the repo's Playwright suite (`npx playwright test`, all configured projects). Save the summary line and any failures to `logs/playwright.log`. No Playwright config or no specs → `audit` reports Should-fix; `fix` scaffolds `tests/deployment-verification.spec.ts` from `references/playwright-scaffold.md` and runs it. Also run the repo's unit tests if a `test` script exists.

A failure that passes on retry is reported as flaky, not as a pass.

## Step 10 — Build gate

Run in order, saving the tail of each log to `logs/`: `<pm> lint`, `<pm> format:check` (or `npx prettier --check .` if the script is missing and Prettier is configured), a typecheck if there's a script for it, then `<pm> build`. A missing script is reported, not invented. Any non-zero exit is a Blocker. `next build` rewrites `next-env.d.ts` — make sure it's still unstaged afterwards.

## Merge findings → report

Merge subagent JSON + your own step 1/8/9/10 findings. Dedupe (same file:line, same root cause → one finding, list all sources). Rank:

- **Blocker** — ships broken, insecure, deindexed, or illegal (a11y AA fail on a primary flow, failed build, secret exposure, missing CSP host that breaks a feature, og:image missing, staging indexable, production noindexed, form doesn't reach backend).
- **Should-fix** — real defect with limited blast radius.
- **Nice-to-have** — polish.

Every finding: severity, area, `file:line`, what's wrong, concrete fix (code-level, not "consider improving"), evidence. Format: `references/report-format.md`.

**Verdict:** GO only if zero Blockers and steps 9–10 passed. Otherwise NO-GO with the shortest path to GO.

Write the report to the run folder. If a version is known and the repo keeps release notes (e.g. `docs/release-notes/`), offer to save a copy there — don't write into the repo unasked.

## `fix` mode

After the audit report, fix Blockers then Should-fixes, one logical change per commit-sized chunk. Skip Nice-to-haves unless trivial. For each fix: edit, re-run the specific check that found it (the script, the axe run, the browser page, the test), and attach that evidence. Then re-run steps 9 and 10 in full. Commit locally with conventional commits (see `references/release.md`); don't push. The final report shows before → after per finding with outcome `fixed` / `skipped (why)` / `could not verify`.

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
  [--json <run>/logs/smoke-<env>.json]
```

It checks status codes, `og:image`/`twitter:image` (and that the image resolves), robots meta + robots.txt per environment, canonical host, unknown-path 404, http→https redirect, first-party static assets, CSP and security headers, and exits non-zero on any failure. On staging pass `--canonical-host` with the production host. Pass `--expect-build` with a string unique to the new deploy (the commit SHA when `generateBuildId` uses it) to prove it's live rather than inferring it. Sites behind basic auth: pass `--header "Authorization: Basic …"` with credentials the user supplies — never commit or echo them.

Then, in the browser, open the home page and the form page and read the console for CSP/JS errors. On staging, submit the real form (ask first if it notifies a human inbox — it's a message sent on the user's behalf). Report the script output verbatim.

## Scripts (Python 3.9+, stdlib only)

- `scripts/smoke_test.py <url> --env staging|production [...]` — HTTP-level smoke checks; human output plus optional JSON. Exit 0 pass, 1 check failed, 2 site unreachable. `--help` lists every flag.
- `scripts/csp_hosts.py [repo] [--config next.config.ts] [--json]` — extracts every external host referenced in client code and diffs it against the CSP in the Next config. Missing hosts are likely Blockers; unused allowlisted hosts are Nice-to-have cleanups. Exit 0 clean, 1 missing hosts, 2 no config/CSP found.

## Reference files (read when you reach the step)

- `references/security.md` — CSP, `NEXT_PUBLIC_` secrets, headers, form hardening, server-only imports
- `references/seo.md` — metadata, OG/Twitter shallow-merge trap, sitemap/robots, JSON-LD, headings, alt text
- `references/analytics.md` — GA4, consent mode, `trackEvent()` wrapper, CSP hosts
- `references/a11y-perf.md` — axe, contrast, keyboard, reduced motion, CWV, images, video
- `references/browser.md` — the click-through protocol and what to look for
- `references/playwright-scaffold.md` — spec template when a repo has no suite
- `references/release.md` — commit conventions, branch flow, checkpoints
- `references/hosting.md` — Amplify / Vercel / Netlify differences
- `references/report-format.md` — findings JSON schema + final report template
