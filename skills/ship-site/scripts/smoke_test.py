#!/usr/bin/env python3
"""Post-deploy HTTP smoke test for a Next.js marketing site.

Checks per route: HTTP 200, og:image present (absolute URL), meta robots matches
the environment. Site-wide: robots.txt matches the environment, CSP and security
headers present, sitemap reachable on production, og:image URL itself resolves.

Usage:
  smoke_test.py https://staging.example.com --env staging
  smoke_test.py https://example.com --env production --routes /,/about,/contact
  smoke_test.py https://example.com --env production --json out.json
  smoke_test.py https://staging.example.com --env staging --header "Authorization: Basic ..."

Routes default to the site's sitemap.xml (production) or "/" plus any links found
on the home page (staging, where sitemap is usually disallowed).

Exit code: 0 = all checks passed, 1 = at least one failure, 2 = site unreachable.
Stdlib only (Python 3.9+), so it runs anywhere without installing anything.
"""
from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

UA = "ship-site-smoke/1.0 (+release verification)"
REQUIRED_HEADERS = {
    "content-security-policy": None,
    "strict-transport-security": None,
    "x-content-type-options": "nosniff",
    "referrer-policy": None,
}
CTX = ssl.create_default_context()
# Extra request headers (e.g. basic auth for a protected staging site). Sent only
# to the site under test over https, never to third-party hosts like an og:image CDN.
EXTRA_HEADERS: dict[str, str] = {}
SITE_NETLOC = ""
TIMEOUT = 20


def request_headers(url: str) -> dict[str, str]:
    h = {"User-Agent": UA}
    u = urllib.parse.urlparse(url)
    if u.scheme == "https" and u.netloc == SITE_NETLOC:
        h.update(EXTRA_HEADERS)
    return h


def fetch(url: str, method: str = "GET", timeout: int | None = None):
    req = urllib.request.Request(url, method=method, headers=request_headers(url))
    timeout = timeout or TIMEOUT
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            body = r.read().decode("utf-8", "replace") if method == "GET" else ""
            return r.status, {k.lower(): v for k, v in r.headers.items()}, body
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, ""
    except Exception as e:  # DNS, TLS, timeout
        return 0, {}, str(e)


def meta(html: str, attr: str, value: str) -> str | None:
    # Tolerates either attribute order: <meta property=".." content=".."> or reversed.
    for m in re.finditer(r"<meta\b[^>]*>", html, re.I):
        tag = m.group(0)
        if re.search(rf'{attr}\s*=\s*["\']{re.escape(value)}["\']', tag, re.I):
            c = re.search(r'content\s*=\s*["\']([^"\']*)["\']', tag, re.I)
            return c.group(1) if c else ""
    return None


def robots_star_disallows_all(body: str) -> bool:
    """True if the `User-agent: *` group contains `Disallow: /`.

    robots.txt is a list of groups: one or more User-agent lines followed by
    rules. A regex across the whole file would pick up `Disallow: /` from a
    later group (e.g. GPTBot) and misreport production as blocked.
    """
    groups: list[tuple[list[str], list[tuple[str, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[str, str]] = []
    for raw in body.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, val = (x.strip() for x in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if rules:  # a UA line after rules starts a new group
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(val.lower())
        elif key in ("allow", "disallow") and agents:
            rules.append((key, val))
    if agents:
        groups.append((agents, rules))
    return any("*" in a and ("disallow", "/") in r for a, r in groups)


def discover_routes(base: str, env: str) -> list[str]:
    if env == "production":
        status, _, body = fetch(urllib.parse.urljoin(base, "/sitemap.xml"))
        if status == 200:
            locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body)
            paths = sorted({urllib.parse.urlparse(u).path or "/" for u in locs})
            if paths:
                return paths
    status, _, body = fetch(base)
    paths = {"/"}
    if status == 200:
        for href in re.findall(r'href=["\'](/[^"\'#?]*)', body):
            if not href.startswith(("/_next", "/api", "/images", "/videos")) and "." not in href.rsplit("/", 1)[-1]:
                paths.add(href.rstrip("/") or "/")
    return sorted(paths)


def parse_header(raw: str) -> tuple[str, str]:
    name, sep, value = raw.partition(":")
    if not sep or not name.strip():
        raise argparse.ArgumentTypeError(f"expected 'Name: value', got {raw!r}")
    return name.strip(), value.strip()


def main() -> int:
    global SITE_NETLOC, TIMEOUT
    ap = argparse.ArgumentParser(description="Post-deploy HTTP smoke test for a Next.js marketing site.")
    ap.add_argument("base_url")
    ap.add_argument("--env", choices=["staging", "production"], required=True)
    ap.add_argument("--routes", help="comma-separated paths; default: discover")
    ap.add_argument("--json", help="write results JSON here")
    ap.add_argument("--expect-build", help="string that must appear in the home HTML to prove the new deploy is live (e.g. short git SHA when generateBuildId uses it)")
    ap.add_argument("--canonical-host", help="host canonical links must point to (default: production host = base host when --env production)")
    ap.add_argument("--header", action="append", type=parse_header, default=[], metavar="'NAME: VALUE'",
                    help="extra request header for the site under test (repeatable), e.g. basic auth on staging")
    ap.add_argument("--timeout", type=int, default=20, help="per-request timeout in seconds (default 20)")
    a = ap.parse_args()

    base = a.base_url.rstrip("/") + "/"
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        ap.error(f"base_url must be an absolute http(s) URL, got {a.base_url!r}")
    SITE_NETLOC, TIMEOUT = parsed.netloc, a.timeout
    EXTRA_HEADERS.update(dict(a.header))

    home_status, headers, home_html = fetch(base)
    if home_status == 0:
        print(f"UNREACHABLE  {base}: {home_html}", file=sys.stderr)
        return 2
    routes = [r.strip() for r in a.routes.split(",")] if a.routes else discover_routes(base, a.env)
    results: list[dict] = []

    def record(check: str, ok: bool, detail: str = "", target: str = ""):
        results.append({"check": check, "target": target, "ok": ok, "detail": detail})

    # Site-wide: robots.txt
    status, _, body = fetch(urllib.parse.urljoin(base, "/robots.txt"))
    disallow_all = robots_star_disallows_all(body)
    if a.env == "staging":
        record("robots.txt disallows all", status == 200 and disallow_all, f"status={status}", "/robots.txt")
    else:
        record("robots.txt allows crawling", status == 200 and not disallow_all, f"status={status}", "/robots.txt")
        record("robots.txt lists sitemap", "sitemap:" in body.lower(), "", "/robots.txt")
        s_status, _, _ = fetch(urllib.parse.urljoin(base, "/sitemap.xml"))
        record("sitemap.xml 200", s_status == 200, f"status={s_status}", "/sitemap.xml")

    # Site-wide: headers on home
    record("home status 200", home_status == 200, f"status={home_status}", "/")
    for h, expected in REQUIRED_HEADERS.items():
        v = headers.get(h)
        ok = v is not None and (expected is None or expected in v.lower())
        record(f"header {h}", ok, (v or "MISSING")[:160], "/")
    if a.env == "staging":
        xr = headers.get("x-robots-tag", "")
        record("x-robots-tag (info)", True, xr or "not set (meta robots must carry noindex)", "/")

    if a.expect_build:
        record("expected build is live", a.expect_build in home_html, a.expect_build, "/")

    # Unknown paths must 404, not soft-200 (soft 404s get indexed and hide broken links).
    nf_status, _, _ = fetch(urllib.parse.urljoin(base, "/ship-site-smoke-does-not-exist"))
    record("unknown path returns 404", nf_status == 404, f"status={nf_status}", "/ship-site-smoke-does-not-exist")

    # http:// must redirect to https://
    if parsed.scheme == "https":
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kw):
                return None
        try:
            opener = urllib.request.build_opener(NoRedirect)
            r = opener.open(urllib.request.Request(f"http://{parsed.netloc}/", headers={"User-Agent": UA}), timeout=TIMEOUT)
            record("http redirects to https", False, f"status={r.status} (no redirect)", "http://")
        except urllib.error.HTTPError as e:
            loc = e.headers.get("location", "")
            record("http redirects to https", e.code in (301, 302, 307, 308) and loc.startswith("https://"), f"{e.code} -> {loc}", "http://")
        except Exception as e:
            record("http redirects to https", False, str(e)[:120], "http://")

    # A handful of first-party static assets from the home page must load.
    assets = sorted(set(re.findall(r'(?:src|href)=["\'](/_next/static/[^"\']+)', home_html)))[:15]
    bad = [p for p in assets if fetch(urllib.parse.urljoin(base, p.lstrip("/")), method="HEAD")[0] not in (200, 304)]
    record("home static assets load", not bad, f"{len(assets) - len(bad)}/{len(assets)} ok" + (f"; failing: {bad[:3]}" if bad else ""), "/")

    canonical_host = a.canonical_host or (parsed.netloc if a.env == "production" else None)
    og_images: set[str] = set()
    for path in routes:
        url = urllib.parse.urljoin(base, path.lstrip("/"))
        status, _, html = fetch(url)
        record("status 200", status == 200, f"status={status}", path)
        if status != 200:
            continue
        og = meta(html, "property", "og:image")
        record("og:image present", bool(og) and og.startswith("http"), og or "MISSING", path)
        if og:
            og_images.add(og)
        tw = meta(html, "name", "twitter:image")
        record("twitter:image present", bool(tw), tw or "MISSING", path)
        robots = (meta(html, "name", "robots") or "").lower()
        if a.env == "staging":
            record("meta robots noindex", "noindex" in robots, robots or "MISSING", path)
        else:
            record("meta robots indexable", "noindex" not in robots, robots or "(none — indexable)", path)
        can = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]*href=["\']([^"\']+)', html, re.I)
        if canonical_host:
            ok = bool(can) and urllib.parse.urlparse(can.group(1)).netloc == canonical_host
            record("canonical -> production host", ok, can.group(1) if can else "MISSING", path)
        else:
            record("canonical present (info)", True, can.group(1) if can else "MISSING — pass --canonical-host to enforce", path)
        h1s = len(re.findall(r"<h1\b", html, re.I))
        record("single h1 (SSR html)", h1s == 1, f"h1 count={h1s}", path)

    for og in sorted(og_images):
        status, headers, _ = fetch(og, method="HEAD")
        if status in (403, 405):  # some CDNs reject HEAD
            status, headers, _ = fetch(og)
        ctype = headers.get("content-type", "")
        record("og:image resolves", status == 200 and ctype.startswith("image/"), f"status={status} type={ctype}", og)

    failed = [r for r in results if not r["ok"]]
    width = max(len(r["check"]) for r in results)
    for r in results:
        mark = "PASS" if r["ok"] else "FAIL"
        print(f"{mark}  {r['check']:<{width}}  {r['target']:<28}  {r['detail']}")
    print(f"\n{len(results) - len(failed)}/{len(results)} passed — {base} ({a.env}), {len(routes)} routes")

    if a.json:
        with open(a.json, "w") as f:
            json.dump({"base": base, "env": a.env, "routes": routes, "results": results,
                       "passed": len(results) - len(failed), "failed": len(failed)}, f, indent=2)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
