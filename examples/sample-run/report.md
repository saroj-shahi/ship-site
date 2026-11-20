# Release readiness — studio-site v1.4.0 — 2026-11-20

**Verdict: NO-GO** — 3 open Blockers (B1, B2, B3).

**Shortest path to GO** (details in `plan.md`):
- Fix 2 Blockers the agent can fix: B1, B2
- Get owner input or a decision for B3

| | Blockers | Should-fix | Nice-to-have | Known |
|---|---|---|---|---|
| Knowledge base | 0 | 0 | 0 | 0 |
| Launch content | 1 | 1 | 0 | 0 |
| Design | 0 | 0 | 0 | 0 |
| Code | 0 | 0 | 1 | 0 |
| Security | 0 | 0 | 0 | 0 |
| SEO | 1 | 1 | 0 | 0 |
| Analytics | 0 | 1 | 0 | 0 |
| A11y / Perf | 0 | 1 | 1 | 0 |
| Browser | 1 | 0 | 0 | 0 |
| **Total open** | **3** | **4** | **2** | **0** |

**Gates:** lint ✅ · format ✅ · typecheck ✅ · build ✅ · playwright ✅ (96/96 across 4 projects)
Detected: pm pnpm · host Vercel · base develop · routes 14 · diff +612/−140 in 23 files
Commit: `4f2c9e1` on `feat/launch`

## Blockers

### B1. CSP connect-src missing forms.example.com
- **Where:** `next.config.ts:41`
- **Area:** Browser, Security
- **Problem:** ContactForm posts to https://forms.example.com; the CSP blocks it and the form fails silently.
- **Fix:** Append https://forms.example.com to connect-src on line 41.
- **Evidence:** screenshots/contact-375-submit.png; console: Refused to connect to 'https://forms.example.com' (connect-src)

### B2. /work/[slug] drops og:image
- **Where:** `src/app/work/[slug]/page.tsx:18`
- **Area:** SEO
- **Problem:** generateMetadata sets openGraph: { title } without spreading the defaults. Next.js shallow-merges openGraph, so the layout's og:image is gone on every case study.
- **Fix:** openGraph: { ...OG_DEFAULTS, title: project.title, url: `/work/${slug}` }
- **Evidence:** curl http://localhost:3000/work/harbor | grep og:image → no match; screenshots/share-preview-work-harbor.png

### B3. Privacy policy link points to a placeholder
- **Where:** `src/components/ContactForm.tsx:87`
- **Area:** Launch content
- **Problem:** The consent checkbox links to /privacy, which renders 'Privacy policy — TBD'. Collecting form data without a policy is not launchable.
- **Fix:** Publish the client's privacy policy at /privacy.
- **Evidence:** launch_content.py: src/app/privacy/page.tsx:6 bracketed placeholder [TBD]
- **Owner:** owner/client must supply

## Should-fix

### S1. Staging robots.txt allows indexing
- **Where:** `src/app/robots.ts:4`
- **Area:** SEO
- **Problem:** robots.ts returns allow: / regardless of environment; staging.example.com is indexable.
- **Fix:** Return disallow: / unless process.env.SITE_ENV === 'production'.
- **Evidence:** curl https://staging.example.com/robots.txt → Allow: /

### S2. Hero video is 14 MB on mobile
- **Where:** `src/components/Hero.tsx:22`
- **Area:** A11y / Perf
- **Problem:** The same 1080p MP4 is served at 375 px; LCP on mobile is 4.1 s.
- **Fix:** Add a 720p source with media="(max-width: 768px)" and a poster image.
- **Evidence:** lighthouse mobile: LCP 4.1 s; network: hero.mp4 14.2 MB

### S3. Staging sends hits to the production GA property
- **Where:** `src/app/layout.tsx:31`
- **Area:** Analytics
- **Problem:** NEXT_PUBLIC_GA_ID is the production ID in every environment.
- **Fix:** Set a staging measurement ID on the host, or skip gtag unless SITE_ENV is production.
- **Evidence:** staging network: collect?tid=G-PROD123
- **Owner:** needs a decision

### S4. Default Next.js favicon still in place
- **Where:** `src/app/favicon.ico`
- **Area:** Launch content
- **Problem:** favicon.ico is the create-next-app default.
- **Fix:** Replace with the brand mark in 32 px and add apple-icon.png.
- **Evidence:** launch_content.py: favicon.ico matches the create-next-app hash
- **Owner:** owner/client must supply

## Nice-to-have

### N1. Footer link contrast 4.2:1
- **Where:** `src/components/Footer.tsx:9`
- **Area:** A11y / Perf
- **Problem:** text-neutral-500 on neutral-900 is 4.2:1, just under AA for small text.
- **Fix:** Use text-neutral-400.
- **Evidence:** axe color-contrast on /about

### N2. Duplicate date formatter
- **Where:** `src/lib/format.ts:3`
- **Area:** Code
- **Problem:** formatDate duplicates Intl logic already in src/lib/date.ts.
- **Fix:** Re-export from src/lib/date.ts.
- **Evidence:** code-review

## Known, pre-existing (from the repo's instructions)

None recorded.

## What passed

- **Knowledge base:** AGENTS.md routes and commands match the code
- **Launch content:** custom 404 and error pages; no links to the old site
- **Design:** touch targets ≥ 44 px; type scale matches tokens
- **Code:** no correctness issues in 23 changed files
- **Security:** HSTS max-age=63072000; no NEXT_PUBLIC secrets; server-only modules never imported by client components
- **SEO:** sitemap.xml lists all 14 routes; canonical host www.example.com; one h1 per page
- **Analytics:** consent default denied, update granted after accept (tested in browser); single trackEvent() wrapper
- **A11y / Perf:** axe: 0 violations on 13/14 routes; CLS < 0.02 on every route; reduced motion respected
- **Browser:** 28 screenshots, 0 hydration errors; no 4xx/5xx requests

## Not checked

- **Design:** dark mode: not supported by the site
- **Security:** rate limiting on /api/contact: needs staging credentials

## Evidence index

- Screenshots: `screenshots/`
- Logs: `logs/`
- Findings: `findings/*.json`, merged in `findings.json`
- Plan: `plan.md`
- Gate log, lint: `logs/lint.log`
- Gate log, format: `logs/format.log`
- Gate log, typecheck: `logs/typecheck.log`
- Gate log, build: `logs/build.log`
- Gate log, playwright: `logs/playwright.log`
