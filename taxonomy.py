import csv
import io
import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_TAXONOMY = ROOT / "data" / "taxonomy.json"
CUSTOM_TAXONOMY = Path(os.getenv("APP_DATA_DIR", str(ROOT / "data"))) / "taxonomy.json"


class TaxonomyError(ValueError):
    pass


def _validate(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("super_categories"), list):
        raise TaxonomyError("Taxonomy must contain a super_categories list.")
    cleaned: list[dict[str, Any]] = []
    for group in payload["super_categories"]:
        if not isinstance(group, dict) or not str(group.get("name", "")).strip():
            continue
        categories = []
        for category in group.get("categories", []):
            if not isinstance(category, dict) or not str(category.get("name", "")).strip():
                continue
            categories.append(
                {
                    "id": category.get("id"),
                    "name": str(category["name"]).strip(),
                    "subcategories": [
                        str(value).strip()
                        for value in category.get("subcategories", [])
                        if str(value).strip()
                    ],
                }
            )
        cleaned.append({"name": str(group["name"]).strip(), "categories": categories})
    if not cleaned:
        raise TaxonomyError("No valid categories were found in the uploaded file.")
    return {
        "version": str(payload.get("version", "Custom Viralizer Taxonomy")),
        "source": str(payload.get("source", "Uploaded taxonomy")),
        "super_categories": cleaned,
        "intelligence_lenses": payload.get("intelligence_lenses") or load_taxonomy().get("intelligence_lenses", []),
        "reputation": payload.get("reputation") or load_taxonomy().get("reputation", []),
    }


def load_taxonomy() -> dict[str, Any]:
    path = CUSTOM_TAXONOMY if CUSTOM_TAXONOMY.exists() else DEFAULT_TAXONOMY
    return json.loads(path.read_text(encoding="utf-8"))


def save_uploaded_taxonomy(filename: str, raw: bytes) -> dict[str, Any]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".json":
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TaxonomyError("The JSON taxonomy file is invalid.") from exc
    elif suffix == ".csv":
        groups: dict[str, list[dict[str, Any]]] = {}
        try:
            rows = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
            for index, row in enumerate(rows, 1):
                super_name = (row.get("super_category") or "Other").strip()
                category_name = (row.get("category") or "").strip()
                if not category_name:
                    continue
                subcategories = [
                    value.strip()
                    for value in (row.get("subcategories") or "").replace(";", "|").split("|")
                    if value.strip()
                ]
                groups.setdefault(super_name, []).append(
                    {"id": index, "name": category_name, "subcategories": subcategories}
                )
        except (UnicodeDecodeError, csv.Error) as exc:
            raise TaxonomyError("The CSV taxonomy file is invalid.") from exc
        payload = {
            "version": "Uploaded Viralizer Taxonomy",
            "source": filename,
            "super_categories": [
                {"name": name, "categories": categories} for name, categories in groups.items()
            ],
        }
    else:
        raise TaxonomyError("Upload a JSON or CSV taxonomy file.")
    normalized = _validate(payload)
    CUSTOM_TAXONOMY.parent.mkdir(parents=True, exist_ok=True)
    CUSTOM_TAXONOMY.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return normalized
