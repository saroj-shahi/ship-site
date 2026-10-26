# Hosting differences

Read only the section for the host detected in step 0.

## AWS Amplify (`amplify.yml`)

- Branch → environment mapping is set in the Amplify console; conventionally `dev` → staging, `main` → production. Confirm URLs from CLAUDE.md.
- Build env: `AWS_BRANCH` is set on every build → use it for preview detection (`AWS_BRANCH !== "main"` ⇒ noindex).
- `amplify.yml` should run `<pm> install --frozen-lockfile` (yarn) / `npm ci` so the deployed tree matches the lockfile.
- **SSR has no static egress IP.** Any fix that relies on allowlisting the site's outbound IP at an upstream (firewall, nginx allow, a CMS admin host) will not work. Use a public API host with token auth instead.
- Deploy status: no CLI assumed. Poll the staging URL — the smoke script's build-id/`x-nextjs` check or a changed asset hash shows the new deploy is live. Or ask the user to confirm in the console. If `aws amplify list-jobs --app-id … --branch-name dev` works locally, use it.
- **Server runtime env vars.** Amplify console env vars are available at *build* time, but the Next.js SSR runtime (API routes, server components) only sees them if the build writes them out, e.g. in `amplify.yml` build phase: `- env | grep -E '^(API_|SITE_ENV)' >> .env.production` (list the prefixes your server code reads). If a server-only secret is read at request time and `amplify.yml` doesn't do this, the route runs without it in production. Confirm with a real request on staging, not a local build.
- Custom headers can also be set in the Amplify console (`customHttp.yml`) and may override `next.config.ts` headers — the smoke test on the live URL is the source of truth.

## Vercel (`vercel.json` / `.vercel/`)

- Every PR gets a preview URL; `VERCEL_ENV` = `production` | `preview` | `development`. Preview detection: `VERCEL_ENV !== "production"`. Vercel also adds `x-robots-tag: noindex` on `*.vercel.app` previews automatically — custom preview domains don't get it.
- The staging step becomes "verify the PR preview URL" (`gh pr view --json statusCheckRollup` or `vercel ls`); the `dev` branch may not exist — use the repo's flow.
- Production deploy = merge to the production branch (or `vercel --prod`, ask first). Use the `vercel:*` skills for env/deploy status if available.
- Static egress IPs require Secure Compute — same caveat as Amplify by default.
- No staging branch: the release flow in release.md collapses to feature PR (preview) → `main`. Bump the version on the feature branch before merge, or on `main` via its own PR — match the repo's history.

## Netlify (`netlify.toml`)

- `CONTEXT` = `production` | `deploy-preview` | `branch-deploy`. Preview detection: `CONTEXT !== "production"`.
- Deploy previews at `deploy-preview-<n>--<site>.netlify.app`; branch deploys at `<branch>--<site>.netlify.app`.
- Headers can come from `netlify.toml` `[[headers]]` or `_headers` and may merge with Next's — verify live.
- `netlify status` / `netlify api listSiteDeploys` for deploy state if the CLI is logged in.

## Unknown host

Say so in the step-0 summary, skip host-specific checks, and ask the user for the staging and production URLs before step 12.
