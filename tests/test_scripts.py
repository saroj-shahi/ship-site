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


class LaunchContentCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        files = {
            "app/page.tsx": ('export const metadata = { title: "Create Next App" };\n'
                             '<p>[TBD: sample content, replace before launch]</p>\n'
                             '<input placeholder="Jane Doe" />\n'),
            "content/team.json": '{"photo": "https://www.old-site.com/wp-content/uploads/a.png"}\n',
            "content/legal.md": "To confirm: data retention period\n",
            "public/next.svg": "<svg/>",
            "docs/plan.md": "TBD lorem ipsum\n",
            "app/page.test.tsx": "lorem ipsum\n",
        }
        for rel, text in files.items():
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text(text)

    def tearDown(self):
        self.tmp.cleanup()

    def findings(self, *args: str) -> tuple[int, list[dict]]:
        res = run("launch_content.py", str(self.root), "--json", *args)
        return res.returncode, json.loads(res.stdout)["findings"]

    def test_reports_each_kind_and_skips_non_shipping(self):
        code, found = self.findings("--legacy-host", "old-site.com")
        self.assertEqual(code, 1)
        got = {(f["kind"], f["file"], f["line"]) for f in found}
        self.assertEqual(got, {
            ("scaffold", "app/page.tsx", 1),
            ("placeholder", "app/page.tsx", 2),
            ("legacy-link", "content/team.json", 1),
            ("placeholder", "content/legal.md", 1),
            ("scaffold", "public/next.svg", 0),
        })

    def test_input_placeholder_attribute_is_not_copy(self):
        _, found = self.findings()
        self.assertFalse([f for f in found if f["line"] == 3])

    def test_wordpress_path_flagged_without_legacy_host(self):
        _, found = self.findings()
        self.assertIn("WordPress upload path", {f["match"] for f in found})

    def test_clean_repo_exits_0(self):
        clean = self.root / "clean"
        (clean / "app").mkdir(parents=True)
        (clean / "app" / "page.tsx").write_text("<h1>Modernize your contact center</h1>\n")
        self.assertEqual(run("launch_content.py", str(clean)).returncode, 0)


class BuildReportCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.tmp.name) / "run1"
        self.write("findings/security.json", {
            "area": "security", "passed": ["HSTS"], "not_checked": ["rate limit: no staging access"],
            "findings": [{"severity": "blocker", "title": "CSP connect-src missing api.example.com",
                          "file": "next.config.ts", "line": 37, "fix": "Add the host.",
                          "verify": "csp_hosts.py exits 0", "effort": "S"}]})
        self.write("findings/seo.json", {"area": "seo", "findings": [
            {"severity": "should-fix", "title": "CSP connect-src missing api.example.com",
             "file": "next.config.ts", "line": 37},
            {"severity": "blocker", "title": "Privacy policy is placeholder", "file": "src/app/privacy/page.tsx",
             "owner": "client", "effort": "M"},
            {"severity": "nice to have", "title": "Long title", "file": "src/app/about/page.tsx", "line": 3},
            {"severity": "should-fix", "title": "Footer links old host", "known_preexisting": True}]})
        self.write("gates.json", {"lint": "pass", "build": {"status": "pass"},
                                  "playwright": {"status": "fail", "detail": "3 failed"}})
        self.write("state.json", {"mode": "audit", "repo": "/x/acme-site", "release": {"steps": [
            {"step": "Push", "command": "git push -u origin feat/x", "approval": True}]}})

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel: str, data, run_dir: Path | None = None) -> None:
        path = (run_dir or self.run_dir) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))

    def build(self, *args: str, run_dir: Path | None = None) -> tuple[int, dict]:
        res = run("build_report.py", str(run_dir or self.run_dir), "--json", *args)
        self.assertNotEqual(res.returncode, 2, res.stderr)
        return res.returncode, json.loads(res.stdout)

    def test_merges_duplicates_and_computes_no_go(self):
        code, out = self.build()
        self.assertEqual((code, out["verdict"]), (1, "NO-GO"))
        by_id = {f["id"]: f for f in out["findings"]}
        self.assertEqual(sorted(by_id), ["B1", "B2", "K1", "N1"])
        self.assertEqual(by_id["B1"]["sources"], ["security", "seo"])  # deduped, highest severity kept
        self.assertEqual(by_id["B2"]["owner"], "owner")
        self.assertIn("failed gate: playwright", "; ".join(out["reasons"]))
        self.assertIn("design", out["missing_areas"])

    def test_report_and_plan_contents(self):
        self.build()
        report = (self.run_dir / "report.md").read_text()
        plan = (self.run_dir / "plan.md").read_text()
        self.assertIn("**Verdict: NO-GO**", report)
        self.assertIn("rate limit: no staging access", report)
        self.assertIn("**Design:** no findings recorded — not run", report)
        self.assertIn("| **Total open** | **2** | **0** | **1** | **1** |", report)
        agent = plan.index("Required before launch — agent can fix")
        owner = plan.index("Required before launch — needs the owner")
        self.assertLess(agent, plan.index("**B1**"), "agent-fixable Blocker under its section")
        self.assertLess(owner, plan.index("**B2**"))
        self.assertIn("Verify: csp_hosts.py exits 0", plan)
        self.assertIn("## Owner inputs to request", plan)
        self.assertIn("- [ ] ⏸ Push — `git push -u origin feat/x`", plan)
        self.assertIn("- [ ] playwright — last: fail, 3 failed", plan)

    def test_fixes_keep_ids_and_reach_go(self):
        self.build()
        sec = json.loads((self.run_dir / "findings/security.json").read_text())
        sec["findings"][0].update(status="fixed", fix_evidence="csp_hosts.py exit 0")
        self.write("findings/security.json", sec)
        seo = json.loads((self.run_dir / "findings/seo.json").read_text())
        seo["findings"][1]["status"] = "accepted"
        self.write("findings/seo.json", seo)
        self.write("gates.json", {"lint": "pass", "build": "pass", "playwright": "pass"})
        code, out = self.build()
        self.assertEqual((code, out["verdict"]), (0, "GO"))
        self.assertEqual({f["id"] for f in out["findings"] if f["bucket"] == "blocker"}, {"B1", "B2"})
        self.assertIn("- [x] **B1**", (self.run_dir / "plan.md").read_text())

    def test_unrun_gate_or_unverified_fix_is_go_pending(self):
        sec = json.loads((self.run_dir / "findings/security.json").read_text())
        sec["findings"][0]["status"] = "could-not-verify"
        self.write("findings/security.json", sec)
        seo = json.loads((self.run_dir / "findings/seo.json").read_text())
        seo["findings"][1]["status"] = "fixed"
        self.write("findings/seo.json", seo)
        self.write("gates.json", {"build": "pass", "playwright": "not-run"})
        code, out = self.build()
        self.assertEqual((code, out["verdict"]), (1, "GO pending"))
        self.assertIn("B1", "; ".join(out["reasons"]))

    def test_previous_run_delta(self):
        self.build()
        run2 = Path(self.tmp.name) / "run2"
        self.write("findings/seo.json", {"area": "seo", "findings": [
            {"severity": "blocker", "title": "Privacy policy is placeholder", "file": "src/app/privacy/page.tsx"},
            {"severity": "should-fix", "title": "New issue", "file": "a.ts"}]}, run_dir=run2)
        _, out = self.build("--previous", str(self.run_dir), run_dir=run2)
        self.assertEqual(out["delta"]["new"], "S1")
        self.assertEqual(out["delta"]["still_open"], "B2")
        self.assertIn("B1", out["delta"]["resolved"])

    def test_bad_input_exits_2(self):
        self.write("findings/x.json", {"area": "x", "findings": [{"severity": "huge", "title": "t"}]})
        res = run("build_report.py", str(self.run_dir))
        self.assertEqual(res.returncode, 2)
        self.assertIn("unknown severity", res.stderr)
        self.assertEqual(run("build_report.py", str(Path(self.tmp.name) / "nope")).returncode, 2)


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
        redirects = {"/old-about/": "/old-about", "/old-about": "/about", "/old-gone": "/"}
        if self.path in redirects:
            self.send_response(301)
            self.send_header("Location", redirects[self.path])
            self.end_headers()
            return
        routes["/old-sitemap.xml"] = ("application/xml", f"<sitemapindex><sitemap><loc>http://{host}/old-sitemap-1.xml"
                                      f"</loc></sitemap></sitemapindex>")
        routes["/old-sitemap-1.xml"] = ("application/xml", f"<urlset><url><loc>http://{host}/old-about</loc></url>"
                                        f"<url><loc>http://{host}/about</loc></url></urlset>")
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

    def test_legacy_sitemap_index_redirects_pass(self):
        base = self.serve(staging=False)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "smoke.json"
            res = run("smoke_test.py", base, "--env", "production", "--routes", "/",
                      "--legacy-urls", f"{base}/old-sitemap.xml", "--json", str(out))
            self.assertEqual(res.returncode, 0, res.stdout)
            legacy = [r for r in json.loads(out.read_text())["results"] if r["check"] == "legacy URL resolves"]
        self.assertEqual(sorted(r["target"] for r in legacy), ["/about", "/old-about"])

    def test_legacy_home_dump_and_404_fail(self):
        base = self.serve(staging=False)
        with tempfile.TemporaryDirectory() as d:
            urls = Path(d) / "legacy.txt"
            urls.write_text("# old WordPress paths\n/old-about/\n/old-gone\nhttps://old.example.com/old-missing\n")
            res = run("smoke_test.py", base, "--env", "production", "--routes", "/", "--legacy-urls", str(urls))
        self.assertEqual(res.returncode, 1)
        self.assertRegex(res.stdout, r"PASS\s+legacy URL resolves\s+/old-about/ .*chain")
        self.assertRegex(res.stdout, r"FAIL\s+legacy URL resolves\s+/old-gone .*soft 404")
        self.assertRegex(res.stdout, r"FAIL\s+legacy URL resolves\s+/old-missing .*status=404")

    def test_rejects_relative_url(self):
        res = run("smoke_test.py", "example.com", "--env", "production")
        self.assertEqual(res.returncode, 2)
        self.assertIn("absolute http(s) URL", res.stderr)


REPO = SCRIPTS.parent.parent.parent
SKILL_DIR = SCRIPTS.parent


class Installer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def install(self, *args: str) -> subprocess.CompletedProcess:
        env = {"HOME": str(self.home), "PATH": "/usr/bin:/bin", "USERPROFILE": str(self.home)}
        return subprocess.run([sys.executable, str(REPO / "install.py"), *args],
                              capture_output=True, text=True, timeout=60, env=env)

    def test_default_links_shared_folder_once(self):
        res = self.install()
        self.assertEqual(res.returncode, 0, res.stderr)
        dest = self.home / ".agents" / "skills" / "ship-site"
        self.assertTrue(dest.is_symlink())
        self.assertEqual(dest.resolve(), SKILL_DIR.resolve())
        self.assertIn("already linked", self.install().stdout)

    def test_project_copy_for_copilot(self):
        proj = Path(self.tmp.name) / "site"
        proj.mkdir()
        res = self.install("--project", str(proj), "--agent", "copilot", "--copy")
        self.assertEqual(res.returncode, 0, res.stderr)
        dest = proj / ".github" / "skills" / "ship-site"
        self.assertFalse(dest.is_symlink())
        self.assertTrue((dest / "SKILL.md").is_file())
        self.assertTrue((dest / "scripts" / "smoke_test.py").is_file())

    def test_foreign_folder_left_alone_without_force(self):
        dest = self.home / ".gemini" / "skills" / "ship-site"
        dest.mkdir(parents=True)
        (dest / "mine.txt").write_text("keep")
        self.assertIn("left alone", self.install("--agent", "gemini").stdout)
        self.assertIn("left alone", self.install("--agent", "gemini", "--uninstall").stdout)
        self.assertTrue((dest / "mine.txt").is_file())

    def test_warns_when_an_agent_would_see_two_copies(self):
        res = self.install("--agent", "agents", "--agent", "claude")
        self.assertRegex(res.stdout, r"warning: (copilot|opencode) reads ship-site from 2 folders")

    def test_uninstall_removes_only_our_link(self):
        self.install("--agent", "all")
        res = self.install("--agent", "all", "--uninstall")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertFalse(list(self.home.rglob("ship-site")))


class SkillPortability(unittest.TestCase):
    """The SKILL.md must load in any Agent Skills host, not only Claude Code."""

    def frontmatter(self) -> dict[str, str]:
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        block = text.split("---\n", 2)[1]
        return dict(line.split(": ", 1) for line in block.strip().splitlines())

    def test_frontmatter_keys_and_limits(self):
        fm = self.frontmatter()
        # Codex rejects keys outside this set; the Agent Skills spec caps description at 1024.
        self.assertLessEqual(set(fm), {"name", "description", "license", "metadata", "allowed-tools"})
        self.assertEqual(fm["name"], SKILL_DIR.name)
        self.assertRegex(fm["name"], r"^[a-z0-9]+(-[a-z0-9]+)*$")
        self.assertLessEqual(len(fm["description"]), 1024)
        self.assertNotIn(": ", fm["description"], "a plain YAML scalar can't contain ': '")

    def test_no_host_specific_substitutions(self):
        for f in SKILL_DIR.rglob("*.md"):
            text = f.read_text(encoding="utf-8")
            for token in ("${CLAUDE_", "$CLAUDE_", "$ARGUMENTS", "${ARGUMENTS}"):
                self.assertNotIn(token, text, f"{f.name} uses {token}, which other hosts leave literal")


if __name__ == "__main__":
    unittest.main()
