#!/usr/bin/env python3
"""Diff external hosts referenced in source against the site's Content-Security-Policy.

A host missing from the CSP is blocked silently by the browser at runtime — no
build error. This finds candidates statically; confirm in the browser console.

Usage:
  csp_hosts.py [repo_dir] [--config <file>] [--src src] [--json]

Where the CSP is looked for, first hit wins (the others are listed as `other_sources`):
  next.config.*, nuxt.config.*, astro.config.*, svelte.config.* (kit.csp.directives),
  vercel.json, netlify.toml, _headers (root, public/, static/, src/), firebase.json,
  staticwebapp.config.json, then <meta http-equiv="Content-Security-Policy"> in HTML
  layouts (index.html, src/app.html, layouts/, _layouts/, _includes/, src/layouts/).
Object-style directives ({'script-src': ['self', 'https://x']}) are understood too.

Output:
  missing  host the code references but no CSP directive allows (per guessed directive)
  unused   host allowlisted in the CSP but never referenced in source
Exit 1 if anything is missing.

Heuristic limits: hosts built at runtime, or fetched internally by SDKs (GA, Vimeo
player, Iconify), won't appear in source. The KNOWN_RUNTIME table covers common
ones so they aren't flagged as unused.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

URL_RE = re.compile(r"""https?://([a-z0-9.-]+\.[a-z]{2,})(?::\d+)?(/[^\s"'`)<>]*)?""", re.I)
SRC_EXT = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".css", ".json", ".astro", ".vue", ".svelte", ".html",
           ".njk", ".liquid", ".hbs", ".mdx", ".md", ".erb", ".php"}
# Hosts that appear in code only as identifiers/docs, never fetched by the browser.
IGNORE = {
    "www.w3.org", "schema.org", "nextjs.org", "github.com", "reactjs.org", "react.dev", "astro.build",
    "nuxt.com", "svelte.dev", "kit.svelte.dev", "vuejs.org", "vitejs.dev", "vite.dev", "gohugo.io",
    "developer.mozilla.org", "tailwindcss.com", "localhost", "example.com",
    "fonts.googleapis.com",  # only relevant if actually <link>ed — next/font self-hosts
}
# Hosts an SDK contacts at runtime without appearing in source.
KNOWN_RUNTIME = {
    "www.google-analytics.com", "analytics.google.com", "region1.google-analytics.com",
    "api.iconify.design", "api.simplesvg.com", "api.unisvg.com",
    "vimeo.com", "i.vimeocdn.com", "f.vimeocdn.com", "*.vimeocdn.com",
    "*.google-analytics.com", "*.analytics.google.com",
}
# Server-side-only paths: fetches from these never hit the browser CSP.
SERVER_HINTS = ("/app/api/", "/pages/api/", "route.ts", "route.js", "/server/", "server-only", ".server.",
                "+server.", "+page.server.", "+layout.server.")
# Tests and stories never ship to the browser.
NON_SHIPPING = (".test.", ".spec.", ".stories.", "/__tests__/", "/__mocks__/", "/e2e/")
SKIP_DIRS = {"node_modules", ".next", ".nuxt", ".output", ".svelte-kit", ".astro", ".git", "dist", "build", "out",
             "_site", "coverage", "vendor", "resources"}
CONFIGS = ("next.config.ts", "next.config.mjs", "next.config.js", "next.config.cjs",
           "nuxt.config.ts", "nuxt.config.js", "nuxt.config.mjs",
           "astro.config.mjs", "astro.config.ts", "astro.config.js",
           "svelte.config.js", "svelte.config.mjs", "svelte.config.ts",
           "vercel.json", "netlify.toml", "_headers", "public/_headers", "static/_headers", "src/_headers",
           "firebase.json", "staticwebapp.config.json", "public/staticwebapp.config.json")
LAYOUT_GLOBS = ("index.html", "src/app.html", "src/index.html", "public/index.html", "app/root.tsx", "app/root.jsx",
                "layouts/**/*.html", "_layouts/*.html", "_includes/*.html", "src/_includes/**/*.njk",
                "src/layouts/**/*.astro", "src/app/layout.tsx", "app.vue", "app/app.vue")


def source_files(src_dirs: list[Path]):
    for d in src_dirs:
        for f in d.rglob("*"):
            if f.suffix in SRC_EXT and f.is_file() and not SKIP_DIRS.intersection(f.parts):
                yield f


def guess_directive(line: str) -> str | None:
    """Directive a browser request from this line would need, or None if the line
    only *mentions* the URL (plain link, JSON-LD sameAs, console text, preconnect)."""
    l = line.lower()
    if re.search(r"rel=[\"'](preconnect|dns-prefetch)", l):
        return None  # connection hints need no CSP allowance
    if re.search(r"<script|script\s*src|strategy=|gtag/js|\.js(\?|[\"'`])", l):
        return "script-src"
    if re.search(r"<iframe|frame|embed|player\.vimeo|youtube\.com/embed", l):
        return "frame-src"
    if re.search(r"<video|<audio|<source|\.mp4|\.webm|\.m3u8", l):
        return "media-src"
    if re.search(r"\.(png|jpe?g|webp|avif|gif)(\?|$|[\"'`])|<img|image|poster|thumbnail|src=", l):
        return "img-src"
    if re.search(r"\.(woff2?|ttf|otf)|@font-face", l):
        return "font-src"
    if re.search(r"fetch\(|axios|xmlhttprequest|sendbeacon|websocket|eventsource|endpoint|api_?url|base_?url", l):
        return "connect-src"
    return None


NAMES = r"(?:default|script|style|img|font|connect|media|frame|worker|child|object|manifest|form-action|base-uri|frame-ancestors)[a-z-]*"
KEYWORDS = {"self", "none", "unsafe-inline", "unsafe-eval", "strict-dynamic", "unsafe-hashes", "wasm-unsafe-eval",
            "report-sample", "inline-speculation-rules"}


def add_sources(directives: dict[str, set[str]], name: str, tokens) -> None:
    hosts = set()
    for tok in tokens:
        tok = tok.strip().strip(";,").strip("'\"")
        if not tok or tok.lower() in KEYWORDS or tok.endswith(":") or tok.startswith(("nonce-", "sha256-", "sha384-", "sha512-")):
            continue
        tok = re.sub(r"^(https?|wss?)://", "", tok).split("/")[0]
        if tok and ("." in tok or tok == "*" or tok.startswith("localhost")):
            hosts.add(tok.lower())
    directives.setdefault(name, set()).update(hosts)


def parse_policy(policy: str, directives: dict[str, set[str]]) -> None:
    """`default-src 'self'; img-src https://x` → directives (a whole policy, or one directive)."""
    for part in policy.split(";"):
        toks = part.split()
        if toks and re.fullmatch(NAMES, toks[0]):
            add_sources(directives, toks[0], toks[1:])


def parse_csp(config_text: str) -> dict[str, set[str]]:
    directives: dict[str, set[str]] = {}
    # String literals that start with a directive name. One pattern per quote type: CSP
    # sources contain single quotes ('self'), so a mixed-quote class would stop at the first.
    pats = [rf'"({NAMES}\s+[^"]*)"', rf"`({NAMES}\s+[^`]*)`",
            rf"'({NAMES}\s+(?:[^']|'(?:self|none|unsafe-[a-z-]+|strict-dynamic|nonce-[^']+|sha\d+-[^']+)')*)'"]
    for m in (m for p in pats for m in re.finditer(p, config_text)):
        parse_policy(m.group(1), directives)
    # Unquoted header lines: `_headers` files, TOML/YAML keys (Content-Security-Policy = "...").
    for m in re.finditer(r"Content-Security-Policy\s*[:=]\s*(.+)", config_text, re.I):
        parse_policy(m.group(1).strip().strip("'\"`,"), directives)
    # Object form: SvelteKit kit.csp.directives, nuxt-security, helmet.
    for m in re.finditer(rf"[\"']?({NAMES})[\"']?\s*:\s*\[([^\]]*)\]", config_text):
        add_sources(directives, m.group(1), [t.strip().strip("\"'`") for t in m.group(2).split(",")])
    for m in re.finditer(rf"[\"']({NAMES})[\"']\s*:\s*[\"'`]([^\"'`]*(?:'[a-z-]+'[^\"'`]*)*)[\"'`]", config_text):
        add_sources(directives, m.group(1), m.group(2).split())
    return directives


def find_csp(repo: Path) -> tuple[Path | None, dict[str, set[str]], list[str]]:
    """First file that carries a CSP, its directives, and any other files that also carry one."""
    candidates = [repo / c for c in CONFIGS if (repo / c).is_file()]
    for g in LAYOUT_GLOBS:
        candidates += sorted(p for p in repo.glob(g) if p.is_file() and not SKIP_DIRS.intersection(p.relative_to(repo).parts))
    hits = []
    for c in dict.fromkeys(candidates):
        text = c.read_text(errors="replace")
        if c.suffix in (".html", ".njk", ".astro", ".tsx", ".jsx", ".vue") and "content-security-policy" not in text.lower():
            continue  # a layout only counts when it sets the CSP meta tag
        d = parse_csp(text)
        if d:
            hits.append((c, d))
    if not hits:
        return None, {}, []
    return hits[0][0], hits[0][1], [h[0].relative_to(repo).as_posix() for h in hits[1:]]


def allowed(host: str, sources: set[str]) -> bool:
    for s in sources:
        if s == host or (s.startswith("*.") and host.endswith(s[1:])):
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Diff external hosts referenced in source against the site's CSP.")
    ap.add_argument("repo", nargs="?", default=".")
    ap.add_argument("--config")
    ap.add_argument("--src", default=None)
    ap.add_argument("--self-host", action="append", default=[],
                    help="host(s) that are this site's own origin (auto-detected from siteUrl)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    repo = Path(a.repo).resolve()
    others: list[str] = []
    if a.config:
        cfg = Path(a.config)
        if not cfg.exists():
            print(f"--config {cfg}: not found", file=sys.stderr)
            return 2
        csp = parse_csp(cfg.read_text(errors="replace"))
    else:
        cfg, csp, others = find_csp(repo)
    if not csp:
        print(f"No CSP directives found {'in ' + str(cfg) if cfg else 'in any known config, headers file or layout'}"
              " (the host or a server may set it: check the live response headers, or pass --config)", file=sys.stderr)
        return 2
    default = csp.get("default-src", set())

    src_dirs = [repo / a.src] if a.src else [d for d in (repo / n for n in (
        "src", "app", "pages", "components", "lib", "layouts", "_layouts", "_includes", "templates", "content",
        "resources/views")) if d.is_dir()]
    if not src_dirs:  # plain static site: the HTML lives at the root
        src_dirs = [repo]
    files = list(source_files(src_dirs))
    refs: dict[str, dict] = {}
    for f in files:
        rel = f.relative_to(repo).as_posix()
        if any(h in "/" + rel for h in NON_SHIPPING):
            continue
        server = any(h in "/" + rel for h in SERVER_HINTS)
        text = f.read_text(errors="replace")
        if 'import "server-only"' in text or "import 'server-only'" in text:
            server = True
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("//", "*", "/*")):
                continue
            for m in URL_RE.finditer(line):
                host = m.group(1).lower()
                if host in IGNORE:
                    continue
                d = guess_directive(line)
                r = refs.setdefault(host, {"host": host, "locations": [], "directives": set(), "server_only": True})
                r["locations"].append(f"{rel}:{i}")
                if d:
                    r["directives"].add(d)
                r["server_only"] &= server

    # The site's own production host is 'self' when deployed there; on staging an
    # absolute URL to it is cross-origin, so it's reported separately, not as missing.
    self_hosts = {h.lower() for h in a.self_host}
    for f in files:
        for m in re.finditer(r"""site_?url\s*[:=]\s*["'`]https?://([a-z0-9.-]+)""", f.read_text(errors="replace"), re.I):
            self_hosts.add(m.group(1).lower())
    # Site URL in framework config: Astro `site`, Hugo `baseURL`, Jekyll `url`, Nuxt `site.url`, Gatsby `siteUrl`.
    for name in ("astro.config.mjs", "astro.config.ts", "hugo.toml", "hugo.yaml", "config.toml", "_config.yml",
                 "nuxt.config.ts", "gatsby-config.js", "gatsby-config.ts"):
        if (repo / name).is_file():
            for m in re.finditer(r"""\b(site|siteUrl|baseURL|baseurl|url)\s*[:=]\s*["'`]?https?://([a-z0-9.-]+)""",
                                 (repo / name).read_text(errors="replace"), re.I):
                self_hosts.add(m.group(2).lower())

    missing, ok, mentioned = [], [], []
    for host, r in sorted(refs.items()):
        if r["server_only"] or host in self_hosts:
            continue  # server-side fetches aren't subject to the browser CSP
        if not r["directives"]:
            mentioned.append(host)  # links / JSON-LD / text — no browser request inferred
            continue
        gaps = [d for d in sorted(r["directives"]) if not allowed(host, csp.get(d, set()) or default)]
        entry = {"host": host, "directives": sorted(r["directives"]), "locations": r["locations"][:5]}
        (missing if gaps else ok).append({**entry, "missing_in": gaps} if gaps else entry)

    all_allowed = set().union(*csp.values())
    referenced = set(refs)
    unused = sorted(h for h in all_allowed
                    if h not in KNOWN_RUNTIME and not any(allowed(r, {h}) for r in referenced))

    try:
        cfg_label = cfg.resolve().relative_to(repo).as_posix()
    except ValueError:  # --config outside the repo
        cfg_label = str(cfg)
    out = {"config": cfg_label, "other_sources": others, "missing": missing, "unused": unused,
           "ok": [o["host"] for o in ok],
           "mentioned_only": mentioned,
           "server_only": sorted(h for h, r in refs.items() if r["server_only"]),
           "self_hosts": sorted(self_hosts)}
    if a.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"CSP source: {out['config']}")
        if others:
            print(f"Also sets a CSP: {', '.join(others)} (browsers enforce every policy they receive: check they agree)")
        print(f"\nMISSING ({len(missing)}) — referenced in client code, not allowed by CSP:")
        for m in missing:
            print(f"  {m['host']:<36} needs {', '.join(m['missing_in'])}   e.g. {m['locations'][0]}")
        print(f"\nUNUSED ({len(unused)}) — allowlisted, never referenced (verify before removing):")
        for u in unused:
            print(f"  {u}")
        print(f"\nOK ({len(ok)}): {', '.join(out['ok']) or '-'}")
        print(f"Mentioned only (links, JSON-LD, text — no request inferred): {', '.join(mentioned) or '-'}")
        print(f"Own origin (treated as 'self'; absolute URLs to it are cross-origin on staging): {', '.join(sorted(self_hosts)) or '-'}")
        print(f"Server-side only (not subject to CSP): {', '.join(out['server_only']) or '-'}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
