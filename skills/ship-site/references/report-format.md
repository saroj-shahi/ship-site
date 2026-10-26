# Findings schema & report template

## Subagent findings (JSON each audit agent returns)

```json
{
  "area": "security",
  "checked": ["CSP hosts", "NEXT_PUBLIC secrets", "headers", "form hardening", "server-only imports"],
  "findings": [
    {
      "severity": "blocker | should-fix | nice-to-have",
      "title": "CSP connect-src missing api.example.com",
      "file": "next.config.ts",
      "line": 37,
      "problem": "ContactForm posts to https://api.example.com; CSP blocks it silently.",
      "fix": "Append https://api.example.com to connect-src on line 37.",
      "evidence": "csp_hosts.py: missing connect-src api.example.com (src/lib/contactForm.ts:12)",
      "known_preexisting": false
    }
  ],
  "passed": ["HSTS max-age=63072000", "no NEXT_PUBLIC secrets"]
}
```

`checked` and `passed` matter: a report that only lists problems can't distinguish "fine" from "not looked at".

## Final report (markdown)

```markdown
# Release readiness — <repo> <vX.Y.Z or branch> — <date>

**Verdict: GO | NO-GO** — <one sentence why>. <If NO-GO: shortest path to GO in ≤3 bullets.>

| | Blockers | Should-fix | Nice-to-have |
|---|---|---|---|
| Design | 0 | 2 | 3 |
| Code | … |
| Security | … |
| SEO | … |
| Analytics | … |
| A11y / Perf | … |
| Browser | … |
| Knowledge base | … |

**Gates:** lint ✅ · format ✅ · build ✅ · Playwright 212/212 ✅ (4 projects) · smoke staging ✅ · smoke prod — not run
Detected: yarn 1.22 · AWS Amplify · base `dev` · 11 routes · diff +420/−88 in 14 files

## Blockers
### 1. <title>
- **Where:** `path/to/file.ts:37`
- **Problem:** …
- **Fix:** … (code snippet if short)
- **Evidence:** … (screenshot path / log excerpt / test name)
- **Status (fix mode):** fixed — re-ran X, output: … | skipped — why | could not verify

## Should-fix
…

## Nice-to-have
…

## Known, pre-existing (from CLAUDE.md)
- …

## What passed
- Security: HSTS, nosniff, … (so "not listed" never means "not checked")

## Evidence index
- Screenshots: `<run>/screenshots/*.png`
- Logs: `<run>/logs/{lint,format,build,playwright}.log`
- Smoke: `<run>/logs/smoke-<env>.json`
```

Keep the verdict honest: a single unverified Blocker fix means NO-GO or "GO pending: <thing>", never a clean GO.
