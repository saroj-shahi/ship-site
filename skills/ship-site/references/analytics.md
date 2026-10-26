# Analytics checklist (step 6)

## 1. GA4 loads

- `gtag.js` loaded via `next/script` (strategy `afterInteractive`) in the root layout, with the measurement ID (`G-XXXX`). Hardcoded or from a `NEXT_PUBLIC_` var — both fine, a GA ID is public.
- In the browser (step 8): network shows `googletagmanager.com/gtag/js?id=G-…` 200 and at least one `google-analytics.com/g/collect` (or `analytics.google.com`) request after consent/page view. `window.gtag` and `window.dataLayer` exist.

## 2. Consent mode default

Before `gtag('config', …)`, a default consent call must run:

```js
gtag('consent', 'default', {
  ad_storage: 'denied', ad_user_data: 'denied', ad_personalization: 'denied',
  analytics_storage: 'denied', // or 'granted' if the site's policy is opt-out and legally reviewed
  wait_for_update: 500,
});
```

Then the consent banner/module (e.g. `src/lib/cookieConsent.ts`) calls `gtag('consent', 'update', …)` on choice. Check: order in the inline script, update wired to the banner, choice persisted.

**Test it in a real browser, don't infer it from source** — a consent update that looks right in code can still send `denied` (wrong key, fired before gtag loads, overwritten by a later default). In a fresh context: load `/`, click Accept, then verify all three: `dataLayer` contains a `consent`,`update` entry with `analytics_storage: 'granted'`; a `_ga` cookie exists; the next `/g/collect` request has `gcs=G111` (or `G1x1` per the granted set). Reload and verify it persists. Repeat with Reject → no `_ga`, `gcs=G100`. A broken Accept path is a Blocker when the release is about analytics. Missing default → Blocker for EU/UK traffic, Should-fix otherwise; flag to the user rather than deciding their legal posture.

## 3. One `trackEvent()` wrapper

```bash
grep -rn "gtag(" src | grep -v "src/lib/analytics"
grep -rn "window.dataLayer" src | grep -v "src/lib/analytics"
```

Any direct `gtag(`/`dataLayer.push` outside the wrapper (other than the loader script in layout) → Should-fix: route it through `trackEvent()`, which guards against `gtag` not loaded yet. List all event names in use and check they're snake_case and ≤40 chars (GA4 limits). Compare with the event list in CLAUDE.md/docs — new undocumented events → update docs.

## 4. CSP allows GA hosts

GA4 needs at minimum:
- `script-src`: `https://www.googletagmanager.com`
- `connect-src`: `https://www.google-analytics.com`, `https://analytics.google.com`, `https://www.googletagmanager.com` (regional: `https://*.google-analytics.com`, `https://*.analytics.google.com` if using wildcards)
- `img-src`: `https://www.google-analytics.com`, `https://www.googletagmanager.com`

A missing host blocks collection silently. Confirm in the browser console (`Refused to connect to …`). GA4 sends some hits to **regional** endpoints (`region1.google-analytics.com`, `*.analytics.google.com`) — if the CSP lists only the exact `www.`/`analytics.` hosts, those are dropped. Recommend `https://*.google-analytics.com https://*.analytics.google.com` in `connect-src`.

## 5. Web Vitals / outbound / scroll

If the site reports CWV via `web-vitals`, check it fires once per metric per page (not on every render) and goes through `trackEvent()`. Outbound link tracking should use `transport_type: 'beacon'` or equivalent so navigation doesn't cancel it.

## 6. Environment separation & GA-side config

- Staging should not report into the production property: load GA only when `isProductionDeploy`, or use a separate measurement ID for staging. Otherwise staging QA traffic pollutes real data (Should-fix).
- Events that appear in network traffic but not in code (e.g. `generate_lead` firing on page view) come from GA admin "create event" rules. Flag them for the user to check in the GA UI — you can't fix them from the repo.
