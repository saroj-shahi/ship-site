#!/usr/bin/env python3
"""Read a site repo once and print the facts every ship-site step depends on.

Step 0 used to be a dozen shell commands and judgment calls per run: which
framework, which package manager, which host, which branch is staging, where the
site lives in a monorepo, which routes exist, which gate scripts to run. Getting
one wrong (a stale package-lock.json in a pnpm repo, a route group leaking into a
URL, the wrong base branch) poisons every later step. This does it deterministically.

Usage:
  detect.py [repo_dir] [--app apps/web] [--json] [--state <run_dir>/state.json]

Frameworks recognised (see references/frameworks.md for what changes per stack):
  Next.js, Astro, Nuxt, SvelteKit, Remix, React Router (framework mode), Gatsby,
  Angular, Eleventy, Create React App, Vite SPAs (React/Vue/Svelte/Solid/Preact),
  Hugo, Jekyll, plain static HTML; Django, Rails, Laravel and WordPress are named
  but their routes come from crawling the running site.

Reports:
  app          where the site lives (repo root, or the workspace package that
               depends on a site framework); several candidates → pass --app
  framework    name, version, router style, pages dir, config file, dev port,
               build output dir, public env-var prefixes, default build/dev command
  pm           JS package manager and how it was decided, plus stale lockfiles
  hosts        Amplify / Vercel / Netlify / Cloudflare / Firebase / Azure SWA /
               Render / Fly / GitHub Pages config found
  git          remote host, current branch, base (staging) and production branch,
               HEAD sha, and whether the local base is behind its remote ref
  scripts      the gate, test, host-build and release scripts that exist
  routes       URL per page file, using the framework's own conventions; dynamic
               segments flagged for expansion; `routes_source` says how they were found
  app_files    404 / error page, sitemap, robots, favicon (plus Next's app files)
  docs         instructions files present, staging/production URLs mentioned in
               them, and replatform hints (WordPress, cutover, "replace the live site")
  previous     earlier .ship-site run folders and whether one is unfinished

Read-only and offline: it never fetches, installs or writes, except the state
file when --state is given (merged in place; existing keys are kept).
Exit 0 = site framework recognised, 1 = none recognised (framework-neutral steps
only, or several apps: pass --app), 2 = not a directory / bad --app.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

JS_EXT = {".tsx", ".ts", ".jsx", ".js", ".mjs", ".cjs"}
PAGE_EXT = {".tsx", ".ts", ".jsx", ".js", ".mdx", ".md"}
LOCKFILES = (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"), ("bun.lock", "bun"),
             ("bun.lockb", "bun"), ("package-lock.json", "npm"))
HOSTS = (("amplify.yml", "AWS Amplify"), ("vercel.json", "Vercel"), (".vercel", "Vercel"),
         ("netlify.toml", "Netlify"), ("wrangler.toml", "Cloudflare Workers"),
         ("wrangler.jsonc", "Cloudflare Workers"), ("wrangler.json", "Cloudflare Workers"),
         ("open-next.config.ts", "Cloudflare Workers"), ("firebase.json", "Firebase Hosting"),
         ("staticwebapp.config.json", "Azure Static Web Apps"), ("render.yaml", "Render"),
         ("fly.toml", "Fly.io"))
INSTRUCTIONS = ("AGENTS.md", "CLAUDE.md", "GEMINI.md", ".github/copilot-instructions.md",
                ".cursor/rules", "README.md", "CONTRIBUTING.md")
STAGING_BRANCHES = ("dev", "develop", "staging")
NEXT_APP_FILES = {"not-found": "not-found", "error": "error", "global-error": "global-error",
                  "sitemap": "sitemap", "robots": "robots", "manifest": "manifest",
                  "opengraph-image": "opengraph-image", "icon": "icon", "apple-icon": "apple-icon"}
SKIP_DIRS = {"node_modules", ".git", ".next", ".nuxt", ".output", ".svelte-kit", ".astro", ".vercel",
             ".netlify", ".open-next", ".cache", "dist", "build", "out", "_site", "coverage", "vendor",
             "resources", ".turbo"}
URL_RE = re.compile(r"https?://[^\s)\"'<>`\]]+")
URL_SKIP = re.compile(r"(github\.com|githubusercontent|shields\.io|localhost|127\.0\.0\.1|example\.(com|org)"
                      r"|nextjs\.org|vercel\.com/docs|npmjs\.|schema\.org|w3\.org|bitbucket\.org|gitlab\.com"
                      r"|keepachangelog|semver\.org|conventionalcommits|astro\.build|nuxt\.com|svelte\.dev"
                      r"|remix\.run|reactrouter\.com|gatsbyjs\.com|angular\.dev|11ty\.dev|gohugo\.io|jekyllrb\.com)", re.I)
STAGING_WORDS = re.compile(r"\b(staging|stage|preview|uat|qa|dev)\b", re.I)
PROD_WORDS = re.compile(r"\b(production|prod|live)\b", re.I)
REPLATFORM = re.compile(r"\b(re-?platform\w*|cut-?over|wordpress|wix|squarespace|webflow|legacy site|old site"
                        r"|replac\w* the (live|existing|old|current) (site|website))\b", re.I)

# name: label, package deps that identify it (first match wins, in this order), config files,
# dev port, build output, public env-var prefixes (anything with these ships to the browser),
# and the build/dev command to use when package.json has no script for it.
FRAMEWORKS: dict[str, dict] = {
    "next": dict(label="Next.js", deps=("next",), port=3000, output=".next (out/ with output: 'export')",
                 configs=("next.config.ts", "next.config.mjs", "next.config.js", "next.config.cjs"),
                 env=("NEXT_PUBLIC_",), build="next build", dev="next dev"),
    "astro": dict(label="Astro", deps=("astro",), port=4321, output="dist",
                  configs=("astro.config.mjs", "astro.config.ts", "astro.config.js", "astro.config.cjs"),
                  env=("PUBLIC_",), build="astro build", dev="astro dev"),
    "nuxt": dict(label="Nuxt", deps=("nuxt", "nuxt3"), port=3000, output=".output (nuxt generate: .output/public)",
                 configs=("nuxt.config.ts", "nuxt.config.js", "nuxt.config.mjs"),
                 env=("NUXT_PUBLIC_",), build="nuxt build", dev="nuxt dev"),
    "sveltekit": dict(label="SvelteKit", deps=("@sveltejs/kit",), port=5173, output="build (depends on the adapter)",
                      configs=("svelte.config.js", "svelte.config.mjs", "svelte.config.ts"),
                      env=("PUBLIC_",), build="vite build", dev="vite dev"),
    "react-router": dict(label="React Router (framework mode)", deps=("@react-router/dev",), port=5173,
                         output="build/client + build/server",
                         configs=("react-router.config.ts", "react-router.config.js", "app/routes.ts"),
                         env=("VITE_",), build="react-router build", dev="react-router dev"),
    "remix": dict(label="Remix", deps=("@remix-run/dev", "@remix-run/react"), port=5173, output="build",
                  configs=("vite.config.ts", "vite.config.js", "vite.config.mts", "remix.config.js"),
                  env=("VITE_",), build="remix vite:build", dev="remix vite:dev"),
    "gatsby": dict(label="Gatsby", deps=("gatsby",), port=8000, output="public",
                   configs=("gatsby-config.ts", "gatsby-config.js", "gatsby-config.mjs"),
                   env=("GATSBY_",), build="gatsby build", dev="gatsby develop"),
    "angular": dict(label="Angular", deps=("@angular/core",), port=4200, output="dist/<project>",
                    configs=("angular.json",), env=(), build="ng build", dev="ng serve"),
    "eleventy": dict(label="Eleventy", deps=("@11ty/eleventy",), port=8080, output="_site",
                     configs=("eleventy.config.js", "eleventy.config.mjs", "eleventy.config.cjs",
                              "eleventy.config.ts", ".eleventy.js"),
                     env=(), build="npx @11ty/eleventy", dev="npx @11ty/eleventy --serve"),
    "cra": dict(label="Create React App", deps=("react-scripts",), port=3000, output="build",
                configs=(), env=("REACT_APP_",), build="react-scripts build", dev="react-scripts start"),
    "vite": dict(label="Vite", deps=("vite",), port=5173, output="dist",
                 configs=("vite.config.ts", "vite.config.js", "vite.config.mjs", "vite.config.mts"),
                 env=("VITE_",), build="vite build", dev="vite"),
    # Detected from files, not package.json.
    "hugo": dict(label="Hugo", deps=(), port=1313, output="public",
                 configs=("hugo.toml", "hugo.yaml", "hugo.yml", "hugo.json", "config.toml", "config.yaml", "config.yml"),
                 env=(), build="hugo --gc --minify", dev="hugo server"),
    "jekyll": dict(label="Jekyll", deps=(), port=4000, output="_site", configs=("_config.yml", "_config.yaml"),
                   env=(), build="bundle exec jekyll build", dev="bundle exec jekyll serve"),
    "static": dict(label="Static HTML", deps=(), port=None, output="(the files themselves)", configs=(),
                   env=(), build=None, dev="npx serve <dir>"),
    "django": dict(label="Django", deps=(), port=8000, output=None, configs=("manage.py",), env=(),
                   build=None, dev="python manage.py runserver"),
    "rails": dict(label="Rails", deps=(), port=3000, output=None, configs=("config/routes.rb",), env=(),
                  build=None, dev="bin/rails server"),
    "laravel": dict(label="Laravel", deps=(), port=8000, output=None, configs=("artisan",), env=(),
                    build=None, dev="php artisan serve"),
    "wordpress": dict(label="WordPress", deps=(), port=None, output=None, configs=("wp-config.php",), env=(),
                      build=None, dev=None),
}
JS_FRAMEWORKS = [k for k, v in FRAMEWORKS.items() if v["deps"]]
META_FRAMEWORKS = [k for k in JS_FRAMEWORKS if k != "vite"]  # a bare vite dep is common in non-site packages
VITE_FLAVOURS = (("react", "React"), ("vue", "Vue"), ("svelte", "Svelte"), ("solid-js", "Solid"),
                 ("preact", "Preact"), ("lit", "Lit"))


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def read_text(path: Path, limit: int = 200_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def git(root: Path, *args: str) -> str | None:
    try:
        res = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return res.stdout.strip() if res.returncode == 0 else None


def deps(pkg: dict) -> dict:
    out = {}
    for k in ("dependencies", "devDependencies", "peerDependencies"):
        out.update(pkg.get(k) or {})
    return out


def walk(base: Path, skip: set[str] = SKIP_DIRS, limit: int = 5000):
    """Files under base, skipping dependency, build and dot folders."""
    n = 0
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(x for x in dirnames if x not in skip and not x.startswith("."))
        for name in sorted(filenames):
            yield Path(dirpath) / name
            n += 1
            if n >= limit:
                return


# ---------------------------------------------------------------- framework

def js_framework(pkg: dict, names=JS_FRAMEWORKS) -> str | None:
    d = deps(pkg)
    return next((n for n in names if any(dep in d for dep in FRAMEWORKS[n]["deps"])), None)


def file_framework(app: Path) -> str | None:
    """Stacks recognised from files rather than package.json deps."""
    strict = any((app / c).is_file() for c in FRAMEWORKS["hugo"]["configs"][:4])  # hugo.*
    loose = any((app / c).is_file() for c in FRAMEWORKS["hugo"]["configs"][4:])  # config.* is generic
    if strict or (loose and ((app / "archetypes").is_dir() or (app / "themes").is_dir()
                             or ((app / "layouts").is_dir() and (app / "content").is_dir()))):
        return "hugo"
    if any((app / c).is_file() for c in FRAMEWORKS["jekyll"]["configs"]) and (
            "jekyll" in read_text(app / "Gemfile") or any((app / d).is_dir() for d in ("_layouts", "_posts", "_includes"))):
        return "jekyll"
    if (app / "manage.py").is_file():
        return "django"
    if (app / "config" / "routes.rb").is_file():
        return "rails"
    if (app / "artisan").is_file():
        return "laravel"
    if (app / "wp-config.php").is_file() or (app / "wp-content").is_dir() or \
            "Theme Name:" in read_text(app / "style.css", 2000):
        return "wordpress"
    if static_root(app):
        return "static"
    return None


def static_root(app: Path) -> Path | None:
    for d in (app, app / "public", app / "site", app / "www", app / "src", app / "docs"):
        if (d / "index.html").is_file():
            return d
    return None


# ---------------------------------------------------------------- app location

def workspace_globs(root: Path, pkg: dict) -> list[str]:
    ws = pkg.get("workspaces")
    globs = list(ws.get("packages") or []) if isinstance(ws, dict) else list(ws or [])
    pnpm = root / "pnpm-workspace.yaml"
    if pnpm.exists():
        for line in pnpm.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"\s*-\s*['\"]?([^'\"#]+?)['\"]?\s*(#.*)?$", line)
            if m and not m.group(1).startswith("!"):
                globs.append(m.group(1).strip())
    return globs


def find_app(root: Path, pkg: dict) -> tuple[Path | None, list[str], bool]:
    """Return (app root, candidates, is_monorepo)."""
    globs = workspace_globs(root, pkg)
    monorepo = bool(globs) or (root / "turbo.json").exists() or (root / "nx.json").exists()
    if js_framework(pkg, META_FRAMEWORKS):
        return root, [], monorepo
    if not globs and monorepo:
        globs = ["apps/*", "packages/*"]
    meta, vite_only = [], []
    for g in globs:
        for d in sorted(root.glob(g.rstrip("/").removesuffix("/**"))):
            if not d.is_dir() or "node_modules" in d.parts:
                continue
            sub = read_json(d / "package.json")
            rel = d.relative_to(root).as_posix()
            bucket = meta if js_framework(sub, META_FRAMEWORKS) else \
                vite_only if js_framework(sub) and (d / "index.html").is_file() else None
            if bucket is not None and rel not in bucket:
                bucket.append(rel)
    candidates = meta or vite_only
    if len(candidates) == 1:
        return root / candidates[0], candidates, monorepo
    if not candidates:
        return root, [], monorepo  # the root itself: a Vite SPA, Hugo, Jekyll, static HTML… decided later
    return None, candidates, monorepo


# ---------------------------------------------------------------- facts

def package_manager(root: Path, app: Path, pkg: dict) -> dict:
    found = []
    for base in dict.fromkeys((root, app)):
        found += [(name, pm) for name, pm in LOCKFILES if (base / name).exists()]
    if not found and not (root / "package.json").exists() and not (app / "package.json").exists():
        return {"name": None, "source": "no package.json", "stale_lockfiles": []}
    declared = str(pkg.get("packageManager") or "").split("@")[0] or None
    if declared:
        pm, source = declared, "packageManager field"
    elif found:
        pm, source = found[0][1], f"lockfile {found[0][0]}"
    else:
        pm, source = "npm", "default (no lockfile)"
    stale = sorted({name for name, other in found if other != pm})
    return {"name": pm, "source": source, "stale_lockfiles": stale}


def hosts(root: Path, app: Path) -> list[str]:
    seen = []
    for base in dict.fromkeys((app, root)):
        for name, host in HOSTS:
            if (base / name).exists() and host not in seen:
                seen.append(host)
    wf = root / ".github" / "workflows"
    if wf.is_dir() and any(re.search(r"actions/deploy-pages|peaceiris/actions-gh-pages|JamesIves/github-pages-deploy",
                                     read_text(f)) for f in wf.glob("*.y*ml")):
        seen.append("GitHub Pages")
    return seen


def git_facts(root: Path) -> dict:
    if git(root, "rev-parse", "--is-inside-work-tree") != "true":
        return {"repo": False}
    remote = git(root, "remote", "get-url", "origin") or ""
    host = ("github" if "github.com" in remote else "bitbucket" if "bitbucket.org" in remote
            else "gitlab" if "gitlab" in remote else "other" if remote else "none")

    def exists(ref: str) -> bool:
        return git(root, "rev-parse", "--verify", "--quiet", ref) is not None

    head = git(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    default = head.split("/", 1)[1] if head and "/" in head else next(
        (b for b in ("main", "master") if exists(f"refs/heads/{b}") or exists(f"refs/remotes/origin/{b}")), None)
    staging = next((b for b in STAGING_BRANCHES
                    if exists(f"refs/heads/{b}") or exists(f"refs/remotes/origin/{b}")), None)
    base = staging or default
    behind = None
    if base and exists(f"refs/heads/{base}") and exists(f"refs/remotes/origin/{base}"):
        n = git(root, "rev-list", "--count", f"{base}..origin/{base}")
        behind = int(n) if n and n.isdigit() else None
    return {"repo": True, "remote": remote or None, "host": host, "branch": git(root, "branch", "--show-current"),
            "head_sha": git(root, "rev-parse", "--short", "HEAD"), "production_branch": default,
            "staging_branch": staging, "base": base, "base_behind_remote": behind,
            "dirty": bool(git(root, "status", "--porcelain")), "last_tag": git(root, "describe", "--tags", "--abbrev=0")}


def scripts(pkg: dict, root_pkg: dict) -> dict:
    s = {**(root_pkg.get("scripts") or {}), **(pkg.get("scripts") or {})}

    def first(*names):
        return next((n for n in names if n in s), None)

    host_build = [n for n, cmd in s.items() if "opennextjs-cloudflare" in str(cmd) or n in ("build:cf", "cf:build")]
    return {
        "aggregate": first("ci", "verify", "check", "validate"),
        "lint": first("lint"),
        "format_check": first("format:check", "prettier:check", "fmt:check", "format-check"),
        "typecheck": first("typecheck", "type-check", "tsc", "types", "check-types", "astro:check", "check:types"),
        "build": first("build"),
        "unit_test": first("test", "test:unit"),
        "e2e": first("test:e2e", "e2e", "playwright", "test:playwright"),
        "host_build": host_build[0] if host_build else None,
        "release": sorted(n for n in s if n.startswith("release")),
    }


# ---------------------------------------------------------------- routes

def front_matter(path: Path) -> dict[str, str]:
    """Top-level scalar keys of YAML (---) or TOML (+++) front matter, good enough for url/permalink/draft."""
    text = read_text(path, 8000)
    m = re.match(r"\A(---|\+\+\+)\s*\n(.*?)\n\1\s*(\n|\Z)", text, re.S)
    if not m:
        return {}
    out = {}
    for line in m.group(2).splitlines():
        kv = re.match(r"([A-Za-z_][\w-]*)\s*[:=]\s*(.*)$", line)
        if kv:
            out[kv.group(1).lower()] = kv.group(2).strip().strip("'\"")
    return out


def next_page_url(parts: tuple[str, ...]) -> str | None:
    if any(p.startswith("_") or p.startswith("(.") for p in parts):
        return None  # private folder or intercepting route
    segs = [p for p in parts if not (p.startswith("(") and p.endswith(")")) and not p.startswith("@")]
    return "/" + "/".join(segs)


def first_dir(app: Path, *names: str) -> Path | None:
    return next((app / n for n in names if (app / n).is_dir()), None)


def add(found: dict, url: str, file: Path, app: Path, router: str) -> None:
    url = re.sub(r"/+", "/", url)
    if re.sub(r"(\.html?|/)$", "", url) in ("/404", "/500"):
        return  # error pages, reported under app_files
    found.setdefault(url, {"url": url, "file": file.relative_to(app).as_posix(), "router": router})


def routes_next(app: Path, found: dict) -> tuple[str | None, Path | None]:
    app_dir = first_dir(app, "src/app", "app")
    pages_dir = first_dir(app, "src/pages", "pages")
    if app_dir:
        for p in sorted(app_dir.rglob("page.*")):
            if p.suffix not in PAGE_EXT or "node_modules" in p.parts:
                continue
            url = next_page_url(p.parent.relative_to(app_dir).parts)
            if url:
                add(found, url, p, app, "app")
    if pages_dir:
        for p in sorted(pages_dir.rglob("*")):
            rel = p.relative_to(pages_dir)
            if p.suffix not in PAGE_EXT or not p.is_file() or rel.parts[0] == "api" \
                    or any(x.startswith("_") for x in rel.parts):
                continue
            parts = list(rel.with_suffix("").parts)
            if parts[-1] == "index":
                parts.pop()
            add(found, "/" + "/".join(parts), p, app, "pages")
    router = "both" if app_dir and pages_dir else "app" if app_dir else "pages" if pages_dir else None
    return router, app_dir or pages_dir


def routes_dir(app: Path, found: dict, d: Path | None, exts: set[str], router: str,
               groups: bool = False) -> Path | None:
    """Plain file-system routing: path = URL, index = folder, _x = private, (x) = group."""
    if not d:
        return None
    for p in walk(d):
        rel = p.relative_to(d)
        if p.suffix not in exts or any(x.startswith("_") for x in rel.parts) or \
                any(s in p.name for s in (".test.", ".spec.", ".stories.")):
            continue
        parts = list(rel.with_suffix("").parts)
        if parts[-1] == "index":
            parts.pop()
        if groups:
            parts = [x for x in parts if not (x.startswith("(") and x.endswith(")"))]
        add(found, "/" + "/".join(parts), p, app, router)
    return d


def routes_sveltekit(app: Path, found: dict) -> Path | None:
    d = first_dir(app, "src/routes")
    if d:
        for p in walk(d):
            if p.name.startswith("+page.") and p.suffix in (".svelte", ".md", ".svx"):
                parts = [x for x in p.parent.relative_to(d).parts if not (x.startswith("(") and x.endswith(")"))]
                add(found, "/" + "/".join(parts), p, app, "file")
    return d


def flat_route_url(name: str) -> str:
    """Remix / React Router flat-routes file name → URL (`blog.$slug` → /blog/:slug)."""
    segs = []
    for seg in re.split(r"\.(?![^\[]*\])", name):
        if seg.startswith("_"):
            continue  # index route, or pathless layout
        seg = seg[:-1] if seg.endswith("_") else seg
        opt = seg.startswith("(") and seg.endswith(")")
        seg = seg.strip("()").replace("[", "").replace("]", "")
        seg = "*" if seg == "$" else ":" + seg[1:] if seg.startswith("$") else seg
        segs.append(seg + "?" if opt else seg)
    return "/" + "/".join(segs)


def routes_flat(app: Path, found: dict, router: str) -> Path | None:
    d = first_dir(app, "app/routes")
    if not d:
        return None
    for p in sorted(d.iterdir()):
        if p.is_dir():
            f = next((x for n in ("route", "index") for x in sorted(p.glob(f"{n}.*")) if x.suffix in JS_EXT | {".mdx"}), None)
            name = p.name
        else:
            f, name = (p, p.name.rsplit(".", 1)[0]) if p.suffix in JS_EXT | {".mdx", ".md"} else (None, "")
        if f and (f.suffix in (".md", ".mdx") or "export default" in read_text(f)):  # no default export = resource route
            add(found, flat_route_url(name), f, app, router)
    return d


def routes_react_router(app: Path, found: dict) -> tuple[str, Path | None]:
    cfg = app / "app" / "routes.ts"
    text = read_text(cfg)
    if not text or "flatRoutes" in text:
        return "file", routes_flat(app, found, "file")
    for m in re.finditer(r"\b(index|route)\(\s*(?:[\"'`]([^\"'`]*)[\"'`]\s*,\s*)?[\"'`]([^\"'`]+)[\"'`]", text):
        url = "/" if m.group(1) == "index" else "/" + (m.group(2) or "").lstrip("/")
        found.setdefault(url, {"url": url, "file": m.group(3), "router": "config"})
    return "config", cfg


def routes_client(app: Path, found: dict) -> str:
    """SPA routers (React Router, Vue Router, Angular, Svelte routers): best-effort scan of path literals."""
    src = first_dir(app, "src") or app
    pats = (re.compile(r"\bpath\s*:\s*[\"'`](/?[\w\-/:.*]*)[\"'`]"),
            re.compile(r"<Route\b[^>]*?\bpath=[\"'{`]+(/?[\w\-/:.*]*)"))
    for f in walk(src):
        if f.suffix not in JS_EXT | {".vue", ".svelte"} or any(s in f.name for s in (".test.", ".spec.", ".stories.")):
            continue
        text = read_text(f)
        if "path" not in text:
            continue
        for rx in pats:
            for m in rx.finditer(text):
                path = m.group(1)
                if path in ("*", "**", "/*") or path.startswith("."):
                    continue
                add(found, "/" + path.lstrip("/"), f, app, "client")
    found.setdefault("/", {"url": "/", "file": "index.html", "router": "client"})
    return "client router (best effort: nested child paths are not joined to their parent)"


def routes_eleventy(app: Path, found: dict, cfg: Path | None) -> Path:
    m = re.search(r"\binput\s*:\s*[\"'`]([^\"'`]+)", read_text(cfg)) if cfg else None
    d = (app / m.group(1)).resolve() if m else app
    exts = {".njk", ".md", ".html", ".liquid", ".webc", ".hbs", ".pug", ".ejs", ".haml", ".mustache"}
    for p in walk(d):
        rel = p.relative_to(d)
        is_js = p.name.endswith((".11ty.js", ".11ty.cjs", ".11ty.mjs"))
        if not (p.suffix in exts or is_js) or any(x.startswith("_") for x in rel.parts) or \
                (len(rel.parts) == 1 and p.stem.upper() in ("README", "CHANGELOG", "LICENSE", "CONTRIBUTING")):
            continue
        fm = front_matter(p)
        link = fm.get("permalink")
        if link in ("false", "False"):
            continue
        stem = p.name.split(".")[0]
        parts = list(rel.parent.parts) + ([] if stem == "index" else [stem])
        url = link if link and link.startswith("/") else "/" + "/".join(parts) + ("/" if parts else "")
        add(found, url, p, app, "file")
        if "pagination" in fm or "{{" in url:
            found[re.sub(r"/+", "/", url)]["dynamic"] = True
    return d


def routes_hugo(app: Path, found: dict) -> Path | None:
    d = first_dir(app, "content")
    found.setdefault("/", {"url": "/", "file": "layouts/index.html", "router": "content"})
    if not d:
        return None
    for p in walk(d):
        if p.suffix not in (".md", ".markdown", ".html", ".adoc"):
            continue
        fm = front_matter(p)
        if fm.get("draft", "").lower() == "true":
            continue
        rel = p.relative_to(d)
        parts = list(rel.parent.parts)
        if p.stem not in ("_index", "index"):
            parts.append(fm.get("slug") or p.stem)
        url = fm.get("url") or ("/" + "/".join(parts) + "/" if parts else "/")
        add(found, url.lower(), p, app, "content")
    return d


def routes_jekyll(app: Path, found: dict) -> Path:
    for p in walk(app):
        rel = p.relative_to(app)
        if p.suffix not in (".md", ".markdown", ".html") or any(x.startswith("_") for x in rel.parts):
            continue
        if not read_text(p, 4).startswith("---"):
            continue  # Jekyll only renders files with front matter
        fm = front_matter(p)
        parts = list(rel.parent.parts)
        url = fm.get("permalink") or ("/" + "/".join(parts) + ("/" if parts else "") if p.stem == "index"
                                      else "/" + "/".join(parts + [p.stem + ".html"]))
        add(found, url, p, app, "file")
    posts = app / "_posts"
    if posts.is_dir() and any(posts.iterdir()):
        found["/:year/:month/:day/:title.html"] = {"url": "/:year/:month/:day/:title.html", "file": "_posts",
                                                   "router": "collection"}
    return app


def routes_static(app: Path, found: dict) -> Path | None:
    d = static_root(app)
    if d:
        for p in walk(d):
            if p.suffix in (".html", ".htm"):
                rel = p.relative_to(d)
                url = "/" + rel.parent.as_posix().strip(".") + "/" if p.stem == "index" else "/" + rel.as_posix()
                add(found, url, p, app, "file")
    return d


def routes(app: Path, fw: str | None, cfg: Path | None) -> tuple[str | None, str | None, str, list[dict]]:
    """Return (router style, pages dir relative to app, how routes were found, routes)."""
    found: dict[str, dict] = {}
    source = "file system"
    router: str | None = "file"
    if fw == "next":
        router, d = routes_next(app, found)
    elif fw == "astro":
        d = routes_dir(app, found, first_dir(app, "src/pages"), {".astro", ".md", ".mdx", ".html"}, "file")
    elif fw == "nuxt":
        d = routes_dir(app, found, first_dir(app, "app/pages", "pages", "src/pages"), {".vue", ".tsx", ".jsx"}, "file",
                       groups=True)
        if not d:
            router, source = "single page (app.vue, no pages/)", "app.vue"
            found["/"] = {"url": "/", "file": "app.vue", "router": "file"}
    elif fw == "sveltekit":
        d = routes_sveltekit(app, found)
    elif fw == "remix":
        d = routes_flat(app, found, "file")
    elif fw == "react-router":
        router, d = routes_react_router(app, found)
        source = "app/routes.ts (best effort)" if router == "config" else source
    elif fw == "gatsby":
        d = routes_dir(app, found, first_dir(app, "src/pages"), JS_EXT | {".mdx"}, "file")
    elif fw in ("vite", "cra", "angular"):
        router, d, source = "client", None, routes_client(app, found)
    elif fw == "eleventy":
        d = routes_eleventy(app, found, cfg)
    elif fw == "hugo":
        router, source, d = "content", "content/ (front matter url/slug honoured)", routes_hugo(app, found)
    elif fw == "jekyll":
        d = routes_jekyll(app, found)
    elif fw == "static":
        d = routes_static(app, found)
    else:
        router, d, source = None, None, "crawl the running site (no file-based routes for this stack)"
    for r in found.values():
        r["dynamic"] = r.get("dynamic") or bool(re.search(r"[\[{:*]", r["url"]))
    rel = None
    if d:
        try:
            rel = d.relative_to(app).as_posix()
        except ValueError:
            rel = str(d)
    return router, rel, source, sorted(found.values(), key=lambda r: (r["url"].count("/"), r["url"]))


# ---------------------------------------------------------------- app files

# Per framework: each key passes if any pattern matches. Patterns are globs relative to
# the app, "dep:<pkg>" (package.json dependency), "text:<glob>:<needle>" or "builtin".
APP_CHECKS: dict[str, dict[str, list[str]]] = {
    "astro": {"not-found": ["src/pages/404.*"], "error": ["src/pages/500.*"],
              "sitemap": ["dep:@astrojs/sitemap", "src/pages/sitemap*", "public/sitemap.xml"],
              "robots": ["public/robots.txt", "src/pages/robots.txt.*", "dep:astro-robots-txt"],
              "favicon": ["public/favicon.*"]},
    "nuxt": {"not-found": ["error.vue", "app/error.vue"], "error": ["error.vue", "app/error.vue"],
             "sitemap": ["dep:@nuxtjs/sitemap", "dep:@nuxtjs/seo", "dep:nuxt-simple-sitemap",
                         "server/routes/sitemap*", "public/sitemap.xml"],
             "robots": ["dep:@nuxtjs/robots", "dep:@nuxtjs/seo", "dep:nuxt-simple-robots",
                        "public/robots.txt", "server/routes/robots*"],
             "favicon": ["public/favicon.*"]},
    "sveltekit": {"not-found": ["src/routes/+error.svelte"], "error": ["src/routes/+error.svelte", "src/error.html"],
                  "sitemap": ["src/routes/sitemap.xml/+server.*", "static/sitemap.xml", "dep:super-sitemap",
                              "dep:svelte-sitemap"],
                  "robots": ["static/robots.txt", "src/routes/robots.txt/+server.*"],
                  "favicon": ["static/favicon.*"]},
    "remix": {"not-found": ["app/routes/$.*", "app/routes/$/route.*", "app/routes/[$]*"],
              "error": ["text:app/root.*:ErrorBoundary"],
              "sitemap": ["app/routes/sitemap[[].[]]xml*", "public/sitemap.xml", "dep:remix-sitemap"],
              "robots": ["public/robots.txt", "app/routes/robots[[].[]]txt*"],
              "favicon": ["public/favicon.*"]},
    "gatsby": {"not-found": ["src/pages/404.*"],
               "sitemap": ["dep:gatsby-plugin-sitemap", "static/sitemap.xml"],
               "robots": ["dep:gatsby-plugin-robots-txt", "static/robots.txt"],
               "favicon": ["static/favicon.*", "dep:gatsby-plugin-manifest"]},
    "spa": {"not-found": ["public/404.html", "src/**/*NotFound*", "src/**/*not-found*", "src/**/*404*"],
            "sitemap": ["public/sitemap.xml", "src/sitemap.xml", "dep:vite-plugin-sitemap"],
            "robots": ["public/robots.txt", "src/robots.txt"],
            "favicon": ["public/favicon.*", "src/favicon.*", "favicon.*"]},
    "eleventy": {"not-found": ["{in}/404.*"], "sitemap": ["{in}/sitemap*", "dep:@quasibit/eleventy-plugin-sitemap"],
                 "robots": ["{in}/robots*"], "favicon": ["{in}/favicon.*", "{in}/*/favicon.*"]},
    "hugo": {"not-found": ["layouts/404.html", "themes/*/layouts/404.html"], "sitemap": ["builtin"],
             "robots": ["static/robots.txt", "layouts/robots.txt", "text:hugo.*:enableRobotsTXT",
                        "text:config.*:enableRobotsTXT"],
             "favicon": ["static/favicon.*", "assets/favicon.*", "static/*/favicon.*"]},
    "jekyll": {"not-found": ["404.*"], "sitemap": ["text:Gemfile:jekyll-sitemap", "text:_config.y*ml:jekyll-sitemap",
                                                   "sitemap.xml"],
               "robots": ["robots.txt"], "favicon": ["favicon.*", "assets/favicon.*", "assets/*/favicon.*"]},
    "static": {"not-found": ["{in}/404.html"], "sitemap": ["{in}/sitemap.xml"], "robots": ["{in}/robots.txt"],
               "favicon": ["{in}/favicon.*"]},
}
APP_CHECKS["react-router"] = APP_CHECKS["remix"]
for _k in ("vite", "cra", "angular"):
    APP_CHECKS[_k] = APP_CHECKS["spa"]


def check(app: Path, pkg_deps: dict, pattern: str, in_dir: str) -> bool:
    if pattern == "builtin":
        return True
    if pattern.startswith("dep:"):
        return pattern[4:] in pkg_deps
    if pattern.startswith("text:"):
        _, glob, needle = pattern.split(":", 2)
        return any(needle in read_text(f) for f in app.glob(glob) if f.is_file())
    return any(app.glob(pattern.replace("{in}", in_dir)))


def app_files(app: Path, fw: str | None, pages_dir: str | None, pkg: dict) -> dict:
    if fw == "next":
        if not pages_dir or not pages_dir.endswith("app"):
            return {}
        d = app / pages_dir
        out = {key: any(d.glob(f"{stem}.*")) for key, stem in NEXT_APP_FILES.items()}
        out["favicon"] = (d / "favicon.ico").exists() or (app / "public" / "favicon.ico").exists()
        return out
    checks = APP_CHECKS.get(fw or "")
    if not checks:
        return {}
    in_dir = pages_dir if fw in ("eleventy", "static") and pages_dir else "."
    d = deps(pkg)
    return {key: any(check(app, d, p, in_dir) for p in pats) for key, pats in checks.items()}


# ---------------------------------------------------------------- docs and runs

def docs(root: Path, app: Path) -> dict:
    files = []
    for base in dict.fromkeys((root, app)):
        for name in INSTRUCTIONS:
            p = base / name
            if p.is_file():
                files.append(p)
            elif p.is_dir():
                files += sorted(x for x in p.rglob("*") if x.is_file())[:20]
        if (base / "docs").is_dir():
            files += sorted(x for x in (base / "docs").rglob("*.md") if "node_modules" not in x.parts)[:60]
    urls = {"staging": [], "production": [], "other": []}
    hints = []
    for f in dict.fromkeys(files):
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        rel = f.relative_to(root).as_posix()
        for i, line in enumerate(lines, 1):
            for url in URL_RE.findall(line):
                url = url.rstrip(".,;:")
                if URL_SKIP.search(url):
                    continue
                host = re.sub(r"^https?://", "", url).split("/")[0]
                kind = ("staging" if STAGING_WORDS.search(host) or (STAGING_WORDS.search(line) and not PROD_WORDS.search(line))
                        else "production" if PROD_WORDS.search(line) else "other")
                origin = "/".join(url.split("/", 3)[:3])
                if origin not in urls[kind]:
                    urls[kind].append(origin)
            m = REPLATFORM.search(line)
            if m and len(hints) < 8:
                hints.append(f"{rel}:{i}: {m.group(0)}")
    present = [p.relative_to(root).as_posix() for p in files if p.name in {Path(n).name for n in INSTRUCTIONS}]
    return {"instructions": present, "doc_count": sum(1 for p in files if "docs" in p.parts),
            "urls": {k: v[:6] for k, v in urls.items()}, "replatform_hints": hints}


def previous_runs(root: Path) -> list[dict]:
    out = []
    for state in sorted((root / ".ship-site").glob("*/state.json"), reverse=True)[:5]:
        s = read_json(state)
        steps = (s.get("release") or {}).get("steps") or []
        unfinished = any(v not in ("done", "skipped") for v in (s.get("steps") or {}).values()) or \
            any(isinstance(x, dict) and not x.get("done") for x in steps)
        out.append({"run": state.parent.relative_to(root).as_posix(), "mode": s.get("mode"),
                    "unfinished": unfinished, "next": s.get("next"),
                    "has_findings": (state.parent / "findings.json").exists()})
    return out


# ---------------------------------------------------------------- assemble

def framework_info(app: Path, fw: str | None, pkg: dict) -> tuple[dict, Path | None]:
    if not fw:
        return {"name": None, "label": None, "version": None}, None
    spec = FRAMEWORKS[fw]
    cfg = next((app / c for c in spec["configs"] if (app / c).is_file()), None)
    d = deps(pkg)
    version = next((d[x] for x in spec["deps"] if x in d), None)
    label = spec["label"]
    if fw == "vite":
        flavour = next((name for dep, name in VITE_FLAVOURS if dep in d), None)
        label = f"Vite + {flavour}" if flavour else label
    if fw == "remix" and not (app / "vite.config.ts").exists() and not (app / "vite.config.js").exists():
        spec = {**spec, "build": "remix build", "dev": "remix dev"}  # classic compiler
    return {"name": fw, "label": label, "version": version,
            "config": cfg.relative_to(app).as_posix() if cfg else None,
            "dev_port": spec["port"], "output_dir": spec["output"], "public_env_prefixes": list(spec["env"]),
            "build_cmd": spec["build"], "dev_cmd": spec["dev"]}, cfg


def detect(root: Path, app_arg: str | None) -> dict:
    root_pkg = read_json(root / "package.json")
    if app_arg:
        app, candidates, monorepo = root / app_arg, [app_arg], True
        if not app.is_dir():
            raise ValueError(f"--app {app_arg}: not a directory")
    else:
        app, candidates, monorepo = find_app(root, root_pkg)
    target = app or root
    pkg = read_json(target / "package.json")
    fw = (js_framework(pkg) or file_framework(target)) if app else None
    info, cfg = framework_info(target, fw, pkg)
    router, pages_dir, source, rts = routes(target, fw, cfg)
    info.update({"router": router, "pages_dir": pages_dir})
    return {
        "repo": str(root),
        "app": {"path": target.relative_to(root).as_posix() if app else None, "monorepo": monorepo,
                "candidates": candidates if app is None or len(candidates) > 1 else []},
        "framework": info,
        "pm": package_manager(root, target, root_pkg),
        "hosts": hosts(root, target),
        "git": git_facts(root),
        "scripts": scripts(pkg, root_pkg if target != root else {}),
        "playwright_config": next((p.name for p in sorted(target.glob("playwright.config.*"))), None),
        "lighthouse_config": next((p.name for p in sorted(target.glob("lighthouserc*"))), None),
        "routes_source": source,
        "routes": rts,
        "app_files": app_files(target, fw, pages_dir, pkg),
        "docs": docs(root, target),
        "previous": previous_runs(root),
    }


def summary(d: dict) -> str:
    g, pm, fw = d["git"], d["pm"], d["framework"]
    host = " + ".join(d["hosts"]) or "unknown host"
    if len(d["hosts"]) > 1:
        host += " (several configs: ask which is live)"
    app = d["app"]["path"]
    where = f"app {app}" if app not in (None, ".", "") else "app at repo root"
    if app is None:
        where = ("monorepo, pick one with --app: " + ", ".join(d["app"]["candidates"])
                 if d["app"]["candidates"] else "no site app found")
    dyn = sum(bool(r["dynamic"]) for r in d["routes"])
    name = f"{fw['label']} {fw['version'] or ''}".strip() if fw["name"] else "No known framework"
    router = f" ({fw['router']} router)" if fw.get("router") else ""
    pm_s = f"{pm['name']} ({pm['source']})" if pm["name"] else "no JS package manager"
    lines = [
        f"{name}{router} · {where} · {pm_s} · {host}",
        f"git {g.get('host', 'none')} · branch {g.get('branch')} @ {g.get('head_sha')} · base {g.get('base')}"
        f" · production {g.get('production_branch')} · {len(d['routes'])} routes ({dyn} dynamic) from {d['routes_source']}",
    ]
    if fw["name"]:
        lines.append(f"Dev port {fw['dev_port'] or '—'} · output {fw['output_dir'] or '—'} · config {fw['config'] or '—'}"
                     + (f" · public env prefixes {', '.join(fw['public_env_prefixes'])}" if fw["public_env_prefixes"] else ""))
    if pm["stale_lockfiles"]:
        lines.append(f"Stale lockfile(s) for another package manager: {', '.join(pm['stale_lockfiles'])} (Should-fix)")
    if g.get("base_behind_remote"):
        lines.append(f"Local {g['base']} is {g['base_behind_remote']} commit(s) behind origin/{g['base']}: fetch/pull first")
    s = d["scripts"]
    gate = s["aggregate"] or " → ".join(x for x in (s["lint"], s["format_check"], s["typecheck"], s["build"]) if x)
    if not gate and fw.get("build_cmd"):
        gate = f"{fw['build_cmd']} (framework default, no package scripts)"
    missing = [k for k in ("lint", "format_check", "build") if not s[k]] if not s["aggregate"] and pm["name"] else []
    lines.append(f"Gate: {gate or 'no scripts'}" + (f" · missing: {', '.join(missing)}" if missing else "")
                 + (f" · host build: {s['host_build']}" if s["host_build"] else "")
                 + (f" · release scripts: {', '.join(s['release'])}" if s["release"] else ""))
    u = d["docs"]["urls"]
    lines.append(f"URLs in docs: staging {', '.join(u['staging']) or '—'} · production {', '.join(u['production']) or '—'}")
    if d["docs"]["replatform_hints"]:
        lines.append("Replatform hints: " + "; ".join(d["docs"]["replatform_hints"][:3]))
    missing_files = [k for k in ("not-found", "error", "global-error", "sitemap", "robots") if d["app_files"].get(k) is False]
    if missing_files:
        lines.append("Site files missing: " + ", ".join(missing_files))
    open_runs = [r for r in d["previous"] if r["unfinished"]]
    if open_runs:
        lines.append(f"Unfinished run: {open_runs[0]['run']} ({open_runs[0]['mode']}) — next: {open_runs[0]['next']}")
    return "\n".join(lines)


def write_state(path: Path, d: dict) -> None:
    state = read_json(path) if path.exists() else {}
    g = d["git"]
    for k, v in (("repo", d["repo"]), ("app", d["app"]["path"]), ("base", g.get("base")),
                 ("branch", g.get("branch")), ("head_sha", g.get("head_sha"))):
        state.setdefault(k, v)
    state.setdefault("detected", {
        "framework": d["framework"]["name"], "pm": d["pm"]["name"], "host": " + ".join(d["hosts"]) or "unknown",
        "git": g.get("host"), "base": g.get("base"), "routes": len(d["routes"]),
        **({"app": d["app"]["path"]} if d["app"]["monorepo"] else {}),
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("repo", nargs="?", default=".")
    ap.add_argument("--app", help="path of the site inside a monorepo, relative to the repo (e.g. apps/web)")
    ap.add_argument("--json", action="store_true", help="print every fact as JSON")
    ap.add_argument("--state", type=Path, help="merge repo/base/head_sha/detected into this state.json")
    args = ap.parse_args()
    root = Path(args.repo).resolve()
    if not root.is_dir():
        print(f"detect: {root} is not a directory", file=sys.stderr)
        return 2
    try:
        d = detect(root, args.app)
    except ValueError as e:
        print(f"detect: {e}", file=sys.stderr)
        return 2
    if args.state:
        write_state(args.state, d)
    print(json.dumps(d, indent=2) if args.json else summary(d))
    return 0 if d["framework"]["name"] else 1


if __name__ == "__main__":
    sys.exit(main())
