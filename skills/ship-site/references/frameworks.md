# Framework notes

`detect.py` names the stack (`framework.name`). Most of the pipeline doesn't depend on it: browser checks, axe, smoke tests, the release flow and the report work on the rendered site. This file covers what does change. Read only the row and section for the detected stack.

## At a glance

| Stack | Routes from | Public env prefix (ships to the browser) | Metadata / SEO | 404 page | Sitemap / robots | CSP usually set in | Dev port · build output |
|---|---|---|---|---|---|---|---|
| Next.js | `app/**/page.*`, `pages/**` | `NEXT_PUBLIC_` | `metadata` / `generateMetadata` | `app/not-found.*` | `app/sitemap.ts`, `app/robots.ts` | `next.config.*` `headers()`, middleware | 3000 · `.next/` (`out/` on export) |
| Astro | `src/pages/**` (`.astro .md .mdx .html`) | `PUBLIC_` (`import.meta.env`) | `<head>` in a layout (`src/layouts/`) | `src/pages/404.astro` | `@astrojs/sitemap` (needs `site`), `public/robots.txt` | host headers file, `<meta>` in layout, `security.csp` (Astro 5.9+ experimental) | 4321 · `dist/` |
| Nuxt | `pages/**` or `app/pages/**` (Nuxt 4) | `runtimeConfig.public` / `NUXT_PUBLIC_` | `useHead` / `useSeoMeta`, `app.head` in `nuxt.config` | `error.vue` | `@nuxtjs/sitemap`, `@nuxtjs/robots` (or `@nuxtjs/seo`) | `routeRules` headers, `nuxt-security` | 3000 · `.output/` |
| SvelteKit | `src/routes/**/+page.svelte` | `PUBLIC_` (`$env/static/public`) | `<svelte:head>` | `src/routes/+error.svelte` | `src/routes/sitemap.xml/+server.ts`, `static/robots.txt` | `kit.csp` in `svelte.config.js`, `hooks.server` | 5173 · adapter-dependent |
| Remix | `app/routes/*` (flat routes) | `VITE_` (or `window.ENV` from the root loader) | `meta` export | splat route `$.tsx` + root `ErrorBoundary` | resource route `sitemap[.]xml.tsx`, `public/robots.txt` | `entry.server` headers, server middleware | 5173 · `build/` |
| React Router 7 | `app/routes.ts` (or `flatRoutes()`) | `VITE_` | `meta` export / `<meta>` in route | splat route + root `ErrorBoundary` | resource route, `public/robots.txt` | `entry.server` headers | 5173 · `build/client`, `build/server` |
| Gatsby | `src/pages/**`, `createPages` in `gatsby-node` | `GATSBY_` | `Head` export | `src/pages/404.*` | `gatsby-plugin-sitemap`, `gatsby-plugin-robots-txt` | host headers (`gatsby-plugin-*-headers`) | 8000 · `public/` |
| Vite SPA / CRA | router config in `src/` (best effort) | `VITE_` / `REACT_APP_` | one `index.html` (+ `react-helmet-async`, `@unhead/vue`) | client catch-all route; host must not 200 every path | `public/sitemap.xml`, `public/robots.txt` | host headers, `<meta>` in `index.html` | 5173 / 3000 · `dist/` / `build/` |
| Angular | `Routes` arrays (best effort) | none: `environment.ts` is bundled whole | `Meta` / `Title` services | `**` route | `src/robots.txt` listed in `angular.json` assets | host headers, `<meta>` in `index.html` | 4200 · `dist/<project>/` |
| Eleventy | templates in the input dir; `permalink` front matter | none (`_data` is build-time) | layout `<head>` | `404.njk`/`404.md` with `permalink: 404.html` | a `sitemap.njk` template, `robots.txt` passthrough | host headers, `<meta>` in layout | 8080 · `_site/` |
| Hugo | `content/**` (`url`/`slug` front matter) | none | `layouts/partials/head.html`, `.Site.Params` | `layouts/404.html` | built in (`sitemap.xml`); `enableRobotsTXT` or `static/robots.txt` | host headers, `<meta>` in `baseof.html` | 1313 · `public/` |
| Jekyll | pages with front matter, `_posts`, collections | none | `jekyll-seo-tag`, `_includes/head.html` | `404.html` / `404.md` | `jekyll-sitemap`, `robots.txt` | host headers, `<meta>` in `_layouts/default.html` | 4000 · `_site/` |
| Static HTML | every `*.html` | none | each page's `<head>` | `404.html` (host-specific) | hand-written files | host headers, `<meta>` per page | any static server · the files |
| Django / Rails / Laravel / WordPress | crawl the running site | n/a (server-rendered) | templates | framework error templates | packages/plugins (e.g. `django.contrib.sitemaps`, Yoast) | middleware / server config | 8000 / 3000 / 8000 / host |

## Rules that hold everywhere

- **Secrets in the bundle.** Anything with the stack's public prefix is in the client JS. A key, token or private URL behind that prefix is a Blocker. Stacks without a prefix (Angular `environment.ts`, Eleventy/Hugo/Jekyll data files rendered into pages) leak by being *used* in a template or client script, so grep the build output (`output_dir`) for the secret's value or name.
- **Build gate.** Use the repo's scripts when they exist. Otherwise `framework.build_cmd` from `detect.py` (`hugo --gc --minify`, `bundle exec jekyll build`, `npx @11ty/eleventy`). Static HTML has no build. Run an HTML validator or link checker if the repo has one, and say the gate was "no build step".
- **Dev server.** Start it with the repo's `dev` script, or `framework.dev_cmd`, and wait for `framework.dev_port`. Plain static sites: `npx serve <dir>` or `python3 -m http.server`.
- **Routes.** `detect.py` reports `routes_source`. "best effort" (SPA routers, React Router config) means nested paths can be wrong or missing. Confirm the list by crawling the running site from `/` in step 8, and use the sitemap if there is one.
- **SPA 404s.** A client-rendered app served with a catch-all rewrite answers every path with 200. The smoke test's "unknown path returns 404" check fails, and that is a real finding: soft 404s get indexed. The fix is host-side (a `404.html`, or pre-rendering known routes), or at least a `noindex` meta on the client not-found view.
- **SPA SEO.** If the page's `<title>`, description and `og:*` only appear after JavaScript runs, link previews and some crawlers never see them. Check the raw HTML (`curl`) as well as the rendered DOM. Missing per-route metadata in raw HTML is a Should-fix on a marketing site, and a Blocker for the `og:image` of pages meant to be shared.

## Stack notes

### Next.js
The deepest coverage: `references/seo.md` (metadata API, OG shallow-merge), `references/security.md` (`next.config` CSP, `server-only`), `csp_hosts.py` and the OpenNext host build. `next build` rewrites `next-env.d.ts`; keep it unstaged.

### Astro
- `site` must be set in `astro.config.*` for canonical URLs and `@astrojs/sitemap`. Missing `site` → the sitemap integration silently writes nothing.
- Pages default to static. With `output: 'server'` or per-page `export const prerender = false`, an adapter must be installed for the host (`@astrojs/vercel`, `@astrojs/netlify`, `@astrojs/cloudflare`, `@astrojs/node`).
- Islands: `client:*` directives ship JS. A heavy component with `client:load` above the fold hurts LCP/INP. `client:visible` or `client:idle` usually fixes it.
- Endpoints (`src/pages/*.xml.js`, `*.json.ts`) are not pages: `detect.py` leaves them out of `routes`. Check `rss.xml` and friends by URL.

### Nuxt
- `ssr: false` in `nuxt.config` makes it an SPA: apply the SPA SEO and 404 rules above.
- `nuxt generate` outputs `.output/public`. Hosts serving that need the 404 page generated (`/404.html` or `200.html` fallback, per host).
- `runtimeConfig` (no `public`) is server-only. Moving a key into `runtimeConfig.public` exposes it.

### SvelteKit
- The adapter decides the host and the output (`adapter-static` → `build/`, `adapter-vercel`, `adapter-netlify`, `adapter-cloudflare`, `adapter-node`). `adapter-auto` in production config is a Should-fix: it guesses at build time.
- `$env/static/private` and `$env/dynamic/private` are server-only and the compiler refuses them in client code. `$env/*/public` and `PUBLIC_` are not.
- `+page.server.ts` / `+server.ts` run on the server: fetches there aren't subject to the browser CSP.
- `kit.csp` with `mode: 'auto'` adds nonces/hashes; inline scripts added outside SvelteKit then break.

### Remix / React Router 7
- Routes without a default export are resource routes (sitemaps, feeds, API). `detect.py` skips them; check them by URL.
- `meta` exports don't merge with parents. A child route that defines `meta` drops the parent's `og:*` tags unless it spreads them (`matches.flatMap(m => m.meta)`), the same trap as Next's OG shallow merge.
- Loader data is serialised into the page. A loader returning a whole user or config object leaks every field to the client.

### Gatsby
- `siteMetadata.siteUrl` is required by `gatsby-plugin-sitemap` and canonical tags.
- Pages built by `createPages` in `gatsby-node.*` don't appear in `src/pages`. Expand them from the data source, or crawl.

### Vite SPA, Create React App, Angular
- Treat the route list from `detect.py` as a hint and crawl. Per-route titles come from a head manager (`react-helmet-async`, `@unhead/vue`, Angular `Title`); without one, every route has the `index.html` title.
- The host needs an SPA fallback (rewrite unknown paths to `index.html`) for deep links to work. Check a deep link with a hard reload in step 8.
- CRA is deprecated. Note it as a post-launch backlog item, not a Blocker.

### Eleventy, Hugo, Jekyll
- The route list honours `permalink` / `url` / `slug` and skips drafts. Pagination and collections show as dynamic entries: expand them from the built output (`find <output_dir> -name index.html`) rather than guessing.
- Build the site and serve the output dir for browser checks. Serving the source shows unbuilt templates.
- `baseURL` (Hugo), `url` + `baseurl` (Jekyll) and the Eleventy `pathPrefix` decide absolute URLs. A staging value left in the production config is a Blocker: canonicals and `og:url` point at staging.
- Hugo `buildDrafts`/`buildFuture` on in the production config, or Jekyll `--drafts` in the build command, ships unfinished content.

### Static HTML
- Every page carries its own `<head>`. Check title, description, canonical and `og:*` on each, since nothing shares a layout.
- No build gate: run the repo's linter or validator if any, and record `build` as `not-run` with "no build step".

### Django, Rails, Laravel, WordPress
`detect.py` names them but finds no routes from files. Start the app the repo's documented way, crawl from `/`, and run the framework-neutral steps (browser, a11y, SEO on rendered pages, smoke, release). Stack-specific security review (CSRF, debug mode, admin exposure) belongs to the host's security-review skill, not this checklist.
