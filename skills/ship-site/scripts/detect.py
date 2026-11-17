#!/usr/bin/env python3
"""Read a site repo once and print the facts every ship-site step depends on.

Step 0 used to be a dozen shell commands and judgment calls per run: which
package manager, which host, which branch is staging, where the Next app lives
in a monorepo, which routes exist, which gate scripts to run. Getting one wrong
(a stale package-lock.json in a pnpm repo, a route group leaking into a URL, the
wrong base branch) poisons every later step. This does it deterministically.

Usage:
  detect.py [repo_dir] [--app apps/web] [--json] [--state <run_dir>/state.json]

Reports:
  app          where the Next.js app lives (repo root, or the workspace package
               that depends on `next`); several candidates in a monorepo → pass --app
  next         version and router (app / pages / both), app dir
  pm           package manager and how it was decided, plus stale lockfiles
  hosts        AWS Amplify / Vercel / Netlify / Cloudflare Workers config found
  git          remote host, current branch, base (staging) and production branch,
               HEAD sha, and whether the local base is behind its remote ref
  scripts      the gate, test, host-build and release scripts that exist
  routes       URL per page file: route groups, private folders, parallel and
               intercepting routes handled; dynamic segments flagged for expansion
  app_files    not-found, error, global-error, sitemap, robots, icons, OG image
  docs         instructions files present, staging/production URLs mentioned in
               them, and replatform hints (WordPress, cutover, "replace the live site")
  previous     earlier .ship-site run folders and whether one is unfinished

Read-only and offline: it never fetches, installs or writes, except the state
file when --state is given (merged in place; existing keys are kept).
Exit 0 = Next.js app found, 1 = no Next.js app (framework-neutral steps only),
2 = not a directory / bad --app.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

PAGE_EXT = {".tsx", ".ts", ".jsx", ".js", ".mdx", ".md"}
LOCKFILES = (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"), ("bun.lock", "bun"),
             ("bun.lockb", "bun"), ("package-lock.json", "npm"))
HOSTS = (("amplify.yml", "AWS Amplify"), ("vercel.json", "Vercel"), (".vercel", "Vercel"),
         ("netlify.toml", "Netlify"), ("wrangler.toml", "Cloudflare Workers"),
         ("wrangler.jsonc", "Cloudflare Workers"), ("wrangler.json", "Cloudflare Workers"),
         ("open-next.config.ts", "Cloudflare Workers"))
INSTRUCTIONS = ("AGENTS.md", "CLAUDE.md", "GEMINI.md", ".github/copilot-instructions.md",
                ".cursor/rules", "README.md", "CONTRIBUTING.md")
STAGING_BRANCHES = ("dev", "develop", "staging")
APP_FILES = {"not-found": "not-found", "error": "error", "global-error": "global-error",
             "sitemap": "sitemap", "robots": "robots", "manifest": "manifest",
             "opengraph-image": "opengraph-image", "icon": "icon", "apple-icon": "apple-icon"}
URL_RE = re.compile(r"https?://[^\s)\"'<>`\]]+")
URL_SKIP = re.compile(r"(github\.com|githubusercontent|shields\.io|localhost|127\.0\.0\.1|example\.(com|org)"
                      r"|nextjs\.org|vercel\.com/docs|npmjs\.|schema\.org|w3\.org|bitbucket\.org|gitlab\.com"
                      r"|keepachangelog|semver\.org|conventionalcommits)", re.I)
STAGING_WORDS = re.compile(r"\b(staging|stage|preview|uat|qa|dev)\b", re.I)
PROD_WORDS = re.compile(r"\b(production|prod|live)\b", re.I)
REPLATFORM = re.compile(r"\b(re-?platform\w*|cut-?over|wordpress|wix|squarespace|webflow|legacy site|old site"
                        r"|replac\w* the (live|existing|old|current) (site|website))\b", re.I)


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


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
    if "next" in deps(pkg):
        return root, [], monorepo
    if not globs and monorepo:
        globs = ["apps/*", "packages/*"]
    candidates = []
    for g in globs:
        for d in sorted(root.glob(g.rstrip("/").removesuffix("/**"))):
            if d.is_dir() and "node_modules" not in d.parts and "next" in deps(read_json(d / "package.json")):
                rel = d.relative_to(root).as_posix()
                if rel not in candidates:
                    candidates.append(rel)
    if len(candidates) == 1:
        return root / candidates[0], candidates, monorepo
    return None, candidates, monorepo


# ---------------------------------------------------------------- facts

def package_manager(root: Path, app: Path, pkg: dict) -> dict:
    found = []
    for base in dict.fromkeys((root, app)):
        found += [(name, pm) for name, pm in LOCKFILES if (base / name).exists()]
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
        "typecheck": first("typecheck", "type-check", "tsc", "types", "check-types"),
        "build": first("build"),
        "unit_test": first("test", "test:unit"),
        "e2e": first("test:e2e", "e2e", "playwright", "test:playwright"),
        "host_build": host_build[0] if host_build else None,
        "release": sorted(n for n in s if n.startswith("release")),
    }


def page_url(parts: tuple[str, ...]) -> str | None:
    if any(p.startswith("_") or p.startswith("(.") for p in parts):
        return None  # private folder or intercepting route
    segs = [p for p in parts if not (p.startswith("(") and p.endswith(")")) and not p.startswith("@")]
    return "/" + "/".join(segs)


def routes(app: Path) -> tuple[str | None, str | None, list[dict]]:
    app_dir = next((d for d in (app / "src" / "app", app / "app") if d.is_dir()), None)
    pages_dir = next((d for d in (app / "src" / "pages", app / "pages") if d.is_dir()), None)
    found: dict[str, dict] = {}
    if app_dir:
        for p in sorted(app_dir.rglob("page.*")):
            if p.suffix not in PAGE_EXT or "node_modules" in p.parts:
                continue
            url = page_url(p.parent.relative_to(app_dir).parts)
            if url and url not in found:
                found[url] = {"url": url, "file": p.relative_to(app).as_posix(), "router": "app"}
    if pages_dir:
        for p in sorted(pages_dir.rglob("*")):
            rel = p.relative_to(pages_dir)
            if p.suffix not in PAGE_EXT or not p.is_file() or rel.parts[0] == "api" \
                    or any(x.startswith("_") for x in rel.parts):
                continue
            parts = list(rel.with_suffix("").parts)
            if parts[-1] == "index":
                parts.pop()
            url = "/" + "/".join(parts)
            found.setdefault(url, {"url": url, "file": p.relative_to(app).as_posix(), "router": "pages"})
    for r in found.values():
        r["dynamic"] = "[" in r["url"]
    router = "both" if app_dir and pages_dir else "app" if app_dir else "pages" if pages_dir else None
    rel_dir = (app_dir or pages_dir)
    return router, rel_dir.relative_to(app).as_posix() if rel_dir else None, \
        sorted(found.values(), key=lambda r: (r["url"].count("/"), r["url"]))


def app_files(app: Path, app_dir: str | None) -> dict:
    if not app_dir or not app_dir.endswith("app"):
        return {}
    d = app / app_dir
    out = {key: any(d.glob(f"{stem}.*")) for key, stem in APP_FILES.items()}
    out["favicon"] = (d / "favicon.ico").exists() or (app / "public" / "favicon.ico").exists()
    return out


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
                base_url = url.split("/", 3)[:3]
                origin = "/".join(base_url)
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


def detect(root: Path, app_arg: str | None) -> dict:
    root_pkg = read_json(root / "package.json")
    if app_arg:
        app, candidates, monorepo = root / app_arg, [app_arg], True
        if not (app / "package.json").exists():
            raise ValueError(f"--app {app_arg}: no package.json there")
    else:
        app, candidates, monorepo = find_app(root, root_pkg)
    target = app or root
    pkg = read_json(target / "package.json")
    router, app_dir, rts = routes(target)
    return {
        "repo": str(root),
        "app": {"path": target.relative_to(root).as_posix() if app else None, "monorepo": monorepo,
                "candidates": candidates if app is None or len(candidates) > 1 else []},
        "next": {"version": deps(pkg).get("next"), "router": router, "app_dir": app_dir},
        "pm": package_manager(root, target, root_pkg),
        "hosts": hosts(root, target),
        "git": git_facts(root),
        "scripts": scripts(pkg, root_pkg if target != root else {}),
        "playwright_config": next((p.name for p in sorted(target.glob("playwright.config.*"))), None),
        "lighthouse_config": next((p.name for p in sorted(target.glob("lighthouserc*"))), None),
        "routes": rts,
        "app_files": app_files(target, app_dir),
        "docs": docs(root, target),
        "previous": previous_runs(root),
    }


def summary(d: dict) -> str:
    g, pm, nx = d["git"], d["pm"], d["next"]
    host = " + ".join(d["hosts"]) or "unknown host"
    if len(d["hosts"]) > 1:
        host += " (several configs: ask which is live)"
    app = d["app"]["path"]
    where = f"app {app}" if app not in (None, ".", "") else "app at repo root"
    if app is None:
        where = ("monorepo, pick one with --app: " + ", ".join(d["app"]["candidates"])
                 if d["app"]["candidates"] else "no Next.js app found")
    dyn = sum(r["dynamic"] for r in d["routes"])
    lines = [
        f"{'Next ' + str(nx['version']) if nx['version'] else 'Not Next.js'} ({nx['router'] or 'no router'})"
        f" · {where} · {pm['name']} ({pm['source']}) · {host}",
        f"git {g.get('host', 'none')} · branch {g.get('branch')} @ {g.get('head_sha')} · base {g.get('base')}"
        f" · production {g.get('production_branch')} · {len(d['routes'])} routes ({dyn} dynamic)",
    ]
    if pm["stale_lockfiles"]:
        lines.append(f"Stale lockfile(s) for another package manager: {', '.join(pm['stale_lockfiles'])} (Should-fix)")
    if g.get("base_behind_remote"):
        lines.append(f"Local {g['base']} is {g['base_behind_remote']} commit(s) behind origin/{g['base']}: fetch/pull first")
    s = d["scripts"]
    gate = s["aggregate"] or " → ".join(x for x in (s["lint"], s["format_check"], s["typecheck"], s["build"]) if x)
    missing = [k for k in ("lint", "format_check", "build") if not s[k]] if not s["aggregate"] else []
    lines.append(f"Gate: {gate or 'no scripts'}" + (f" · missing: {', '.join(missing)}" if missing else "")
                 + (f" · host build: {s['host_build']}" if s["host_build"] else "")
                 + (f" · release scripts: {', '.join(s['release'])}" if s["release"] else ""))
    u = d["docs"]["urls"]
    lines.append(f"URLs in docs: staging {', '.join(u['staging']) or '—'} · production {', '.join(u['production']) or '—'}")
    if d["docs"]["replatform_hints"]:
        lines.append("Replatform hints: " + "; ".join(d["docs"]["replatform_hints"][:3]))
    missing_files = [k for k in ("not-found", "error", "global-error", "sitemap", "robots") if d["app_files"].get(k) is False]
    if missing_files:
        lines.append("App files missing: " + ", ".join(missing_files))
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
        "pm": d["pm"]["name"], "host": " + ".join(d["hosts"]) or "unknown",
        "git": g.get("host"), "base": g.get("base"), "routes": len(d["routes"]),
        **({"app": d["app"]["path"]} if d["app"]["monorepo"] else {}),
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("repo", nargs="?", default=".")
    ap.add_argument("--app", help="path of the Next.js app inside a monorepo, relative to the repo (e.g. apps/web)")
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
    return 0 if d["next"]["version"] else 1


if __name__ == "__main__":
    sys.exit(main())
