# Hosting differences

Read only the section for the host detected in step 0. Several sections below are written for Next.js (`next.config` headers, `x-nextjs`, SSR runtime); the host mechanics (headers files, preview detection, rollback) hold for other stacks, whose build commands and output are in `frameworks.md`.

## AWS Amplify (`amplify.yml`)

- Branch → environment mapping is set in the Amplify console; conventionally `dev` → staging, `main` → production. Confirm URLs from the repo's instructions file (AGENTS.md, CLAUDE.md, …).
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

## Cloudflare Workers via OpenNext (`wrangler.toml` / `wrangler.jsonc` / `open-next.config.ts`)

- The build command must be `opennextjs-cloudflare build` (often a `<pm> run build:cf` or `preview`/`deploy` script), **not** plain `next build`. A dashboard set to `npm run build` then `npx wrangler deploy` builds fine and then fails with "Could not find compiled Open Next config", because `.open-next/` was never generated. The fix is in the Workers Builds settings, not the code: tell the user the exact build and deploy commands to set.
- Preview detection: an env var set per environment in `wrangler` config (`[env.staging] vars = { APP_ENV = "staging" }`). Check that the noindex signal reads it.
- `*.workers.dev` staging URLs: smoke-test sub-routes, not only `/`. A misconfigured assets binding or `run_worker_first` serves the home page and 404s every nested route.
- Node APIs: the worker runs with `nodejs_compat`. Server code using `fs`, native modules or long-running work fails at request time, not at build. Exercise every API route on staging.
- Headers: `next.config` headers apply via OpenNext. A `_headers` file in the assets dir applies to static assets only. Verify live.
- Deploy status: `npx wrangler deployments list` if logged in, else the smoke script's `--expect-build`.
- Add `.open-next/` and `.wrangler/` to `.gitignore`.

## Other hosts

**Firebase Hosting** (`firebase.json`)
- Headers, redirects and rewrites are set in `firebase.json` (`hosting.headers`, `hosting.redirects`, `hosting.rewrites`).
- Staging: preview channels, `firebase hosting:channel:deploy <channel-id>` (the channel URL is printed; channels expire).
- Rollback: Hosting console → Release history → roll back to a previous release (see rollback.md).

**Azure Static Web Apps** (`staticwebapp.config.json`)
- Headers (`globalHeaders`), `routes`, `responseOverrides` and `navigationFallback` live in `staticwebapp.config.json`.
- Staging: pull requests get their own preview environment from the deploy workflow.
- Rollback: redeploy the last good commit through the workflow, or revert in git.

**Render** (`render.yaml`)
- For static sites, `headers` and `routes` (redirects and rewrites) are set in `render.yaml` or the dashboard.
- Staging: pull request previews if enabled, or a separate service for the staging branch.
- Rollback: dashboard → the service's deploys → roll back to an earlier deploy.

**Fly.io** (`fly.toml`)
- It runs your container, so headers and redirects come from the app or its web server, not `fly.toml`.
- Staging: usually a second app (`fly deploy -a <staging-app>`). Confirm the app names from the repo's docs.
- Rollback: `fly releases` then redeploy the previous image (see rollback.md).

**GitHub Pages** (a deploy workflow in `.github/workflows/`)
- No custom response headers: a CSP has to be a `<meta http-equiv>` tag, and server-side redirects aren't available (use framework redirects or meta refresh).
- No built-in preview: staging is a separate repo, branch or site, or a local build. Check the live URL after the workflow finishes.
- Rollback: re-run the deploy workflow on the last good commit, or revert in git and let it redeploy.

## Unknown host

Say so in the step-0 summary, skip host-specific checks, and ask the user for the staging and production URLs before step 12.
