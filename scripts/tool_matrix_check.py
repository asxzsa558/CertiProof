#!/usr/bin/env python3
"""Lightweight consistency check for the security tool entry matrix."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL_CATALOG = ROOT / "frontend/src/components/toolCatalog.js"
CHAT_API = ROOT / "backend/app/api/chat.py"
ORCHESTRATOR = ROOT / "backend/app/orchestrator/orchestrator.py"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_frontend_tools(source: str) -> list[tuple[str, str]]:
    return re.findall(r"command:\s*'([^']+)'.{0,180}?capability:\s*'([^']+)'", source, re.S)


def parse_backend_display_names(source: str) -> set[str]:
    block = source.split("CAPABILITY_DISPLAY_NAMES = {", 1)[1].split("\n}", 1)[0]
    return set(re.findall(r'"([^"]+)":\s*"', block))


def parse_scan_capabilities(source: str) -> set[str]:
    block = source.split("SCAN_CAPABILITIES = {", 1)[1].split("}", 1)[0]
    return set(re.findall(r'"([^"]+)"', block))


def main() -> int:
    frontend_tools = parse_frontend_tools(read(TOOL_CATALOG))
    backend_names = parse_backend_display_names(read(CHAT_API))
    scan_capabilities = parse_scan_capabilities(read(ORCHESTRATOR))
    allowed_non_scan = {"ping_host", "ping_asset"}

    if not frontend_tools:
        print("FAIL: no frontend tools parsed")
        return 1

    failures = []
    seen_commands = set()
    for command, capability in frontend_tools:
        if command in seen_commands:
            failures.append(f"duplicate command: {command}")
        seen_commands.add(command)
        if capability not in backend_names:
            failures.append(f"{command}: capability {capability} missing in backend CAPABILITY_DISPLAY_NAMES")
        if capability not in scan_capabilities and capability not in allowed_non_scan:
            failures.append(f"{command}: capability {capability} missing in orchestrator SCAN_CAPABILITIES")

    print(f"Checked {len(frontend_tools)} frontend tool entries")
    print(f"Backend display names: {len(backend_names)}")
    print(f"Orchestrator scan capabilities: {len(scan_capabilities)}")

    if failures:
        print("\nFAILURES:")
        for item in failures:
            print(f"- {item}")
        return 1

    print("tool matrix check ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
