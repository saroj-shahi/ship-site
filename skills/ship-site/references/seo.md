# SEO checklist (step 5)

## 1. Metadata on every route

For each `page.tsx` / `layout.tsx`: `export const metadata` or `generateMetadata` with `title`, `description` (50–160 chars), and `alternates.canonical`. Dynamic routes (`[slug]`) must use `generateMetadata` with per-item title/description. Duplicate titles across routes → Should-fix.

## 2. The OG/Twitter shallow-merge trap

Next.js **does not deep-merge** `openGraph` or `twitter` across segments. A page that declares `openGraph: { url: "/about" }` replaces the layout's whole object — `images`, `siteName`, `type`, `locale` vanish. No build error; `og:image` just disappears.

Rule: any segment that sets `openGraph` must spread the shared defaults first; same for `twitter`.

```ts
openGraph: { ...OG_DEFAULTS, url: "/about", title, description },
twitter:   { ...TWITTER_DEFAULTS, title, description },
```

Check:
```bash
grep -rn "openGraph:\|twitter:" src/app
```
Every hit outside the root layout must contain `...OG_DEFAULTS` / `...TWITTER_DEFAULTS` (or whatever the repo's shared-defaults module exports — find it via `grep -rn "export const OG_" src/lib`). Missing spread → Blocker (social shares lose their image). Confirm in step 12: the smoke script checks `og:image` on every route.

`metadataBase` must be set in the root layout, or relative OG URLs resolve to localhost.

## 3. sitemap.ts + robots.ts

- `src/app/sitemap.ts` lists every static route plus every dynamic item (from the same data module `generateStaticParams` uses). A route present in the app but missing from the sitemap → Should-fix.
- `src/app/robots.ts` exists, references the sitemap on production, disallows `/api/`.

## 4. Preview/staging must be noindex

Staging is usually a public subdomain built from the same code. It needs **both**:
- `robots.txt` → `Disallow: /` (stops crawling), and
- `<meta name="robots" content="noindex, nofollow">` (deindexes URLs linked from elsewhere — robots.txt alone doesn't).

Both should flip on one env signal (e.g. `isPreviewDeploy` from `AWS_BRANCH !== "main"` on Amplify, `VERCEL_ENV !== "production"` on Vercel, `CONTEXT !== "production"` on Netlify). The default when the signal is absent must be **indexable** — getting it backwards on production deindexes the whole site, which is worse than a staging leak. Verify live with the smoke script on both environments.

## 5. JSON-LD

Root: `Organization` (name, url, logo, sameAs socials). Optionally `WebSite`. Case studies: `CreativeWork` or `Article`. Rendered via `<script type="application/ld+json">` with `JSON.stringify` of static data. Validate shape (required fields present, absolute URLs).

## 6. Headings

Per route (check in the running page, not source — components compose):

```js
[...document.querySelectorAll('h1,h2,h3,h4,h5,h6')].map(h => h.tagName + ' ' + h.textContent.trim().slice(0,50))
```

- Exactly one `h1`.
- No level skips (h1 → h3 with no h2). Known gaps listed in CLAUDE.md "Known inconsistencies" are reported as known, not new.

## 7. Alt text

- Every `<img>` / `next/image` has `alt`. Decorative images use `alt=""` (not missing).
- Alt describes content, isn't a filename, isn't "image of".
```js
[...document.images].filter(i => !i.hasAttribute('alt')).map(i => i.src)
```

## 8. Misc

- `lang` on `<html>`.
- No `noindex` on production pages (check after build).
- Internal links use `<Link>`, no links to 404s (the Playwright crawl covers this).
