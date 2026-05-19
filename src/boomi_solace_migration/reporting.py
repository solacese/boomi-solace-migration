from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def manifest_to_markdown(manifest: dict[str, Any]) -> str:
    lines = [
        "# Boomi to Solace Migration Report",
        "",
        f"- Plan ID: `{manifest.get('plan_id', '')}`",
        f"- Started: `{manifest.get('started_at', '')}`",
        f"- Completed: `{manifest.get('completed_at', '')}`",
        "",
        "| Process | Status | Created Components | Error |",
        "|---|---|---:|---|",
    ]
    for entry in manifest.get("entries", []):
        created = entry.get("created_components", [])
        lines.append(
            "| {name} | {status} | {count} | {error} |".format(
                name=entry.get("process_name", entry.get("process_id", "")),
                status=entry.get("status", ""),
                count=len(created),
                error=str(entry.get("error", "")).replace("|", "\\|"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def write_report(manifest: dict[str, Any], output: str | Path) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".json":
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        path.write_text(manifest_to_markdown(manifest), encoding="utf-8")
