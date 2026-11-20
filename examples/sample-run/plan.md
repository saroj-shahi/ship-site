# Launch plan — studio-site v1.4.0 — 2026-11-20

**Now: NO-GO** — 3 open Blockers (B1, B2, B3).

**Path to GO:**
1. Fix 2 Blockers the agent can fix: B1, B2
2. Get owner input or a decision for B3

## 1. Required before launch — agent can fix

Clear these first, in order. One fix per commit; re-run its check before moving on. Effort: 2×S.

- [ ] **B1** CSP connect-src missing forms.example.com — `next.config.ts:41` · effort S · Browser
  - Do: Append https://forms.example.com to connect-src on line 41.
  - Verify: csp_hosts.py exits 0 and the form submits with no CSP error at 1440 and 375 px
- [ ] **B2** /work/[slug] drops og:image — `src/app/work/[slug]/page.tsx:18` · effort S · SEO
  - Do: openGraph: { ...OG_DEFAULTS, title: project.title, url: `/work/${slug}` }
  - Verify: og:image present on all 6 /work/* pages; smoke_test.py og check passes

## 2. Required before launch — needs the owner

Content, credentials or decisions only the site owner can supply. Never invent them to close the item. Effort: 1×S.

- [ ] **B3** Privacy policy link points to a placeholder — `src/components/ContactForm.tsx:87` · effort S · Launch content
  - Do: Publish the client's privacy policy at /privacy.
  - Verify: launch_content.py exits 0; /privacy shows the final policy

## 3. Recommended before launch

Real defects with limited blast radius. Fix now if cheap, or schedule with a date. Effort: 3×S, 1×M.

- [ ] **S1** Staging robots.txt allows indexing — `src/app/robots.ts:4` · effort S · SEO
  - Do: Return disallow: / unless process.env.SITE_ENV === 'production'.
  - Verify: smoke_test.py --env staging robots check passes
- [ ] **S2** Hero video is 14 MB on mobile — `src/components/Hero.tsx:22` · effort M · A11y / Perf
  - Do: Add a 720p source with media="(max-width: 768px)" and a poster image.
  - Verify: mobile LCP < 2.5 s on /
- [ ] **S3** Staging sends hits to the production GA property — `src/app/layout.tsx:31` · effort S · Analytics
  - Do: Set a staging measurement ID on the host, or skip gtag unless SITE_ENV is production.
  - Verify: staging browser pass shows no hits to the production ID
- [ ] **S4** Default Next.js favicon still in place — `src/app/favicon.ico` · effort S · Launch content
  - Do: Replace with the brand mark in 32 px and add apple-icon.png.
  - Verify: launch_content.py exits 0

## Owner inputs to request

One list to send to the owner/client, all severities:

- [ ] **B3** Privacy policy link points to a placeholder — Publish the client's privacy policy at /privacy.
- [ ] **S3** Staging sends hits to the production GA property — Set a staging measurement ID on the host, or skip gtag unless SITE_ENV is production.
- [ ] **S4** Default Next.js favicon still in place — Replace with the brand mark in 32 px and add apple-icon.png.

## Re-verify

After the fixes above, re-run in this order and record each in `gates.json`:

- [ ] Build gate in full (lint, format, typecheck, build) and the Playwright suite
- [ ] `build_report.py` again: the verdict must read GO

## Release

⏸ = stop and ask; one approval covers one step.

- [ ] ⏸ Push the feature branch — `git push -u origin feat/launch`
- [ ] ⏸ PR into develop — `gh pr create --base develop --title "feat: launch pages"`
- [ ] Smoke test staging — `python3 $SKILL_DIR/scripts/smoke_test.py https://staging.example.com --env staging`
- [ ] ⏸ Bump version — `pnpm release:minor`
- [ ] ⏸ Release PR into main — `gh pr create --base main --head develop --title "release: v1.4.0"`
- [ ] ⏸ Tag and GitHub release — `pnpm release:publish`
- [ ] Smoke test production — `python3 $SKILL_DIR/scripts/smoke_test.py https://www.example.com --env production --expect-build 4f2c9e1`

## Backlog — after launch

Polish. Doesn't block GO. Effort: 2×S.

- [ ] **N1** Footer link contrast 4.2:1 — `src/components/Footer.tsx:9` · effort S · A11y / Perf
  - Do: Use text-neutral-400.
  - Verify: axe: 0 violations on /about
- [ ] **N2** Duplicate date formatter — `src/lib/format.ts:3` · effort S · Code
  - Do: Re-export from src/lib/date.ts.
  - Verify: pnpm typecheck passes
