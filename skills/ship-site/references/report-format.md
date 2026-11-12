# Findings, gates, report and plan

A run produces three inputs and three outputs, all in the run folder:

| File | Written by | Holds |
|---|---|---|
| `findings/<area>.json` | each audit subagent, and you for `knowledge-base`, `launch-content`, `browser` | findings for one area, plus what was checked, passed, and not checked |
| `gates.json` | you, after steps 9, 10 and 12 | pass/fail of every gate |
| `state.json` | you, throughout | mode, repo facts, release progress and release steps |
| `report.md` | `scripts/build_report.py` | the go/no-go report |
| `plan.md` | `scripts/build_report.py` | the ordered route to GO and through the release |
| `findings.json` | `scripts/build_report.py` | merged findings with stable IDs; the next run's `--previous` |

Don't hand-write `report.md` or `plan.md`. To change them, fix the inputs and re-run the script. That way the counts, IDs and verdict always agree with the findings.

## Findings JSON (one file per area)

```json
{
  "area": "security",
  "checked": ["CSP hosts", "NEXT_PUBLIC secrets", "headers", "form hardening", "server-only imports"],
  "passed": ["HSTS max-age=63072000", "no NEXT_PUBLIC secrets"],
  "not_checked": ["rate limiting on /api/contact: staging is behind auth we don't have"],
  "findings": [
    {
      "severity": "blocker",
      "title": "CSP connect-src missing api.example.com",
      "file": "next.config.ts",
      "line": 37,
      "problem": "ContactForm posts to https://api.example.com; CSP blocks it silently.",
      "fix": "Append https://api.example.com to connect-src on line 37.",
      "evidence": "csp_hosts.py: missing connect-src api.example.com (src/lib/contactForm.ts:12)",
      "verify": "python3 $SKILL_DIR/scripts/csp_hosts.py . exits 0, and the form submits in the browser with no CSP error",
      "owner": "agent",
      "effort": "S",
      "known_preexisting": false
    }
  ]
}
```

| Field | Required | Values / meaning |
|---|---|---|
| `severity` | yes | `blocker` · `should-fix` · `nice-to-have` (rules in SKILL.md) |
| `title` | yes | Short and specific. With `file`, it is the finding's identity across runs, so don't reword it between runs |
| `file`, `line` | most | Where to fix it. Leave `line` out for file-level or site-wide issues |
| `problem`, `fix`, `evidence` | yes | What's wrong, the code-level fix, and the proof that it is wrong (log line, screenshot path, test name) |
| `verify` | yes | The exact check that proves it's fixed. The plan prints it under the task |
| `owner` | default `agent` | `agent` = fixable from the repo · `owner` = needs content, credentials, assets or access from the site owner · `decision` = several valid fixes, and the choice belongs to the owner |
| `effort` | recommended | `S` under ~15 min · `M` under ~2 h · `L` more |
| `known_preexisting` | default false | Listed in the repo's Known inconsistencies, so it goes under `K` IDs and stays out of the verdict |
| `area` | no | Overrides the file's `area` for one finding (the seo-analytics agent uses `seo` and `analytics`) |
| `status`, `fix_evidence` | fix mode | `open` · `fixed` · `skipped` · `could-not-verify` · `accepted` (the owner chose to ship with it, in writing). `fix_evidence` is the re-run output |

`checked`, `passed` and `not_checked` matter. A report that only lists problems can't tell "fine" from "not looked at". An area with no file at all shows up in the report as "not run".

## gates.json

```json
{
  "lint": {"status": "pass", "log": "logs/lint.log"},
  "format": {"status": "pass", "log": "logs/format.log"},
  "typecheck": {"status": "not-run", "detail": "no typecheck script"},
  "build": {"status": "pass", "log": "logs/build.log"},
  "playwright": {"status": "fail", "detail": "93/96, 3 failed in mobile-safari", "log": "logs/playwright.log"},
  "smoke-staging": {"status": "pass", "log": "logs/smoke-staging.json"}
}
```

`status` is `pass`, `fail`, `flaky` (passed only on retry) or `not-run`. Keys keep their order in the report. A string value (`"lint": "pass"`) is shorthand for `{"status": "pass"}`.

## Verdict (computed)

- **NO-GO**: any open Blocker (status not `fixed`/`accepted`), or any gate `fail`.
- **GO pending**: no open Blocker, but a gate is `not-run` or `flaky`, a Blocker fix is `could-not-verify`, or no gates were recorded.
- **GO**: zero open Blockers and every recorded gate passed.

`--summary` replaces the one-line reason after the verdict. It can't change the verdict itself. A single unverified Blocker fix means "GO pending", never a clean GO.

## report.md layout

1. Title, then **Verdict** with its reason, then the shortest path to GO when it isn't GO.
2. Counts table: open findings per area and severity, plus a total row. A finding raised by several audits counts once.
3. Gates line, the detected stack (from `state.detected`), and the commit.
4. **Since the last run** (only with `--previous`): new, resolved, still open, by ID.
5. Blockers, Should-fix, Nice-to-have. Each finding shows ID, Where, Area (every audit that raised it), Problem, Fix, Evidence and Owner (when it isn't the agent). In fix mode it also shows Status with the re-run evidence.
6. Known, pre-existing.
7. What passed.
8. **Not checked**: each area's `not_checked`, areas with no findings file, and gates that didn't run.
9. Evidence index.

## plan.md layout

The plan is the report turned into work, in the order it should happen. It is the document to hand a developer or a client.

1. **Now**: the verdict and the numbered path to GO.
2. **Required before launch, agent can fix**: Blockers with `owner: agent`, cheapest first. Each is a checkbox with ID, location and effort, a "Do" line (the fix) and a "Verify" line.
3. **Required before launch, needs the owner**: Blockers with `owner`/`decision`.
4. **Recommended before launch**: Should-fixes, agent items first.
5. **Owner inputs to request**: every open `owner`/`decision` item at any severity, as one list to forward.
6. **Re-verify**: gates that didn't pass, then the full gate, then re-running the script.
7. **Release**: `state.release.steps` as checkboxes, with ⏸ on each step that needs approval. Write these for the real repo (branch names, package manager, scripts) from step 0 and `references/release.md`:

   ```json
   "release": {"steps": [
     {"step": "Push the feature branch", "command": "git push -u origin feat/launch", "approval": true, "done": false},
     {"step": "PR into develop", "command": "gh pr create --base develop --title \"feat: launch pages\"", "approval": true, "done": false},
     {"step": "Smoke test staging", "command": "python3 $SKILL_DIR/scripts/smoke_test.py https://staging.example.com --env staging", "approval": false, "done": false}
   ]}
   ```

8. **Backlog, after launch**: Nice-to-haves.
9. Known, pre-existing items, listed so nobody re-raises them.

IDs (`B1`, `S2`, `N3`, `K1`) persist when the script re-runs in the same folder, and carry over from `--previous`, so "B2 is done" means the same thing in the report, the plan, a commit message and a chat with the client.
