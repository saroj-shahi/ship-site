#!/usr/bin/env python3
"""Install the ship-site skill for one or more coding agents.

ship-site is a standard Agent Skill (a folder with SKILL.md), so any agent that
loads skills can run it. Agents look in different folders:

  agent     user scope (default)          project scope (--project DIR)
  agents    ~/.agents/skills              .agents/skills      shared: Codex, Gemini CLI, Cursor, Copilot, OpenCode, Amp…
  codex     ~/.agents/skills              .agents/skills
  gemini    ~/.gemini/skills              .gemini/skills
  cursor    ~/.cursor/skills              .cursor/skills
  copilot   ~/.copilot/skills             .github/skills
  opencode  ~/.config/opencode/skills     .opencode/skills
  claude    ~/.claude/skills              .claude/skills      (or use the Claude Code plugin)

With no --agent, installs to the shared `agents` folder only. One copy there
serves most agents, and an agent that reads several folders would otherwise list
the skill twice.

Usage:
  python3 install.py                          # ~/.agents/skills/ship-site -> this repo
  python3 install.py --agent gemini --agent cursor
  python3 install.py --project ../my-site --agent copilot --copy
  python3 install.py --uninstall --agent all
Links by default (updates with `git pull`); --copy for a standalone copy (default on Windows).
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

SKILL = "ship-site"
SOURCE = Path(__file__).resolve().parent / "skills" / SKILL
USER_DIRS = {
    "agents": ".agents/skills",
    "codex": ".agents/skills",
    "gemini": ".gemini/skills",
    "cursor": ".cursor/skills",
    "copilot": ".copilot/skills",
    "opencode": ".config/opencode/skills",
    "claude": ".claude/skills",
}
PROJECT_DIRS = {**USER_DIRS, "copilot": ".github/skills", "opencode": ".opencode/skills"}
# Folders each agent is documented to read besides its own. Used only to warn about duplicates.
ALSO_READS = {
    "gemini": ["agents"], "cursor": ["agents"], "copilot": ["agents", "claude"],
    "opencode": ["agents", "claude"], "codex": [],
}


def target_root(agent: str, project: Path | None) -> Path:
    return (project / PROJECT_DIRS[agent]) if project else (Path.home() / USER_DIRS[agent])


def ours(path: Path) -> bool:
    return path.is_symlink() and path.resolve() == SOURCE


def remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    else:
        shutil.rmtree(path)


def install(dest: Path, copy: bool, force: bool, dry: bool) -> str:
    if ours(dest):
        return "already linked"
    if dest.exists() or dest.is_symlink():
        if not force:
            return "exists (not ours): left alone, pass --force to replace"
        if not dry:
            remove(dest)
    if dry:
        return "would " + ("copy" if copy else "link")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if copy:
        shutil.copytree(SOURCE, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        return "copied"
    dest.symlink_to(SOURCE, target_is_directory=True)
    return "linked"


def uninstall(dest: Path, force: bool, dry: bool) -> str:
    if not (dest.exists() or dest.is_symlink()):
        return "not installed"
    is_copy = dest.is_dir() and not dest.is_symlink() and (dest / "SKILL.md").is_file()
    if not ours(dest) and not (force and is_copy):
        return "not ours: left alone" + (", pass --force to remove a copy" if is_copy else "")
    if dry:
        return "would remove"
    remove(dest)
    return "removed"


def duplicate_warnings(project: Path | None) -> list[str]:
    present = {a for a in USER_DIRS if (target_root(a, project) / SKILL / "SKILL.md").is_file()}
    out = []
    for agent, extra in ALSO_READS.items():
        seen = {str(target_root(a, project)) for a in [agent, *extra] if a in present}
        if len(seen) > 1:
            out.append(f"{agent} reads {SKILL} from {len(seen)} folders ({', '.join(sorted(seen))}); "
                       f"it may list the skill twice. Keep one.")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Install the ship-site skill for coding agents.")
    ap.add_argument("--agent", action="append", choices=[*USER_DIRS, "all"],
                    help="target agent (repeatable); default: the shared .agents/skills folder")
    ap.add_argument("--project", type=Path, help="install into this repo instead of your home folder")
    ap.add_argument("--copy", action="store_true", default=os.name == "nt", help="copy instead of symlink")
    ap.add_argument("--force", action="store_true", help="replace or remove an existing folder that isn't this skill's link")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if not (SOURCE / "SKILL.md").is_file():
        print(f"skill not found at {SOURCE}", file=sys.stderr)
        return 2
    project = a.project.resolve() if a.project else None
    if project and not project.is_dir():
        ap.error(f"--project is not a directory: {a.project}")
    agents = a.agent or ["agents"]
    if "all" in agents:
        agents = list(USER_DIRS)

    done: set[Path] = set()
    for agent in agents:
        dest = target_root(agent, project) / SKILL
        if dest in done:
            continue
        done.add(dest)
        status = uninstall(dest, a.force, a.dry_run) if a.uninstall else install(dest, a.copy, a.force, a.dry_run)
        print(f"{agent:<9} {dest}  {status}")

    for w in duplicate_warnings(project):
        print(f"warning: {w}")
    if not a.uninstall and not a.dry_run:
        print("\nRestart your agent, then ask it to \"run ship-site audit\" or use /ship-site if it supports slash commands.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
