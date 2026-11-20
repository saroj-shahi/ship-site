#!/usr/bin/env python3
"""Rebuild examples/sample-run and re-render the README screenshots of report.md and plan.md.

Maintainer tool, not part of the skill. Needs:
  - gh, authenticated (GitHub's markdown API renders exactly what github.com shows)
  - Google Chrome or Chromium (headless screenshot); set CHROME=/path/to/chrome if it isn't found
  - network access for github-markdown-css from jsdelivr

Usage: python3 tools/render_readme_shots.py
Writes assets/readme/report.png and assets/readme/plan.png.
"""
from __future__ import annotations

import html
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUN = ROOT / "examples" / "sample-run"
OUT = ROOT / "assets" / "readme"
CSS = "https://cdn.jsdelivr.net/npm/github-markdown-css@5.8.1/github-markdown-dark.css"
CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
]

PAGE = """<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="{css}"><style>
html,body{{margin:0;background:#080808}}
body{{padding:40px;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
.frame{{position:relative;height:900px;border:1px solid #2a2a2a;border-radius:14px;overflow:hidden;background:#0d1117;
  box-shadow:0 30px 80px rgba(245,158,11,.10)}}
.bar{{display:flex;align-items:center;gap:8px;padding:12px 16px;background:#161616;border-bottom:1px solid #2a2a2a}}
.dot{{width:12px;height:12px;border-radius:50%}}
.name{{flex:1;text-align:center;color:#8b8b8b;font:13px ui-monospace,SFMono-Regular,Menlo,monospace;margin-right:52px}}
.tag{{color:#f59e0b}}
.fade{{position:absolute;left:0;right:0;bottom:0;height:160px;background:linear-gradient(rgba(13,17,23,0),#0d1117 85%)}}
.markdown-body{{padding:28px 36px 36px;font-size:15px;background:#0d1117}}
.markdown-body table{{font-size:13.5px}}
</style></head><body><div class="frame"><div class="bar">
<span class="dot" style="background:#ff5f57"></span><span class="dot" style="background:#febc2e"></span>
<span class="dot" style="background:#28c840"></span>
<span class="name">.ship-site/2026-11-20T14-02/<span class="tag">{name}</span></span></div>
<article class="markdown-body">{body}</article><div class="fade"></div></div></body></html>"""


def chrome() -> str:
    for c in [os.environ.get("CHROME")] + CHROME_CANDIDATES:
        if c and (Path(c).exists() or shutil.which(c)):
            return c
    sys.exit("Chrome not found: set CHROME=/path/to/chrome")


def main() -> None:
    subprocess.run([sys.executable, str(ROOT / "skills/ship-site/scripts/build_report.py"), str(RUN),
                    "--title", "studio-site v1.4.0"], check=False)
    browser = chrome()
    with tempfile.TemporaryDirectory() as tmp:
        for name in ("report.md", "plan.md"):
            body = subprocess.run(["gh", "api", "markdown", "-f", "mode=gfm", "-f",
                                   "text=" + (RUN / name).read_text(encoding="utf-8")],
                                  check=True, capture_output=True, text=True).stdout
            page = Path(tmp) / (name + ".html")
            page.write_text(PAGE.format(css=CSS, name=html.escape(name), body=body), encoding="utf-8")
            png = OUT / name.replace(".md", ".png")
            subprocess.run([browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                            "--force-device-scale-factor=1.5", "--window-size=960,980",
                            f"--screenshot={png}", page.as_uri()], check=True, capture_output=True)
            print(f"wrote {png.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
