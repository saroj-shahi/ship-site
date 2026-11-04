# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.1.0] - 2026-11-04

### Added

- `SECURITY.md` with private vulnerability reporting.
- Issue forms for bug reports and false positives or missed issues.
- Dependabot updates for GitHub Actions.
- `launch_content.py`: finds placeholder and unconfirmed copy (TBD, lorem ipsum, sample content, "To confirm:" notes), create-next-app leftovers including the default favicon, and links back to the site being replaced or to `/wp-content/`.
- `smoke_test.py --legacy-urls`: checks that every URL of a replaced site (from its sitemap, following sitemap indexes, or a file) reaches a 200 on the new site. Redirects to the home page fail. Credentials passed with `--header` are not forwarded to other hosts on redirect.
- Step 1b, launch essentials (`references/launch-essentials.md`): unfinished content, icons and OG image, error pages, form consent, links, and handover hygiene.
- Replatform parity (`references/migration.md`): URL inventory and redirects, carried-over titles, descriptions and schema, hotlinks, and a cutover checklist.
- Cloudflare Workers (OpenNext) hosting section.
- Git-host detection (GitHub, Bitbucket, other), and a release section on following the repo's own workflow rules, including trunk-based repos.
- `state.json` checkpoints and a `resume` mode, for releases cut off by usage limits or context resets.
- Evals for a replatform pre-launch check and for resuming a release.
- Support for agents other than Claude Code: `install.py` installs the skill for Codex, Gemini CLI, Cursor, GitHub Copilot, OpenCode or Claude Code, at user or project scope. It defaults to the shared `~/.agents/skills` folder and warns when an agent would see two copies. `SKILL.md` gained a Host notes section covering invocation, instructions files, approvals in non-interactive modes, delegation and companion skills.
- Portability tests: frontmatter keys and limits, and no host-only substitutions.

### Changed

- `SKILL.md`, references and README are host-neutral: "the repo's instructions file" (AGENTS.md, CLAUDE.md, GEMINI.md, Cursor rules, Copilot instructions) instead of CLAUDE.md only, and generic browser-tool and subagent wording. The skill description is shorter (842 characters).
- Hard rules: no invented content to clear a finding; `--force-with-lease` is allowed only when the user asks, on their own feature branch.
- Step 0 flags stale second lockfiles and several host configs, and fetches before diffing against the base branch.
- Step 1 checks the docs' stack claims (host, package manager, git host, branches, CI) against what step 0 detected.
- Step 10 prefers the repo's aggregate `ci` script, runs the host-specific build, builds in a scratch worktree when a dev server shares `.next/`, and runs Lighthouse CI if configured.
- Step 8 re-checks reveal animations in Playwright, because embedded preview panes may never fire `IntersectionObserver`.

## [1.0.0] - 2026-10-26

First public release.

### Added

- Plugin packaging: `.claude-plugin/plugin.json` and a single-plugin `marketplace.json`, so the skill installs with `/plugin install`.
- `smoke_test.py`: `--header` for protected staging sites (sent only to the site under test, only over https), `--timeout`, exit code `2` when the site is unreachable, input URL validation, and checks for canonical host, unknown-path 404, http→https redirect, static assets, `twitter:image`, and `--expect-build`.
- `csp_hosts.py` skips tests, stories, and build output, scans `pages/`, and accepts a `--config` outside the repo.
- Test suite (`tests/`) covering both scripts end to end against a local fixture site, plus CI.
- An applicability check in step 0, a fallback for every companion skill, browser-tool-agnostic verification, a release flow for repos without a staging branch, and a `fix`-mode eval.
- Reference updates: consent mode verified in a real browser, regional GA4 endpoints, runtime env vars on Amplify SSR, form-handler check ordering and ReDoS, honest rate-limit guarantees, an empty-promotion check, and release-level mismatch handling.

### Changed

- The skill moved to `skills/ship-site/`. Personal-skill installs now link that folder.
- `SKILL_DIR` is resolved from wherever the skill is installed instead of assuming `~/.claude/skills/ship-site`.
- Organization-specific hosts and component names in references and evals were replaced with generic examples.
- `smoke_test.py` parses robots.txt by user-agent group, so a `Disallow: /` for another bot no longer reads as production being blocked.

[Unreleased]: https://github.com/saroj-shahi/ship-site/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/saroj-shahi/ship-site/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/saroj-shahi/ship-site/releases/tag/v1.0.0
