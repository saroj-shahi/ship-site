# Launch essentials (step 1b)

Things a client notices on day one that no linter, type checker or Lighthouse run catches. Each item below has shipped broken or unfinished on a real launch.

## 1. Unfinished content

Run `scripts/launch_content.py <repo> [--legacy-host <old-host>]`. Triage every hit by opening the page it renders on:

| Hit | Severity on a production release |
|---|---|
| `[TBD …]`, "replace before launch", lorem ipsum, "sample/dummy content" rendered on a page | Blocker |
| "To confirm:" or open questions on a legal page | Blocker. Legal copy is the client's call: list the open items, don't write the answers |
| Starter assets (`public/next.svg`, `vercel.svg`), "Create Next App" title | Should-fix (Blocker if it's the visible title or favicon) |
| Stand-in data (`@example.com`, 555 numbers) in a file production imports | Blocker if it renders, else Nice-to-have |
| Hit in a dev-only stand-in, input hint, or code path that never renders | Not a finding. Say why in one line |

**Never invent copy to clear a finding.** A missing bio, an unconfirmed certification, a badge you can't verify, a testimonial: the fix is "remove it or get the real text from <owner>", not a plausible sentence. When you can't confirm a factual claim on the site (partner tier, certification, metric, client name), keep only what a source in the repo or the content doc backs, and list the rest for the user.

Placeholder media counts too: a stock "demo" video, a YouTube link used to show the layout, a hidden-but-routable demo page. Ask whether each is meant to ship.

## 2. Identity and sharing

- **Favicon and app icons** are the brand's, not the create-next-app default (the script flags a 25,931-byte `app/favicon.ico`). `icon.png` / `apple-icon.png` present; manifest icons resolve.
- **OG share image** reflects the *current* hero copy and brand. If the headline changed this release, the image probably needs regenerating. Open it: `curl -sI <og-url>` plus a look at the image.
- Title template is consistent across pages (`%s | Brand` or `%s — Brand`, one form only), defined once in the root layout, not repeated per page.

## 3. Error and edge pages

- `not-found.tsx` (404) styled like the site, with a way back. Unknown paths return a real 404 (the smoke test checks).
- `error.tsx` (segment errors) and `global-error.tsx` (root layout failures; must render its own `<html><body>`).
- Hosting-level 5xx/maintenance page if the host supports one (Amplify custom error pages, Cloudflare/Netlify custom 5xx).
- Pages hidden "for now" (an empty demo page, a removed section) are either `noindex` and unlinked, or deleted. Not half-linked.

## 4. Forms and consent

Collecting personal data needs, before submit:
- A visible notice next to the submit button linking to the privacy policy ("By submitting, you agree to … [Privacy Policy]"), or an unticked consent checkbox where marketing consent is separate. Pre-ticked boxes are not consent under GDPR.
- Required vs optional fields marked consistently (one convention, e.g. asterisk = required, nothing = optional) and matching validation.
- The privacy policy actually describes what the form collects and where it goes (CRM, email provider).
- Non-essential cookies/analytics wait for consent (see analytics.md). If a third-party CMP is planned but not installed, that's a Blocker for EU/UK traffic, not a Nice-to-have. Say so.

## 5. Links

- External links: correct destination, `target="_blank"` with `rel="noopener noreferrer"` if the repo opens them in new tabs. One rule site-wide.
- `mailto:`/`tel:` links use the real, current contact details from the content source.
- No absolute links back to the old site or staging host (`launch_content.py --legacy-host`). On a same-domain replatform they "work" only if the old path exists on the new site, so make them relative and check the smoke test's legacy-URL results.
- Footer and legal links all resolve (the Playwright crawl or smoke routes cover them).

## 6. Layout polish visible at a glance

Check these in the step-8 screenshots, not in source:
- Images fill their containers without distortion (`object-fit: cover` and a fixed aspect ratio). Team photos with different crops are the usual offender.
- No orphaned single words on headings: `text-wrap: balance` on headings, `text-wrap: pretty` on body copy.
- Card grids have even rows at 1440, 1024 and 375 widths.

## 7. Repo hygiene for handover

If the repo is going to a client or another team:
- Docs are the standard set (README, CONTRIBUTING, architecture/design-system docs, CHANGELOG, AGENTS/CLAUDE.md). Internal planning notes, phase plans, AI session notes and pricing discussions belong elsewhere. Flag them; don't delete them.
- Docs describe the stack as it is now: host, package manager, branch names, CI. A doc that still says Vercel when the repo deploys to Amplify is a Should-fix (step 1 checks this).
- `.gitignore` covers `.DS_Store`, `.env*`, `.next/`, `.open-next/`, `.vercel/`, test output, and the lockfiles of package managers the repo doesn't use.
- No unused assets (images nothing references). `grep -rl <basename> src app content` for each file in `public/` is enough for a candidate list.
