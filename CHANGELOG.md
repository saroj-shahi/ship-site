# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `SECURITY.md` with private vulnerability reporting.
- Issue forms for bug reports and false positives or missed issues.
- Dependabot updates for GitHub Actions.

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

[1.0.0]: https://github.com/saroj-shahi/ship-site/releases/tag/v1.0.0
