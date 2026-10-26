#!/usr/bin/env python3
"""Diff external hosts referenced in source against the CSP in next.config.*.

A host missing from the CSP is blocked silently by the browser at runtime — no
build error. This finds candidates statically; confirm in the browser console.

Usage:
  csp_hosts.py [repo_dir] [--config next.config.ts] [--src src] [--json]

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
SRC_EXT = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".css", ".json"}
# Hosts that appear in code only as identifiers/docs, never fetched by the browser.
IGNORE = {
    "www.w3.org", "schema.org", "nextjs.org", "github.com", "reactjs.org", "react.dev",
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
SERVER_HINTS = ("/app/api/", "route.ts", "route.js", "/server/", "server-only", ".server.")
# Tests and stories never ship to the browser.
NON_SHIPPING = (".test.", ".spec.", ".stories.", "/__tests__/", "/__mocks__/", "/e2e/")
SKIP_DIRS = {"node_modules", ".next", "dist", "build", "out", "coverage"}


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


def parse_csp(config_text: str) -> dict[str, set[str]]:
    # Grab every "directive-name source source" string literal fragment.
    directives: dict[str, set[str]] = {}
    names = r"(?:default|script|style|img|font|connect|media|frame|worker|child|object|manifest|form-action|base-uri|frame-ancestors)[a-z-]*"
    # One pattern per quote type: CSP sources contain single quotes ('self'), so
    # a mixed-quote character class would stop at the first one.
    pats = [rf'"({names})\s+([^"]*)"', rf"`({names})\s+([^`]*)`", rf"'({names})\s+((?:[^']|'(?:self|none|unsafe-[a-z-]+|strict-dynamic|nonce-[^']+|sha\d+-[^']+)')*)'"]
    for m in (m for p in pats for m in re.finditer(p, config_text)):
        name, sources = m.group(1), m.group(2)
        hosts = set()
        for tok in sources.split():
            tok = tok.strip(";")
            if tok.startswith("'") or tok.endswith(":"):
                continue
            tok = re.sub(r"^https?://", "", tok).split("/")[0]
            if tok:
                hosts.add(tok.lower())
        directives.setdefault(name, set()).update(hosts)
    return directives


def allowed(host: str, sources: set[str]) -> bool:
    for s in sources:
        if s == host or (s.startswith("*.") and host.endswith(s[1:])):
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Diff external hosts referenced in source against the CSP in next.config.*.")
    ap.add_argument("repo", nargs="?", default=".")
    ap.add_argument("--config")
    ap.add_argument("--src", default=None)
    ap.add_argument("--self-host", action="append", default=[],
                    help="host(s) that are this site's own origin (auto-detected from siteUrl)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    repo = Path(a.repo).resolve()
    cfg = Path(a.config) if a.config else next(
        (repo / f for f in ("next.config.ts", "next.config.mjs", "next.config.js") if (repo / f).exists()), None)
    if not cfg or not cfg.exists():
        print("No next.config.* found — pass --config", file=sys.stderr)
        return 2
    csp = parse_csp(cfg.read_text())
    if not csp:
        print(f"No CSP directives found in {cfg} (headers may be set by the host — check the live response)", file=sys.stderr)
        return 2
    default = csp.get("default-src", set())

    src_dirs = [repo / a.src] if a.src else [d for d in (repo / n for n in ("src", "app", "pages", "components", "lib")) if d.exists()]
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
    out = {"config": cfg_label, "missing": missing, "unused": unused,
           "ok": [o["host"] for o in ok],
           "mentioned_only": mentioned,
           "server_only": sorted(h for h, r in refs.items() if r["server_only"]),
           "self_hosts": sorted(self_hosts)}
    if a.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"CSP source: {out['config']}")
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
