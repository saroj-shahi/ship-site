# ship-site

[![tests](https://github.com/saroj-shahi/ship-site/actions/workflows/ci.yml/badge.svg)](https://github.com/saroj-shahi/ship-site/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Claude Code skill](https://img.shields.io/badge/Claude%20Code-skill-d97757)](https://docs.claude.com/en/docs/claude-code/skills)

A [Claude Code](https://docs.claude.com/en/docs/claude-code) skill that takes a Next.js marketing site from "feature done" to "released in production" as one checkpointed pipeline, and finishes with a **GO / NO-GO** report where every claim carries evidence.

```
knowledge base → parallel audits → real-browser proof → tests → build gate → release → smoke test
```

It replaces the release checklist people run by hand and get wrong at 6pm on a Friday: `og:image` silently dropped by a metadata merge, a CSP that blocks the contact form, a staging site Google is indexing, a "passing" form test against a mocked backend.

## Contents

- [What it checks](#what-it-checks)
- [Install](#install)
- [Usage](#usage)
- [Safety model](#safety-model)
- [Requirements](#requirements)
- [How it reads your repo](#how-it-reads-your-repo)
- [Standalone scripts](#standalone-scripts)
- [Repository layout](#repository-layout)
- [Development](#development)
- [Limitations](#limitations)
- [License](#license)

## What it checks

| Area | Highlights |
|---|---|
| **Knowledge base** | CLAUDE.md and `docs/` exist, and their claims (paths, routes, commands) still match the code |
| **Design** | Typography, spacing, motion, `prefers-reduced-motion`, touch targets, via your installed design skills |
| **Code** | Correctness review of the diff against the base branch, then reuse/simplification |
| **Security** | CSP covers every external host, no secrets in `NEXT_PUBLIC_*`, security headers, form endpoint hardening (honeypot, rate limit, captcha, ReDoS, upstream timeout), server-only modules never imported by client components |
| **SEO** | Per-route metadata, the OG/Twitter shallow-merge trap, sitemap/robots, staging `noindex` vs production indexable, JSON-LD, heading outline, alt text |
| **Analytics** | GA4 loads, consent mode default + update tested in a real browser, single `trackEvent()` wrapper, GA hosts in CSP, staging kept out of the production property |
| **A11y & performance** | axe WCAG 2 A/AA on every route, contrast, keyboard and focus, reduced motion, Core Web Vitals, image and video weight |
| **Browser** | Every route at 1440 and 375 px: console, network, CSP violations, hydration errors, screenshots, contact form end to end |
| **Tests & build** | Playwright across all configured projects (flaky ≠ pass), then lint → format → typecheck → build |
| **Release** | Conventional commits → staging → version bump → release PR → tag + GitHub release, with a stop before every outward-facing step |
| **Smoke test** | Live status codes, `og:image` that resolves, robots per environment, canonical host, real 404s, http→https, static assets, CSP and security headers, proof the new build is live |

Findings are ranked **Blocker / Should-fix / Nice-to-have**, each with `file:line`, a code-level fix, and evidence (screenshot path, log excerpt, or test name). The report also lists what *passed*, so "not listed" never means "not checked". See [the report template](skills/ship-site/references/report-format.md).

## Install

### As a plugin (recommended)

In Claude Code:

```
/plugin install ship-site --marketplace saroj-shahi/ship-site
```

On older Claude Code versions, add the marketplace first:

```
/plugin marketplace add saroj-shahi/ship-site
/plugin install ship-site@ship-site
```

Update later with `/plugin update ship-site`.

### As a personal skill

Clone the repo and link the skill folder into your skills directory:

```bash
git clone https://github.com/saroj-shahi/ship-site.git
```

```bash
ln -s "$PWD/ship-site/skills/ship-site" ~/.claude/skills/ship-site
```

To share it with a team through one repo, copy `skills/ship-site/` into that project's `.claude/skills/` instead.

Restart Claude Code, then check that `ship-site` appears in the skill list.

## Usage

| Command | What it does | Changes code? | Outward-facing? |
|---|---|---|---|
| `/ship-site audit` | Read-only release-readiness report | No | No |
| `/ship-site fix` | Audit, then fix Blockers and Should-fixes locally, re-verifying each one | Local commits only | No |
| `/ship-site release [patch\|minor\|major]` | Build gate → staging → version bump → release PR → tag and release | Version bump | Yes, every step gated |
| `/ship-site smoke [url]` | Post-deploy smoke test; uses the URL from your docs if you omit it | No | No |
| `/ship-site` | The whole pipeline, pausing before anything outward-facing | Yes | Yes, gated |

When installed as a plugin, the command may be namespaced as `/ship-site:ship-site`. You rarely need it, because the skill also triggers on plain requests:

> "is this ready to ship?" · "run a pre-launch check" · "cut a patch release" · "smoke test staging" · "promote dev to main"

### Example

```
> /ship-site audit

Detected: pnpm · Vercel · base `main` · 14 routes · diff +612/−140 in 23 files
Mode: audit (read-only). Companion skills: code-review, security-review.
...
Verdict: NO-GO — 2 Blockers.
  1. /work/[slug] drops og:image (openGraph set without ...OG_DEFAULTS) — src/app/work/[slug]/page.tsx:18
  2. CSP connect-src missing https://forms.example.com — next.config.ts:41
Gates: lint ✅ · format ✅ · build ✅ · Playwright 96/96 ✅ (4 projects)
Report: .ship-site/2026-10-26T14-02/report.md
```

## Safety model

The skill acts only after you say yes. It **stops and asks before each** of these:

- `git push`, opening a PR, merging a PR
- a version bump, a git tag, `gh release`
- a real form submission that would reach a human inbox

One approval covers one action, so a yes to "push" is not a yes to "open the PR". It never force-pushes, never deletes a published tag or release, and never commits `next-env.d.ts`, a lockfile for a package manager the repo doesn't use, or `.env*` files. `audit` and `smoke` leave tracked files untouched, and run artifacts go to the session scratchpad or a git-excluded `.ship-site/` folder.

## Requirements

| Need | For |
|---|---|
| [Claude Code](https://docs.claude.com/en/docs/claude-code) | Running the skill |
| Python 3.9+ | The bundled scripts (stdlib only, nothing to install) |
| A Next.js App Router site with `git` | Full coverage. Other frameworks get the framework-neutral steps: build gate, browser, a11y, release, smoke |
| [`gh`](https://cli.github.com/), authenticated | PRs and GitHub releases in `release` mode |
| Playwright in the target repo | The test step (the skill can scaffold a suite in `fix` mode, after asking) |
| A browser tool | Step 8: a built-in browser pane, a browser MCP (Chrome DevTools or Playwright MCP), or a Playwright script as a fallback |

### Optional companion skills

ship-site orchestrates other skills when they're installed and falls back to its own checklists when they aren't:

| Skill | Used for |
|---|---|
| `code-review`, `simplify` | Code audit of the diff |
| `security-review` | Generic security pass before the stack-specific checks |
| `impeccable`, `web-design-guidelines`, or similar | Design audit |
| `init` | Drafting a missing CLAUDE.md in `fix` mode |

## How it reads your repo

Step 0 runs in every mode and needs no configuration. It detects:

- the **package manager**, from `packageManager` or the lockfile
- the **host**: AWS Amplify (`amplify.yml`), Vercel (`vercel.json` or `.vercel/`), or Netlify (`netlify.toml`)
- the **staging branch** (`dev`, `develop`, or `staging`; otherwise the default branch) and the diff against it
- every **route**, from `app/**/page.*`, with dynamic segments expanded

It also reads `CLAUDE.md`, `AGENTS.md`, `README.md`, and `docs/`. Writing these down there makes it more accurate:

- **Production and staging URLs**: used by `smoke` and the release flow
- **Don'ts**: treated as hard rules
- **Known inconsistencies**: reported as "known, pre-existing" rather than as new Blockers
- **Release scripts** (`release:patch`, `release:publish`, …): used in place of the raw `npm version` / `git tag` / `gh release` commands

## Standalone scripts

Both scripts run without Claude and are handy in CI.

```bash
# Post-deploy smoke test. Exit: 0 pass, 1 check failed, 2 unreachable.
python3 skills/ship-site/scripts/smoke_test.py https://staging.example.com --env staging \
  --canonical-host www.example.com --json smoke-staging.json

python3 skills/ship-site/scripts/smoke_test.py https://www.example.com --env production \
  --expect-build "$GITHUB_SHA"
```

```bash
# External hosts in source vs the CSP in next.config.*. Exit: 0 clean, 1 missing hosts, 2 no CSP found.
python3 skills/ship-site/scripts/csp_hosts.py path/to/site --json
```

Run either one with `--help` for all flags. For a staging site behind basic auth, `smoke_test.py --header "Authorization: Basic …"` sends that header only to the site under test, and only over https.

## Repository layout

```
.claude-plugin/
  plugin.json             plugin manifest
  marketplace.json        single-plugin marketplace, so /plugin install works from this repo
skills/ship-site/
  SKILL.md                the orchestrator: modes, hard rules, steps 0–12
  references/             checklists loaded on demand (security, seo, analytics,
                          a11y-perf, browser, release, hosting, playwright-scaffold,
                          report-format)
  scripts/
    smoke_test.py         HTTP smoke checks
    csp_hosts.py          CSP vs source host diff
  evals/evals.json        prompts + assertions for skill-creator's eval loop
tests/                    unit + end-to-end tests for the scripts
```

`SKILL.md` stays short. Claude loads a reference file only when it reaches that step, which keeps the context cost low.

## Development

```bash
python3 -m unittest discover -s tests -v
```

```bash
claude plugin validate . --strict
```

The tests run each script against a local fixture repo and a throwaway HTTP server, so they need no network access. CI runs the tests on every push.

To measure the skill itself, run the prompts in [`evals/evals.json`](skills/ship-site/evals/evals.json) through the `skill-creator` eval loop against a real Next.js repo and compare with a no-skill baseline.

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Limitations

- Next.js App Router conventions run through the SEO and security checklists. Pages Router or non-Next sites get partial coverage, and the skill says so up front.
- `csp_hosts.py` is a static heuristic. Hosts built at runtime or fetched inside SDKs won't show up, so the browser console in step 8 is the source of truth.
- Hosting guidance covers AWS Amplify, Vercel, and Netlify. For any other host, the skill asks for your staging and production URLs and skips the host-specific checks.
- It can't fix anything that lives outside the repo, such as GA admin event rules, host console headers, or DNS. It flags those for you instead.

## License

[MIT](LICENSE) © Saroj Shahi
