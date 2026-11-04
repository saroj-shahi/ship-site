# Replatform parity (step 5b)

Read this when the release **replaces an existing live site**: a WordPress-to-Next.js rebuild, a new repo taking over the same domain, a prototype promoted to production. Detect it in step 0 from the docs ("replace the current site", "cutover", an old domain) or ask once.

The old site's search rankings live in its URLs, titles, descriptions and structured data. A rebuild that drops any of them can lose traffic the client earned over years, and nobody notices until the analytics dip.

## 1. URL inventory → every old URL has a destination

1. Get the old URL list: the live `sitemap.xml` (WordPress/Yoast serve a sitemap index; the smoke script follows it), plus any URLs the client's SEO report or Search Console export names.
2. Map each one to a new route or a 301. Redirects live in `next.config.*` `redirects()` or at the host (Amplify rewrites, `_redirects`, Cloudflare rules). Use one place, not both.
3. Prove it against staging:
   ```bash
   python3 "$SKILL_DIR/scripts/smoke_test.py" <staging-url> --env staging --routes / \
     --legacy-urls https://<old-host>/sitemap.xml --header "…"
   ```
   Fails: a 404, or a redirect that dumps to the home page (search engines treat that as a soft 404). A redirect chain passes but is listed. Point old URLs straight at their target.
4. Trailing slashes: WordPress URLs end in `/`, Next.js strips it with a 308. That's one hop; fine. Don't add `trailingSlash: true` just to match.

## 2. Carry over what ranks

For pages that rank (from the client's SEO report, Search Console, or ask), the new page keeps:
- **Title and meta description.** Compare old vs new per mapped URL. A rebuilt page whose title went from a keyword phrase to "Product — Brand" is a Should-fix; on a page that ranks #1 for that phrase, a Blocker.
- **Structured data**: Organization, LocalBusiness/location, FAQ, Article, Breadcrumb. Same types, same facts.
- **Headings and on-page copy** that carry the ranking phrase. Rewriting copy is fine; dropping the phrase is a decision for the client or their SEO agency, not for you.
- **Location and service pages** that exist mainly for local search: same city/region names, same NAP (name, address, phone) as the Google Business profile.

Lengths: titles ≤ 60 characters, descriptions ≤ 155. When carried-over copy from an SEO agency is over the limit, report it and let the client decide. Don't silently trim their work.

Keep the values in content files or one metadata helper (DRY), so the next SEO pass edits data, not components.

## 3. Hotlinks and assets

- `scripts/launch_content.py --legacy-host <old-host>` finds absolute links back to the old domain and `/wp-content/` asset paths. After cutover the WordPress uploads are gone, so every one of those images breaks.
- Download or re-export assets into the repo. Don't hotlink the old CDN.

## 4. Cutover checklist (add to the release plan)

- DNS/TTL lowered a day ahead; who flips it, and when.
- Production env is indexable *only* on the real domain (the staging host stays noindex). Smoke-test both.
- Search Console: property verified for the new deploy, new sitemap submitted, Change of Address only if the domain changes.
- Analytics: the same GA4 property/stream continues, so history isn't split.
- Forms: the production endpoint and recipient list are the client's, tested with a real submission.
- Rollback: the old site stays deployable (don't delete the WordPress host) until the new one has run cleanly for an agreed period.
- After launch: watch 404s (host logs or Search Console coverage) for the first week and add redirects for anything the inventory missed.
