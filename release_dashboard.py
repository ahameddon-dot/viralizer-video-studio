import json
import os
from pathlib import Path
from typing import Any

from release_actions import action_status


ROOT = Path(__file__).resolve().parent
CATALOG = ROOT / "data" / "release_catalog.json"


class ReleaseDashboardError(ValueError):
    pass


def load_catalog() -> dict[str, Any]:
    try:
        payload = json.loads(CATALOG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseDashboardError("The release catalog could not be loaded.") from exc
    releases = payload.get("releases")
    if not isinstance(releases, list) or not releases:
        raise ReleaseDashboardError("The release catalog has no versions.")
    return payload


def environment_snapshot() -> dict[str, Any]:
    catalog = load_catalog()
    releases = catalog["releases"]
    return {
        "application": "Viralizer Video Studio",
        "environment": os.getenv("APP_ENVIRONMENT", "development"),
        "branch": os.getenv("RENDER_GIT_BRANCH", os.getenv("APP_GIT_BRANCH", "develop")),
        "commit": os.getenv("RENDER_GIT_COMMIT", releases[-1].get("commit", "unknown")),
        "service": os.getenv("RENDER_SERVICE_NAME", "local-development"),
        "current_version": os.getenv("APP_VERSION", releases[-1].get("version", "unversioned")),
        "production_version": catalog.get("production_version", "unknown"),
        "beta_version": catalog.get("beta_version", "not deployed"),
        "release_controls": {"mode": "live" if action_status()["configured"] else "locked", **action_status()},
    }


def release_index(catalog: dict[str, Any], version: str) -> int:
    for index, release in enumerate(catalog["releases"]):
        if release.get("version") == version:
            return index
    raise ReleaseDashboardError(f"Unknown version: {version}")


def compare_versions(from_version: str, to_version: str) -> dict[str, Any]:
    catalog = load_catalog()
    start = release_index(catalog, from_version)
    end = release_index(catalog, to_version)
    direction = "upgrade" if end >= start else "rollback"
    low, high = sorted((start, end))
    selected = catalog["releases"][low + 1 : high + 1]
    changes = [change for release in selected for change in release.get("changes", [])]
    if direction == "rollback":
        changes.reverse()
    return {
        "from": catalog["releases"][start],
        "to": catalog["releases"][end],
        "direction": direction,
        "change_count": len(changes),
        "changes": changes,
        "files": sorted({file for change in changes for file in change.get("files", [])}),
        "endpoints": sorted({endpoint for change in changes for endpoint in change.get("endpoints", [])}),
        "environment_variables": sorted({value for change in changes for value in change.get("environment_variables", [])}),
        "data_changes": [change.get("data_impact") for change in changes if change.get("data_impact")],
    }


def rollback_preview(target_version: str) -> dict[str, Any]:
    catalog = load_catalog()
    current = catalog.get("production_version") or catalog["releases"][-1]["version"]
    comparison = compare_versions(current, target_version)
    removed = comparison["changes"] if comparison["direction"] == "rollback" else []
    return {
        "current_version": current,
        "target_version": target_version,
        "can_execute": False,
        "mode": "preview_only",
        "changes_removed": removed,
        "files_affected": comparison["files"],
        "endpoints_affected": comparison["endpoints"],
        "environment_variables_affected": comparison["environment_variables"],
        "data_review": comparison["data_changes"],
        "preserved": [
            "Render environment secrets and API keys",
            "Previously generated images and videos",
            "Uploaded taxonomy unless a selected release explicitly changes its format",
            "Release history and audit evidence",
        ],
        "warning": "This is an impact preview only. It does not change production.",
    }
