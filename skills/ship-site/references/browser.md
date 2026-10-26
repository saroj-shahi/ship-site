# Browser verification protocol (step 8)

The browser is where the silent failures show up: CSP blocks, missing og tags from a merge trap, hydration errors, a form that "succeeds" against a mock. Source reading can't substitute.

## Start the server

Pick the first that works and say which in the step-0 summary:

1. **Built-in preview/browser pane** (e.g. the Claude desktop app's preview tools). If it starts servers from `.claude/launch.json` and that file is missing, create it (name `dev`, `runtimeExecutable` = the package manager, `runtimeArgs` = `["run","dev"]` / `["dev"]`, port 3000) and tell the user you added it — it's a local config file, not part of the release.
2. **Browser MCP** (Chrome DevTools MCP, Playwright MCP) against a dev server you start in the background (`<pm> dev`), so it doesn't block the session.
3. **Playwright script** from the run folder (`npx playwright test <file>` with a `webServer` block, or `chromium.launch()` in a node script). A webapp-testing skill, if installed, wraps this.

The tool names below are generic — map them to whatever your browser tooling calls them (console messages, network requests, evaluate script, screenshot, resize).

## Per route × {desktop 1440×900, mobile 375×812}

1. Navigate. Wait for intro loaders/scroll locks to release (e.g. `document.body` no longer `overflow-hidden`).
2. Read console errors — record every one. Specifically grep for:
   - `Content Security Policy` / `Refused to connect|load|frame|execute` → CSP host missing (cross-check `csp_hosts.py`)
   - `Hydration` / `did not match` → SSR/CSR mismatch
   - `404` / `Failed to load resource`
3. Read network requests — any 4xx/5xx, any request to a host not in the CSP, oversized images (>500KB).
4. Scroll to the bottom (triggers lazy content and reveal animations), check nothing stays invisible.
5. Evaluate in the page: heading outline, images without alt, `document.querySelector('meta[property="og:image"]')?.content`, `meta[name=robots]`.
6. Screenshot → save to `<run>/screenshots/<route-slug>-<desktop|mobile>.png`. Screenshots are the evidence for "looks right" claims.

After the loop, reset the viewport to its default size.

## Contact form end to end

1. Submit empty → every required field shows an error, focus moves to the error summary/first invalid field, errors are announced (`aria-describedby`, `aria-invalid`).
2. Submit invalid email → field-level error.
3. Honeypot: confirm it's not autofilled (inspect value after a browser autofill attempt if possible).
4. Captcha/human check completes.
5. Valid submission on **local** → watch the `POST /api/contact` response. If the upstream is real and would notify a human inbox, ask before sending; otherwise use obviously-test content ("ship-site test — please ignore") and tell the user it was sent.
6. On **staging** (step 12), repeat the real submission. A mocked local success does not prove the backend host/token/CORS are right — a wrong upstream host, a missing server-side token, or a proxy 403 only shows up against the real backend.

## Media

Open the showreel/video modal: plays, controls work, closes with Escape, focus returns. Sound-on-first-play must be checked in a fresh profile (see a11y-perf.md §7).

## What goes in the report

For each route: console error count, network failures, screenshot paths. Any CSP block → finding with the blocked URL, the directive, and the exact `next.config.*` line to change.
