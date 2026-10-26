# Accessibility & performance (step 7)

Measure in the running dev server (or `next start` after build for perf numbers — dev mode inflates LCP/INP). Don't estimate from source.

## 1. axe on every route

If `@axe-core/playwright` is installed, run a one-off script (save to the run folder, not the repo):

```ts
import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
const routes = ['/', '/about' /* … all routes from step 0 */];
for (const r of routes) test(`axe ${r}`, async ({ page }) => {
  await page.goto(r); await page.waitForLoadState('networkidle');
  const res = await new AxeBuilder({ page }).withTags(['wcag2a','wcag2aa']).analyze();
  console.log(JSON.stringify({ route: r, violations: res.violations.map(v => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, targets: v.nodes.slice(0,3).map(n => n.target) })) }));
});
```

Run with `npx playwright test <file> --project="Desktop Chrome" --reporter=line`. Otherwise inject axe from `node_modules/axe-core/axe.min.js` (or cdnjs `axe-core`) into the page with your browser tool's evaluate-script and run `axe.run({runOnly:['wcag2a','wcag2aa']})`.

Severity: `critical`/`serious` on a primary flow (nav, hero CTA, contact form) → Blocker; other `serious` → Should-fix; `moderate`/`minor` → Nice-to-have. Map each violation target back to a component `file:line`.

Pages with intro loaders / scroll locks: wait for the unlock before running axe, or you'll audit the loader.

## 2. Contrast

axe catches most. Also check text over images/video (axe can't) — screenshot and sample; ≥4.5:1 body, ≥3:1 large text and UI component boundaries. Check hover/focus states and the mobile nav.

## 3. Keyboard & focus

Tab through each route: visible focus ring everywhere, no traps, skip link if nav is long, modal traps focus and restores it on close, Escape closes. Touch targets ≥44×44 CSS px on mobile width.

## 4. Reduced motion

Emulate `prefers-reduced-motion: reduce` (Playwright `page.emulateMedia({ reducedMotion: 'reduce' })`). Autoplaying/parallax/scroll-linked motion should stop or become a fade. Content must still become visible (reveal animations that never fire under reduced motion = Blocker).

## 5. Core Web Vitals

Targets (p75): LCP < 2.5s, CLS < 0.1, INP < 200ms. In the browser:

```js
new PerformanceObserver(l => l.getEntries().forEach(e => console.log('LCP', e.startTime, e.element))).observe({type:'largest-contentful-paint', buffered:true});
new PerformanceObserver(l => { let c=0; l.getEntries().forEach(e => { if(!e.hadRecentInput) c+=e.value }); console.log('CLS', c) }).observe({type:'layout-shift', buffered:true});
```

Identify the LCP element and check it's not lazy-loaded, has `fetchpriority="high"`/`priority`, and its dimensions are reserved. For CLS, find shifting elements (fonts without `size-adjust`, images without dimensions, late banners).

## 6. Images

```bash
find public src/assets -type f \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' \) -size +200k
```

- Photographic images → webp/avif. PNGs >200KB that aren't transparency-critical → Should-fix.
- Every `<img>` / `next/image` has explicit `width`/`height` (or aspect-ratio container). Missing → CLS risk.
- Below-the-fold images `loading="lazy"`; hero not lazy.
- Served size roughly matches rendered size (check `naturalWidth` vs `clientWidth × DPR` in the browser).

## 7. Video

- Background/hero video: `muted playsInline autoPlay loop`, `preload="metadata"` or lazy, poster image set, paused under reduced motion.
- Below-the-fold video: lazy (IntersectionObserver or `preload="none"`).
- Embeds (Vimeo/YouTube): loaded on interaction or lazily; `title` on iframe.
- Autoplay-with-sound behaviour must be checked in a **fresh browser profile** — a browser that already has media engagement for the origin allows sound and hides the bug. Use a new Playwright context (fresh by default) rather than a long-lived browser session for this check.
