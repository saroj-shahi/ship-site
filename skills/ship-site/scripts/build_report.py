#!/usr/bin/env python3
"""Merge a run's findings and gate results into report.md, plan.md and findings.json.

The audits (subagents and the orchestrator) each write findings JSON; the gates
(lint, build, Playwright, smoke) each produce a pass/fail. Merging those by hand
is where reports go wrong: duplicates counted twice, a Blocker dropped, a GO
declared while a gate never ran. This script does the merge deterministically so
the agent spends its effort on the findings, not the bookkeeping.

Usage:
  build_report.py <run_dir> [--previous <earlier_run_dir>] [--summary "..."]
                  [--title "repo v1.4.1"] [--json]

Reads (all inside <run_dir>):
  findings/*.json   one file per area: {"area", "checked", "findings", "passed", "not_checked"}
  gates.json        {"lint": {"status": "pass|fail|flaky|not-run", "detail": "...", "log": "logs/lint.log"}, ...}
  state.json        optional: mode, repo, base, head_sha, detected, version, replatform,
                    release.steps [{"step", "command", "approval", "done"}]
Writes:
  report.md         the go/no-go report (references/report-format.md)
  plan.md           the ordered work plan: required before GO, recommended, owner inputs,
                    re-verification, release steps, backlog
  findings.json     merged findings with stable IDs (B1, S2, N3, K1); feeds --previous

Finding IDs persist across re-runs in the same folder: re-running after fixes
keeps B1 as B1. Exit 0 = GO, 1 = NO-GO or GO pending, 2 = bad input.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

SEVERITIES = ("blocker", "should-fix", "nice-to-have")
SEV_PREFIX = {"blocker": "B", "should-fix": "S", "nice-to-have": "N", "known": "K"}
SEV_ALIASES = {"blocker": "blocker", "should-fix": "should-fix", "should fix": "should-fix",
               "shouldfix": "should-fix", "major": "should-fix", "nice-to-have": "nice-to-have",
               "nice to have": "nice-to-have", "nit": "nice-to-have", "minor": "nice-to-have"}
AREA_LABELS = {"knowledge-base": "Knowledge base", "launch-content": "Launch content",
               "design": "Design", "code": "Code", "security": "Security", "seo": "SEO",
               "analytics": "Analytics", "a11y-perf": "A11y / Perf", "browser": "Browser",
               "tests": "Tests", "build": "Build", "migration": "Replatform", "smoke": "Smoke"}
# Areas a full audit is expected to cover; a missing file means "not run", never "clean".
AUDIT_AREAS = ("knowledge-base", "launch-content", "design", "code", "security", "seo",
               "analytics", "a11y-perf", "browser")
AUDIT_MODES = {"audit", "fix", "full", None}
OWNERS = {"agent": "agent", "owner": "owner", "client": "owner", "decision": "decision"}
DONE = {"fixed", "accepted"}
STATUS_LABEL = {"open": "open", "fixed": "fixed", "skipped": "skipped",
                "could-not-verify": "could not verify", "accepted": "risk accepted"}
GATE_ICON = {"pass": "✅", "fail": "❌", "flaky": "⚠️ flaky", "not-run": "— not run"}
EFFORT_RANK = {"S": 0, "M": 1, "L": 2}


class InputError(Exception):
    pass


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise InputError(f"{path}: {e}") from e


def norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def fingerprint(f: dict) -> str:
    """Identity across runs: file + title, not line (lines move when code above changes)."""
    key = f"{f.get('file') or ''}|{norm_title(f['title'])}"
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def norm_severity(raw, where: str) -> str:
    sev = SEV_ALIASES.get(str(raw or "").strip().lower())
    if not sev:
        raise InputError(f"{where}: unknown severity {raw!r} (use blocker | should-fix | nice-to-have)")
    return sev


def read_findings(run: Path) -> tuple[list[dict], dict[str, dict]]:
    fdir = run / "findings"
    if not fdir.is_dir():
        raise InputError(f"{fdir} not found: write one findings JSON per audit area there first")
    raw, areas = [], {}
    for path in sorted(fdir.glob("*.json")):
        data = load_json(path)
        if not isinstance(data, dict):
            raise InputError(f"{path}: expected an object with 'area' and 'findings'")
        area = str(data.get("area") or path.stem)
        info = areas.setdefault(area, {"checked": [], "passed": [], "not_checked": []})
        for k in info:
            info[k].extend(str(x) for x in data.get(k) or [])
        for i, f in enumerate(data.get("findings") or []):
            where = f"{path.name} finding {i + 1}"
            if not f.get("title"):
                raise InputError(f"{where}: missing title")
            f = dict(f)
            f["severity"] = norm_severity(f.get("severity"), where)
            f["area"] = str(f.get("area") or area)
            f["owner"] = OWNERS.get(str(f.get("owner") or "agent").lower(), "agent")
            f["effort"] = str(f.get("effort") or "").upper()[:1] or None
            f["status"] = str(f.get("status") or "open").lower().replace(" ", "-")
            raw.append(f)
    if not raw and not areas:
        raise InputError(f"{fdir} has no findings files")
    return raw, areas


def merge(raw: list[dict]) -> list[dict]:
    """Same file:line and same title from several audits = one finding, highest severity wins."""
    merged: dict[tuple, dict] = {}
    for f in raw:
        key = (f.get("file") or f"area:{f['area']}", f.get("line"), norm_title(f["title"]))
        cur = merged.get(key)
        if cur is None:
            f["sources"] = [f["area"]]
            merged[key] = f
            continue
        if f["area"] not in cur["sources"]:
            cur["sources"].append(f["area"])
        if SEVERITIES.index(f["severity"]) < SEVERITIES.index(cur["severity"]):
            cur["severity"] = f["severity"]
        for k in ("problem", "fix", "evidence", "verify", "effort", "fix_evidence"):
            if not cur.get(k) and f.get(k):
                cur[k] = f[k]
        cur["known_preexisting"] = cur.get("known_preexisting") and f.get("known_preexisting")
    out = list(merged.values())
    for f in out:
        f["fingerprint"] = fingerprint(f)
        f["bucket"] = "known" if f.get("known_preexisting") else f["severity"]
    return out


def assign_ids(findings: list[dict], previous_ids: dict[str, str]) -> None:
    """Reuse the ID a finding had in this run folder before; new findings take the next number."""
    order = {s: i for i, s in enumerate(SEVERITIES + ("known",))}
    findings.sort(key=lambda f: (order[f["bucket"]], f["owner"] != "agent",
                                 EFFORT_RANK.get(f.get("effort") or "", 1),
                                 f["area"], f.get("file") or "", f.get("line") or 0))
    used: dict[str, set[int]] = {p: set() for p in SEV_PREFIX.values()}
    for f in findings:
        prev = previous_ids.get(f["fingerprint"])
        prefix = SEV_PREFIX[f["bucket"]]
        if prev and prev[0] == prefix and prev[1:].isdigit() and int(prev[1:]) not in used[prefix]:
            f["id"] = prev
            used[prefix].add(int(prev[1:]))
    for f in findings:
        if "id" not in f:
            prefix = SEV_PREFIX[f["bucket"]]
            n = 1
            while n in used[prefix]:
                n += 1
            used[prefix].add(n)
            f["id"] = f"{prefix}{n}"


def read_gates(run: Path) -> dict[str, dict]:
    path = run / "gates.json"
    if not path.exists():
        return {}
    data = load_json(path)
    gates = {}
    for name, g in (data or {}).items():
        g = {"status": g} if isinstance(g, str) else dict(g)
        status = str(g.get("status") or "not-run").lower().replace(" ", "-")
        g["status"] = {"passed": "pass", "ok": "pass", "failed": "fail", "skipped": "not-run"}.get(status, status)
        gates[name] = g
    return gates


def verdict(findings: list[dict], gates: dict[str, dict]) -> tuple[str, list[str]]:
    open_blockers = [f for f in findings if f["bucket"] == "blocker" and f["status"] not in DONE]
    unverified = [f for f in findings if f["bucket"] == "blocker" and f["status"] == "could-not-verify"]
    failed = [n for n, g in gates.items() if g["status"] == "fail"]
    pending_gates = [n for n, g in gates.items() if g["status"] in ("not-run", "flaky")]
    reasons = []
    hard_blockers = [f for f in open_blockers if f not in unverified]
    if hard_blockers:
        reasons.append(f"{len(hard_blockers)} open Blocker{'s' if len(hard_blockers) != 1 else ''} "
                       f"({', '.join(f['id'] for f in hard_blockers)})")
    if failed:
        reasons.append("failed gate: " + ", ".join(failed))
    if reasons:
        return "NO-GO", reasons
    if unverified:
        reasons.append("Blocker fix not verified: " + ", ".join(f["id"] for f in unverified))
    if pending_gates:
        reasons.append("gate not run or flaky: " + ", ".join(pending_gates))
    if not gates:
        reasons.append("no gate results recorded (gates.json missing)")
    if reasons:
        return "GO pending", reasons
    return "GO", ["zero open Blockers and every recorded gate passed"]


def compare(findings: list[dict], previous: list[dict] | None) -> dict | None:
    if previous is None:
        return None
    now = {f["fingerprint"]: f for f in findings if f["status"] not in DONE}
    before = {f["fingerprint"]: f for f in previous if f.get("status", "open") not in DONE}
    return {"new": [f for k, f in now.items() if k not in before],
            "resolved": [f for k, f in before.items() if k not in now],
            "still_open": [f for k, f in now.items() if k in before]}


def loc(f: dict) -> str:
    if not f.get("file"):
        return ""
    return f"`{f['file']}:{f['line']}`" if f.get("line") else f"`{f['file']}`"


def ids(fs: list[dict]) -> str:
    return ", ".join(f.get("id", "?") for f in fs) or "none"


def area_label(a: str) -> str:
    return AREA_LABELS.get(a, a.replace("-", " ").capitalize())


# ---------------------------------------------------------------- report.md

def render_report(ctx: dict) -> str:
    f_all, gates, state = ctx["findings"], ctx["gates"], ctx["state"]
    v, reasons = ctx["verdict"]
    L = [f"# Release readiness — {ctx['title']} — {ctx['date']}", ""]
    summary = ctx["summary"] or "; ".join(reasons) + "."
    L.append(f"**Verdict: {v}** — {summary}")
    if v != "GO":
        L += ["", "**Shortest path to GO** (details in `plan.md`):"]
        L += [f"- {step}" for step in path_to_go(ctx)[:5]]
    L.append("")

    areas = sorted({f["area"] for f in f_all} | set(ctx["areas"]), key=lambda a: (
        list(AREA_LABELS).index(a) if a in AREA_LABELS else 99, a))
    L += ["| | Blockers | Should-fix | Nice-to-have | Known |", "|---|---|---|---|---|"]
    def counts(fs):
        return [sum(1 for f in fs if f["bucket"] == b and f["status"] not in DONE) for b in SEVERITIES + ("known",)]
    for a in areas:  # a finding several audits raised counts once, under the first area that raised it
        L.append(f"| {area_label(a)} | " + " | ".join(str(n) for n in counts(
            [f for f in f_all if f["area"] == a])) + " |")
    L.append("| **Total open** | " + " | ".join(f"**{n}**" for n in counts(f_all)) + " |")
    L.append("")
    if gates:
        L.append("**Gates:** " + " · ".join(
            f"{n} {GATE_ICON.get(g['status'], g['status'])}" + (f" ({g['detail']})" if g.get("detail") else "")
            for n, g in gates.items()))
    detected = state.get("detected")
    if isinstance(detected, dict):
        detected = " · ".join(f"{k} {v_}" for k, v_ in detected.items())
    if detected:
        L.append(f"Detected: {detected}")
    if state.get("head_sha"):
        L.append(f"Commit: `{state['head_sha']}`" + (f" on `{state['branch']}`" if state.get("branch") else ""))
    L.append("")

    delta = ctx["delta"]
    if delta:
        L += ["## Since the last run", "",
              f"- New: {len(delta['new'])} ({ids(delta['new'])})",
              f"- Resolved: {len(delta['resolved'])} ({ids(delta['resolved'])})",
              f"- Still open: {len(delta['still_open'])} ({ids(delta['still_open'])})", ""]

    titles = {"blocker": "Blockers", "should-fix": "Should-fix", "nice-to-have": "Nice-to-have"}
    for sev in SEVERITIES:
        fs = [f for f in f_all if f["bucket"] == sev]
        L += [f"## {titles[sev]}", ""]
        if not fs:
            L += ["None.", ""]
            continue
        for f in fs:
            L.append(f"### {f['id']}. {f['title']}")
            rows = [("Where", loc(f)), ("Area", ", ".join(area_label(s) for s in f["sources"])),
                    ("Problem", f.get("problem")), ("Fix", f.get("fix")), ("Evidence", f.get("evidence")),
                    ("Owner", {"owner": "owner/client must supply", "decision": "needs a decision"}.get(f["owner"]))]
            if f["status"] != "open" or state.get("mode") == "fix":
                st = STATUS_LABEL.get(f["status"], f["status"])
                if f.get("fix_evidence"):
                    st += f" — {f['fix_evidence']}"
                rows.append(("Status", st))
            L += [f"- **{k}:** {val}" for k, val in rows if val]
            L.append("")

    known = [f for f in f_all if f["bucket"] == "known"]
    L += ["## Known, pre-existing (from the repo's instructions)", ""]
    L += [f"- **{f['id']}** {f['title']} {loc(f)}".rstrip() for f in known] or ["None recorded."]
    L.append("")

    L += ["## What passed", ""]
    passed = [(a, ctx["areas"][a]["passed"]) for a in areas if a in ctx["areas"] and ctx["areas"][a]["passed"]]
    L += [f"- **{area_label(a)}:** {'; '.join(p)}" for a, p in passed] or ["Nothing recorded as passed."]
    L.append("")

    gaps = [(a, ctx["areas"][a]["not_checked"]) for a in areas if a in ctx["areas"] and ctx["areas"][a]["not_checked"]]
    missing = ctx["missing_areas"]
    L += ["## Not checked", ""]
    L += [f"- **{area_label(a)}:** {'; '.join(n)}" for a, n in gaps]
    L += [f"- **{area_label(a)}:** no findings recorded — not run" for a in missing]
    L += [f"- **Gate {n}:** not run" + (f" — {g['detail']}" if g.get("detail") else "")
          for n, g in gates.items() if g["status"] == "not-run"]
    if L[-1] == "":
        L.append("Everything in scope was checked.")
    L.append("")

    L += ["## Evidence index", "",
          "- Screenshots: `screenshots/`", "- Logs: `logs/`", "- Findings: `findings/*.json`, merged in `findings.json`",
          "- Plan: `plan.md`"]
    L += [f"- Gate log, {n}: `{g['log']}`" for n, g in gates.items() if g.get("log")]
    return "\n".join(L).rstrip() + "\n"


# ---------------------------------------------------------------- plan.md

def path_to_go(ctx: dict) -> list[str]:
    f_all, gates = ctx["findings"], ctx["gates"]
    steps = []
    blockers = [f for f in f_all if f["bucket"] == "blocker" and f["status"] not in DONE]
    agent = [f for f in blockers if f["owner"] == "agent"]
    other = [f for f in blockers if f["owner"] != "agent"]
    if agent:
        steps.append(f"Fix {len(agent)} Blocker{'s' if len(agent) != 1 else ''} the agent can fix: {ids(agent)}")
    if other:
        steps.append(f"Get owner input or a decision for {ids(other)}")
    redo = [n for n, g in gates.items() if g["status"] != "pass"]
    if redo:
        steps.append("Re-run until green: " + ", ".join(redo))
    if not gates:
        steps.append("Run the build gate and tests, and record them in gates.json")
    return steps


def task(f: dict) -> list[str]:
    done = f["status"] in DONE
    meta = " · ".join(x for x in (loc(f), f.get("effort") and f"effort {f['effort']}",
                                  area_label(f["area"])) if x)
    lines = [f"- [{'x' if done else ' '}] **{f['id']}** {f['title']}" + (f" — {meta}" if meta else "")]
    if f["status"] not in ("open",) and not done:
        lines[0] += f" _({STATUS_LABEL.get(f['status'], f['status'])})_"
    if f.get("fix"):
        lines.append(f"  - Do: {f['fix']}")
    lines.append(f"  - Verify: {f.get('verify') or 're-run the check in the Evidence line of report.md and attach its output'}")
    return lines


def render_plan(ctx: dict) -> str:
    f_all, gates, state = ctx["findings"], ctx["gates"], ctx["state"]
    v, reasons = ctx["verdict"]
    open_ = [f for f in f_all if f["status"] not in DONE]
    L = [f"# Launch plan — {ctx['title']} — {ctx['date']}", "",
         f"**Now: {v}** — {'; '.join(reasons)}.", ""]
    if v != "GO":
        L += ["**Path to GO:**"] + [f"{i}. {s}" for i, s in enumerate(path_to_go(ctx), 1)] + [""]

    def section(title: str, intro: str, fs: list[dict]) -> None:
        nonlocal L
        if not fs:
            return
        effort = {e: sum(1 for f in fs if f.get("effort") == e) for e in "SML"}
        sized = ", ".join(f"{n}×{e}" for e, n in effort.items() if n)
        L += [f"## {title}", "", intro + (f" Effort: {sized}." if sized else ""), ""]
        for f in fs:
            L += task(f)
        L.append("")

    blockers = [f for f in f_all if f["bucket"] == "blocker"]
    section("1. Required before launch — agent can fix",
            "Clear these first, in order. One fix per commit; re-run its check before moving on.",
            [f for f in blockers if f["owner"] == "agent"])
    section("2. Required before launch — needs the owner",
            "Content, credentials or decisions only the site owner can supply. Never invent them to close the item.",
            [f for f in blockers if f["owner"] != "agent"])
    should = [f for f in f_all if f["bucket"] == "should-fix"]
    section("3. Recommended before launch",
            "Real defects with limited blast radius. Fix now if cheap, or schedule with a date.",
            sorted(should, key=lambda f: (f["owner"] != "agent", EFFORT_RANK.get(f.get("effort") or "", 1))))

    inputs = [f for f in open_ if f["owner"] != "agent" and f["bucket"] != "known"]
    if inputs:
        L += ["## Owner inputs to request", "",
              "One list to send to the owner/client, all severities:", ""]
        L += [f"- [ ] **{f['id']}** {f['title']}" + (f" — {f['fix']}" if f.get("fix") else "") for f in inputs]
        L.append("")

    redo = [(n, g) for n, g in gates.items() if g["status"] != "pass"]
    L += ["## Re-verify", "", "After the fixes above, re-run in this order and record each in `gates.json`:", ""]
    L += [f"- [ ] {n}" + (f" — last: {g['status']}" + (f", {g['detail']}" if g.get("detail") else "")) for n, g in redo]
    L += ["- [ ] Build gate in full (lint, format, typecheck, build) and the Playwright suite",
          "- [ ] `build_report.py` again: the verdict must read GO", ""]

    steps = (state.get("release") or {}).get("steps") or []
    if steps:
        L += ["## Release", "", "⏸ = stop and ask; one approval covers one step.", ""]
        for s in steps:
            s = {"step": s} if isinstance(s, str) else s
            mark = "x" if s.get("done") else " "
            pause = "⏸ " if s.get("approval") else ""
            cmd = f" — `{s['command']}`" if s.get("command") else ""
            L.append(f"- [{mark}] {pause}{s.get('step', '')}{cmd}")
        L.append("")
    elif state.get("mode") in (None, "full", "release"):
        L += ["## Release", "", "Not planned yet: run the release flow (step 11) once the verdict is GO.", ""]

    section("Backlog — after launch", "Polish. Doesn't block GO.",
            [f for f in f_all if f["bucket"] == "nice-to-have"])
    known = [f for f in open_ if f["bucket"] == "known"]
    if known:
        L += ["## Known, pre-existing — not in this plan", "",
              "Documented in the repo's instructions; left alone unless the owner asks.", ""]
        L += [f"- **{f['id']}** {f['title']}" for f in known]
        L.append("")
    return "\n".join(L).rstrip() + "\n"


# ---------------------------------------------------------------- main

def build(run: Path, previous: Path | None, summary: str | None, title: str | None) -> dict:
    state = load_json(run / "state.json") if (run / "state.json").exists() else {}
    raw, areas = read_findings(run)
    findings = merge(raw)
    merged_path = run / "findings.json"
    prev_ids = {}
    if merged_path.exists():
        prev_ids = {f["fingerprint"]: f["id"] for f in load_json(merged_path).get("findings", [])
                    if f.get("fingerprint") and f.get("id")}
    prev_findings = None
    if previous:
        p = previous / "findings.json"
        if not p.exists():
            raise InputError(f"{p} not found: --previous needs a run folder this script has built")
        prev_findings = load_json(p).get("findings", [])
        for f in prev_findings:
            prev_ids.setdefault(f.get("fingerprint"), f.get("id"))
    assign_ids(findings, prev_ids)
    gates = read_gates(run)
    mode = state.get("mode")
    missing = [a for a in AUDIT_AREAS if mode in AUDIT_MODES and a not in areas
               and not any(a in f["sources"] for f in findings)]
    repo = state.get("repo")
    ctx = {
        "findings": findings, "areas": areas, "gates": gates, "state": state, "summary": summary,
        "title": title or " ".join(x for x in (Path(repo).name if repo else run.name,
                                               state.get("version") or state.get("branch")) if x),
        "date": dt.date.today().isoformat(), "missing_areas": missing,
        "delta": compare(findings, prev_findings),
    }
    ctx["verdict"] = verdict(findings, gates)
    (run / "report.md").write_text(render_report(ctx), encoding="utf-8")
    (run / "plan.md").write_text(render_plan(ctx), encoding="utf-8")
    keep = ("id", "fingerprint", "bucket", "severity", "area", "sources", "title", "file", "line",
            "problem", "fix", "evidence", "verify", "owner", "effort", "status", "fix_evidence",
            "known_preexisting")
    merged = {"verdict": ctx["verdict"][0], "reasons": ctx["verdict"][1],
              "findings": [{k: f[k] for k in keep if f.get(k) is not None} for f in findings]}
    merged_path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    return {**merged, "missing_areas": missing, "delta": {k: ids(v) for k, v in (ctx["delta"] or {}).items()}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--previous", type=Path, help="an earlier run folder, to report new/resolved/still-open")
    ap.add_argument("--summary", help="one sentence after the verdict; defaults to the computed reasons")
    ap.add_argument("--title", help="report title, e.g. 'acme-site v1.4.1' (default: repo name + version/branch)")
    ap.add_argument("--json", action="store_true", help="print the merged result as JSON")
    args = ap.parse_args()
    try:
        result = build(args.run_dir.resolve(), args.previous and args.previous.resolve(), args.summary, args.title)
    except InputError as e:
        print(f"build_report: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        counts = {b: sum(1 for f in result["findings"] if f["bucket"] == b and f.get("status") not in DONE)
                  for b in SEVERITIES + ("known",)}
        print(f"Verdict: {result['verdict']} — {'; '.join(result['reasons'])}")
        print("Open: " + " · ".join(f"{n} {b}" for b, n in counts.items()))
        if result["missing_areas"]:
            print("Not run: " + ", ".join(result["missing_areas"]))
        print(f"Wrote {args.run_dir / 'report.md'}, plan.md, findings.json")
    return 0 if result["verdict"] == "GO" else 1


if __name__ == "__main__":
    sys.exit(main())
