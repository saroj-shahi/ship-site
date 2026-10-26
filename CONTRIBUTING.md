# Contributing

Thanks for helping improve ship-site. Issues and pull requests are welcome.

## Reporting a problem

Open an issue with:

- the mode you ran (`audit`, `fix`, `release`, `smoke`) and your Claude Code version
- the stack: Next.js version, package manager, host
- what the skill did vs what you expected, ideally with the relevant part of the report

For a false positive or a missed issue in a script, a minimal reproduction (a robots.txt, a `next.config` snippet, a response header) is the fastest path to a fix.

## Making changes

1. Fork, then branch from `main`.
2. Keep changes focused. A checklist addition belongs in the matching `skills/ship-site/references/*.md` file, not in `SKILL.md`. `SKILL.md` holds the pipeline and the hard rules, and every line in it costs context on every run.
3. Scripts stay **Python 3.9+, stdlib only**. Users run them with no install step.
4. Add or update tests in `tests/` for any script change.
5. Run the checks:

   ```bash
   python3 -m unittest discover -s tests -v
   ```

   ```bash
   claude plugin validate . --strict
   ```

6. Add a line under `## [Unreleased]` in `CHANGELOG.md`.
7. Use [Conventional Commits](https://www.conventionalcommits.org/) for commit messages, e.g. `fix(smoke): handle HEAD-less CDNs`.

## Writing guidance for the skill

- **Explain the why.** "Never commit `next-env.d.ts` — `next build` rewrites it" generalizes better than a bare "NEVER".
- **Every check needs a severity rule** (Blocker / Should-fix / Nice-to-have) and a way to verify it with evidence.
- **Don't add new outward-facing actions** without a stop-and-ask checkpoint.
- **Keep examples generic** (`example.com`), with no real company hosts or component names.

## Testing the skill itself

Script tests don't exercise the orchestration. For a behaviour change in `SKILL.md` or a reference file, run the prompts in `skills/ship-site/evals/evals.json` against a real Next.js repo, with and without your change, using the `skill-creator` eval loop. Summarize the difference in the PR.

## Releasing (maintainers)

1. Bump `version` in `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`.
2. Move `Unreleased` entries under the new version in `CHANGELOG.md`.
3. Tag `vX.Y.Z` and create a GitHub release from the changelog section.
