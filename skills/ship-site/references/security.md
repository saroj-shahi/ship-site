# Security checklist (step 4)

Run the `security-review` skill first for the generic pass on the diff. Then these stack-specific checks, across the whole repo (not just the diff — a release ships everything).

## 1. CSP covers every external host

```bash
python3 "$SKILL_DIR/scripts/csp_hosts.py" . --json
```

- `missing` → a host the code calls that the CSP doesn't allow. The browser blocks it **silently** — no build error, the feature just doesn't work. Map each host to the directive it needs (`connect-src` for fetch/XHR/beacons, `img-src`, `script-src`, `frame-src`, `media-src`, `font-src`). Blocker if it breaks a visible feature or analytics; Should-fix otherwise.
- `unused` → allowlisted but never referenced. Nice-to-have removal, unless it's a known runtime-only host (GA sub-hosts, Vimeo CDN wildcards, Iconify fallback APIs `api.simplesvg.com`/`api.unisvg.com`) — note those as intentional.
- The script is a heuristic: hosts built at runtime (template strings, SDKs that fetch internally) won't appear. Confirm against the browser console in step 8.
- Check dev vs prod branches of the CSP: `'unsafe-eval'` must only appear under the dev branch.
- `'unsafe-inline'` in `script-src` is common with GA + Next inline scripts; report as Nice-to-have (nonce migration) unless the user has asked to harden.

## 2. No secrets in `NEXT_PUBLIC_*`

```bash
grep -rn "NEXT_PUBLIC_" src app .env* next.config.* 2>/dev/null
```

Anything named `*_TOKEN`, `*_SECRET`, `*_KEY` (except known-public keys like a GA measurement ID or a public Maps key with referrer restrictions), `*_PASSWORD`, or a backend URL that should be server-side → Blocker. `NEXT_PUBLIC_` values are inlined into the client bundle at build time. Also check `.env` is gitignored and `git ls-files | grep -E '^\.env($|\.)'` only shows `.env.example`.

## 3. Security headers

In `next.config.*` `headers()` (or host config), for `/(.*)`:

| Header | Expect |
|---|---|
| `Content-Security-Policy` | present, `object-src 'none'`, `base-uri 'self'`, `form-action 'self'` |
| `Strict-Transport-Security` | `max-age` ≥ 31536000 |
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` or CSP `frame-ancestors` | `SAMEORIGIN`/`DENY` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` or stricter |
| `Permissions-Policy` | disables unused camera/mic/geolocation |

Verify the live response in step 12 too — hosts can override or strip headers.

## 4. Form endpoints

For every `route.ts` exporting `POST` (and any server action handling user input):

- **Honeypot** — present, and not something autofill will fill (readOnly/uncontrolled, name that matches no autocomplete token). A browser filling a honeypot silently drops real messages behind a success screen.
- **Rate limit** — per-IP, applied before forwarding.
- **Captcha / proof-of-work** — verified server-side; params shared between client and server from one module (a mismatch silently rejects everyone).
- **Body validation** — malformed JSON returns 400, doesn't throw a 500.
- **Upstream timeout** — `AbortSignal.timeout(...)` or equivalent on the forward fetch.
- **Upstream host** — the public API host, not an admin/CMS host. A typical failure: the form posts to `admin.example.com`, whose reverse proxy 403s everything outside an IP allowlist — and serverless/SSR hosts (Amplify, Vercel without Secure Compute) have no static egress IP, so allowlisting can't fix it. Use the public API host with token auth.
- Credentials for the upstream come from non-public env vars — and those vars actually reach the **server runtime** on the host (see hosting.md: Amplify SSR does not pass console env vars to the runtime unless `amplify.yml` writes them into `.env.production`). A build log line like "token not set" is a Blocker candidate, not noise.
- **Cheap checks first.** Order the handler: body-size cap → field length caps → captcha/PoW verify → rate limit → expensive validation (regex) → forward. A regex email check on unbounded input is a ReDoS vector — measure it: time `validate` on a 40k-char crafted email. >100ms → Blocker.
- **Rate-limit key.** If it keys on `x-forwarded-for`, check which hop it reads — the first entry is client-controlled. And an in-memory limiter on serverless/SSR is per instance: it deters, it doesn't stop floods. Report the real guarantee.

These layers stack; none replaces another. Don't "simplify" one away.

## 5. Server-only modules never reach the client

Find modules that must stay server-side: anything importing secrets/`process.env` non-public vars, `node:crypto`, fs, or marked `import "server-only"`. Then:

```bash
grep -rln '"use client"' src app 2>/dev/null | xargs grep -n "@/lib/<module>"
```

Any client component importing a server-only module (directly or via a barrel) → Blocker. Recommend adding `import "server-only"` at the top of those modules so the build enforces it.

## 6. Misc

- `dangerouslySetInnerHTML` — only with trusted/static content (JSON-LD is fine when it's `JSON.stringify` of static data).
- API routes that return data: no internal fields, no stack traces in error responses.
- `yarn audit` / `npm audit --omit=dev` high/critical in production deps → Should-fix (Blocker if exploitable in this app).
