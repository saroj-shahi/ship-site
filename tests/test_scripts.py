"""Tests for the ship-site helper scripts. Stdlib only: python3 -m unittest discover -s tests"""
from __future__ import annotations

import http.server
import json
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "ship-site" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import csp_hosts  # noqa: E402
import smoke_test  # noqa: E402


def run(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args],
                          capture_output=True, text=True, timeout=60)


class RobotsTxt(unittest.TestCase):
    def test_star_group_disallow_all(self):
        self.assertTrue(smoke_test.robots_star_disallows_all("User-agent: *\nDisallow: /\n"))

    def test_disallow_in_other_group_is_ignored(self):
        body = "User-agent: *\nAllow: /\n\nUser-agent: GPTBot\nDisallow: /\n"
        self.assertFalse(smoke_test.robots_star_disallows_all(body))

    def test_shared_group_and_comments(self):
        body = "# staging\nUser-agent: Googlebot\nUser-agent: *\nDisallow: /   # everything\n"
        self.assertTrue(smoke_test.robots_star_disallows_all(body))

    def test_partial_disallow_is_not_all(self):
        self.assertFalse(smoke_test.robots_star_disallows_all("User-agent: *\nDisallow: /api/\n"))


class MetaParsing(unittest.TestCase):
    def test_either_attribute_order(self):
        a = '<meta property="og:image" content="https://x.test/a.png">'
        b = "<meta content='https://x.test/b.png' property='og:image' />"
        self.assertEqual(smoke_test.meta(a, "property", "og:image"), "https://x.test/a.png")
        self.assertEqual(smoke_test.meta(b, "property", "og:image"), "https://x.test/b.png")

    def test_missing(self):
        self.assertIsNone(smoke_test.meta("<meta name=description content=x>", "name", "robots"))


class ExtraHeaders(unittest.TestCase):
    def setUp(self):
        self._saved = (dict(smoke_test.EXTRA_HEADERS), smoke_test.SITE_NETLOC)
        smoke_test.EXTRA_HEADERS.clear()
        smoke_test.EXTRA_HEADERS["Authorization"] = "Basic secret"
        smoke_test.SITE_NETLOC = "staging.example.com"

    def tearDown(self):
        smoke_test.EXTRA_HEADERS.clear()
        smoke_test.EXTRA_HEADERS.update(self._saved[0])
        smoke_test.SITE_NETLOC = self._saved[1]

    def test_sent_to_site_over_https(self):
        self.assertIn("Authorization", smoke_test.request_headers("https://staging.example.com/about"))

    def test_not_sent_to_third_party_host(self):
        self.assertNotIn("Authorization", smoke_test.request_headers("https://cdn.other.test/og.png"))

    def test_not_sent_over_plain_http(self):
        self.assertNotIn("Authorization", smoke_test.request_headers("http://staging.example.com/"))


class CspParsing(unittest.TestCase):
    CONFIG = """
    const csp = [
      "default-src 'self'",
      `script-src 'self' 'unsafe-inline' https://www.googletagmanager.com`,
      "connect-src 'self' https://api.example.com https://*.google-analytics.com",
      'img-src 'self' data: https://images.example.com',
    ].join("; ");
    """

    def test_parses_all_quote_styles(self):
        csp = csp_hosts.parse_csp(self.CONFIG)
        self.assertEqual(csp["script-src"], {"www.googletagmanager.com"})
        self.assertEqual(csp["connect-src"], {"api.example.com", "*.google-analytics.com"})
        self.assertEqual(csp["img-src"], {"images.example.com"})

    def test_wildcard_matches_subdomain_only(self):
        self.assertTrue(csp_hosts.allowed("region1.google-analytics.com", {"*.google-analytics.com"}))
        self.assertFalse(csp_hosts.allowed("google-analytics.com", {"*.google-analytics.com"}))

    def test_guess_directive(self):
        self.assertEqual(csp_hosts.guess_directive('fetch("https://api.example.com/x")'), "connect-src")
        self.assertEqual(csp_hosts.guess_directive('<img src="https://cdn.x.test/a.png" />'), "img-src")
        self.assertEqual(csp_hosts.guess_directive('<iframe src="https://player.vimeo.com/1">'), "frame-src")
        self.assertIsNone(csp_hosts.guess_directive('<link rel="preconnect" href="https://x.test">'))
        self.assertIsNone(csp_hosts.guess_directive('sameAs: ["https://twitter.com/x"]'))


class CspHostsCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "src/app/api/contact").mkdir(parents=True)
        (root / "src/components").mkdir(parents=True)
        (root / "next.config.ts").write_text(
            'const csp = ["default-src \'self\'", "connect-src \'self\' https://api.example.com", '
            '"img-src \'self\' https://old-cdn.example.com"];\n')
        (root / "src/components/Form.tsx").write_text(
            'await fetch("https://api.example.com/contact");\n'
            'await fetch("https://forms.thirdparty.test/submit");\n')
        (root / "src/app/api/contact/route.ts").write_text('await fetch("https://internal.crm.test/hook");\n')
        (root / "src/components/Form.test.tsx").write_text('await fetch("https://mock.only-in-tests.test/x");\n')
        self.root = root

    def tearDown(self):
        self.tmp.cleanup()

    def test_reports_missing_unused_and_server_only(self):
        res = run("csp_hosts.py", str(self.root), "--json")
        self.assertEqual(res.returncode, 1, res.stderr)
        out = json.loads(res.stdout)
        self.assertEqual([m["host"] for m in out["missing"]], ["forms.thirdparty.test"])
        self.assertEqual(out["missing"][0]["missing_in"], ["connect-src"])
        self.assertEqual(out["unused"], ["old-cdn.example.com"])
        self.assertIn("api.example.com", out["ok"])
        self.assertIn("internal.crm.test", out["server_only"])
        self.assertNotIn("only-in-tests", res.stdout)

    def test_config_outside_repo(self):
        with tempfile.TemporaryDirectory() as other:
            cfg = Path(other) / "next.config.ts"
            cfg.write_text((self.root / "next.config.ts").read_text())
            res = run("csp_hosts.py", str(self.root), "--config", str(cfg), "--json")
        self.assertEqual(res.returncode, 1, res.stderr)
        self.assertEqual(json.loads(res.stdout)["config"], str(cfg))

    def test_no_config_exits_2(self):
        (self.root / "next.config.ts").unlink()
        self.assertEqual(run("csp_hosts.py", str(self.root)).returncode, 2)


class FakeSite(http.server.BaseHTTPRequestHandler):
    """A tiny production-like site; `staging = True` serves the noindex variant."""
    staging = False

    def log_message(self, *args):
        pass

    def _page(self, path: str) -> str:
        host = self.headers["Host"]
        robots = '<meta name="robots" content="noindex, nofollow">' if self.staging else ""
        return (f'<html><head><meta property="og:image" content="http://{host}/og.png">'
                f'<meta name="twitter:image" content="http://{host}/og.png">{robots}'
                f'<link rel="canonical" href="http://{host}{path}">'
                f'<script src="/_next/static/chunks/app.js"></script></head>'
                f'<body><h1>Title</h1><a href="/about">About</a></body></html>')

    def do_HEAD(self):
        self.do_GET(head=True)

    def do_GET(self, head: bool = False):
        host = self.headers["Host"]
        routes = {
            "/": ("text/html", self._page("/")),
            "/about": ("text/html", self._page("/about")),
            "/robots.txt": ("text/plain", "User-agent: *\nDisallow: /\n" if self.staging
                            else f"User-agent: *\nAllow: /\nSitemap: http://{host}/sitemap.xml\n"),
            "/sitemap.xml": ("application/xml", f"<urlset><url><loc>http://{host}/</loc></url>"
                             f"<url><loc>http://{host}/about</loc></url></urlset>"),
            "/og.png": ("image/png", "png"),
            "/_next/static/chunks/app.js": ("application/javascript", "1"),
        }
        ctype, body = routes.get(self.path, ("text/html", "not found"))
        self.send_response(200 if self.path in routes else 404)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Security-Policy", "default-src 'self'")
        self.send_header("Strict-Transport-Security", "max-age=63072000")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.end_headers()
        if not head:
            self.wfile.write(body.encode())


class SmokeTestCli(unittest.TestCase):
    def serve(self, staging: bool) -> str:
        handler = type("Handler", (FakeSite,), {"staging": staging})
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}"

    def test_healthy_production_passes(self):
        base = self.serve(staging=False)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "smoke.json"
            res = run("smoke_test.py", base, "--env", "production", "--json", str(out))
            self.assertEqual(res.returncode, 0, res.stdout)
            data = json.loads(out.read_text())
        self.assertEqual(data["failed"], 0)
        self.assertEqual(data["routes"], ["/", "/about"])

    def test_healthy_staging_passes(self):
        base = self.serve(staging=True)
        res = run("smoke_test.py", base, "--env", "staging", "--routes", "/,/about")
        self.assertEqual(res.returncode, 0, res.stdout)

    def test_indexable_staging_fails(self):
        base = self.serve(staging=False)
        res = run("smoke_test.py", base, "--env", "staging", "--routes", "/")
        self.assertEqual(res.returncode, 1)
        self.assertRegex(res.stdout, r"FAIL\s+robots\.txt disallows all")
        self.assertRegex(res.stdout, r"FAIL\s+meta robots noindex")

    def test_expect_build_mismatch_fails(self):
        base = self.serve(staging=False)
        res = run("smoke_test.py", base, "--env", "production", "--routes", "/", "--expect-build", "abc1234")
        self.assertEqual(res.returncode, 1)
        self.assertRegex(res.stdout, r"FAIL\s+expected build is live")

    def test_unreachable_exits_2(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        res = run("smoke_test.py", f"http://127.0.0.1:{port}", "--env", "production", "--timeout", "3")
        self.assertEqual(res.returncode, 2)

    def test_rejects_relative_url(self):
        res = run("smoke_test.py", "example.com", "--env", "production")
        self.assertEqual(res.returncode, 2)
        self.assertIn("absolute http(s) URL", res.stderr)


if __name__ == "__main__":
    unittest.main()
