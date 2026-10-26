# Playwright scaffold (step 9, when a repo has no suite)

Only in `fix` or no-arg mode. Install if missing: `<pm> add -D @playwright/test @axe-core/playwright` then `npx playwright install` (ask first — it downloads browsers, ~500MB).

## playwright.config.ts (if missing)

```ts
import { defineConfig, devices } from '@playwright/test';
export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: 'html',
  use: { baseURL: 'http://localhost:3000', trace: 'on-first-retry' },
  projects: [
    { name: 'Desktop Chrome', use: { ...devices['Desktop Chrome'] } },
    { name: 'Desktop Safari', use: { ...devices['Desktop Safari'] } },
    { name: 'Mobile Chrome',  use: { ...devices['Pixel 5'] } },
    { name: 'Mobile Safari',  use: { ...devices['iPhone 12'] } },
  ],
  webServer: { command: '<pm> dev', url: 'http://localhost:3000', reuseExistingServer: !process.env.CI, timeout: 120_000 },
});
```

## tests/deployment-verification.spec.ts

Fill `ROUTES` from step 0 and form selectors from the actual form component (prefer `getByLabel` / `getByRole` so the test doubles as an a11y check).

```ts
import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const ROUTES = ['/', '/about', '/contact' /* … */];

test.describe('routes', () => {
  for (const route of ROUTES) {
    test(`${route} loads without console errors`, async ({ page }) => {
      const errors: string[] = [];
      page.on('console', m => m.type() === 'error' && errors.push(m.text()));
      const res = await page.goto(route);
      expect(res?.status()).toBe(200);
      await expect(page.locator('h1')).toHaveCount(1);
      expect(errors.filter(e => /Content Security Policy|Refused to/.test(e))).toEqual([]);
    });

    test(`${route} has og:image`, async ({ page }) => {
      await page.goto(route);
      await expect(page.locator('meta[property="og:image"]')).toHaveAttribute('content', /^https?:\/\//);
    });

    test(`${route} passes axe wcag2a/2aa`, async ({ page }) => {
      await page.goto(route);
      await page.waitForLoadState('networkidle');
      const { violations } = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze();
      expect(violations.filter(v => ['critical', 'serious'].includes(v.impact ?? ''))).toEqual([]);
    });
  }
});

test('no internal link returns 404', async ({ page, request }) => {
  const seen = new Set<string>();
  for (const route of ROUTES) {
    await page.goto(route);
    const hrefs = await page.$$eval('a[href^="/"]', as => as.map(a => (a as HTMLAnchorElement).getAttribute('href')!));
    for (const h of hrefs) seen.add(h.split('#')[0] || '/');
  }
  for (const href of seen) {
    const res = await request.get(href);
    expect(res.status(), href).toBeLessThan(400);
  }
});

test.describe('contact form', () => {
  test('shows validation errors on empty submit', async ({ page }) => {
    await page.goto('/contact');
    await page.getByRole('button', { name: /send|submit/i }).click();
    await expect(page.locator('[aria-invalid="true"]').first()).toBeVisible();
  });

  test('successful submission (backend mocked)', async ({ page }) => {
    await page.route('**/api/contact', r => r.fulfill({ status: 200, json: { ok: true } }));
    await page.goto('/contact');
    // fill fields via getByLabel(...) — adapt to the real form
    // complete captcha / human check
    // click submit, expect success state
  });
});

test.describe('media', () => {
  test('images have alt and dimensions', async ({ page }) => {
    await page.goto('/');
    const bad = await page.$$eval('img', imgs => imgs.filter(i => !i.hasAttribute('alt') || (!i.getAttribute('width') && !i.style.aspectRatio)).map(i => i.src));
    expect(bad).toEqual([]);
  });

  test('background video is muted and inline', async ({ page }) => {
    await page.goto('/');
    const vids = await page.$$eval('video[autoplay]', vs => vs.map(v => ({ muted: v.muted, inline: v.playsInline })));
    for (const v of vids) expect(v).toEqual({ muted: true, inline: true });
  });

  test('reduced motion keeps content visible', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/');
    await page.mouse.wheel(0, 5000);
    await expect(page.locator('main')).toBeVisible();
  });
});
```

Adapt the mocked-submission test to the real form before committing — a scaffold test with TODO comments that trivially passes is worse than none. Mark anything you couldn't fill as `test.fixme` and say so in the report.
