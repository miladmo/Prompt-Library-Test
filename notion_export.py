#!/usr/bin/env python3
"""notion_export.py — Export prompts from a Notion database into YAML files
compatible with Fraunhofer FIT’s prompt‑library schema.

Features:
  - Support for .env files via python-dotenv
  - Explicit YAML document start (`---`)
  - Structured logging instead of print
  - CLI interface with argparse for DB-ID and output directory
  - Exit codes: 1=config, 2=API, 3=IO
  - Idempotent: only updates changed files and deletes archived ones

Environment variables (required unless overridden via CLI):
  NOTION_API_KEY       – Secret integration token with read access to the DB
  NOTION_DATABASE_ID   – ID of the Notion database that stores the prompts
Optional:
  OUTPUT_DIR           – Target directory for generated YAML (default: ./prompts)
  PAGE_SIZE            – Items per Notion query (1–100, default: 100)

Usage:
  python notion_export.py \
    --db-id "$NOTION_DATABASE_ID" \
    --output "prompts/"  # optional

Example with .env:
  // create .env file with NOTION_API_KEY and NOTION_DATABASE_ID
  python notion_export.py
"""
from __future__ import annotations
import os
import re
import sys
import json
import logging
import argparse
from pathlib import Path
from typing import Any, Dict, List
from datetime import datetime

from dotenv import load_dotenv  # type: ignore
from notion_client import Client, APIResponseError  # type: ignore
from ruamel.yaml import YAML  # type: ignore

# Load .env if present
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

def slugify(text: str) -> str:
    s = text.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def notion_rich_text_to_str(rich: List[Dict[str, Any]]) -> str:
    return "".join(part.get("plain_text", "") for part in rich)


def extract_properties(page: Dict[str, Any]) -> Dict[str, Any]:
    props = page.get("properties", {})
    def get(key: str, default=None):
        val = props.get(key, {})
        t = val.get("type")
        return val.get(t, default)

    name = notion_rich_text_to_str(get("Name", [])) or "untitled"
    system_prompt = notion_rich_text_to_str(get("System Prompt", []))
    user_template = notion_rich_text_to_str(get("User Template", []))
    category = get("Kategorie", {}).get("name", "uncategorised")
    tags = [t.get("name") for t in get("Tags", [])] if props.get("Tags") else []
    version = get("Version", "0.1.0")
    qdims = [d.get("name") for d in get("Qualitäts-Dims", [])] if props.get("Qualitäts-Dims") else []
    license_ = get("Lizenz", {}).get("name", "internal")
    authors = [p.get("person", {}).get("name", "") for p in get("Autor", {}).get("people", [])]

    return {
        "name": f"fit/{slugify(category)}/{slugify(name)}@{version}",
        "description": (user_template.split("\n", 1)[0][:100] if user_template else name),
        "tags": tags,
        "template": f"""<system>\n{system_prompt}\n</system>\n<user>\n{user_template}\n</user>""",
        "quality_dimensions": qdims,
        "metadata": {
            "authors": authors or ["Unknown"],
            "version": version,
            "license": license_,
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "notion_page_id": page.get("id"),
        },
    }


def write_yaml(prompt: Dict[str, Any], output_dir: Path) -> Path:
    _, filename_with_version = prompt["name"].split("/", 2)
    filename, _ = filename_with_version.split("@", 1)
    category = prompt["name"].split("/")[1]
    target_dir = output_dir / category
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{filename}.yaml"
    with path.open("w", encoding="utf-8") as fh:
        yaml.dump(prompt, fh)
    logger.info(f"✓ {path.relative_to(Path.cwd())}")
    return path


def delete_removed(existing: List[Path], retained: List[Path]) -> None:
    for path in existing:
        if path not in retained:
            try:
                path.unlink()
                logger.info(f"✗ removed {path.relative_to(Path.cwd())}")
            except OSError as e:
                logger.error(f"ERROR removing {path}: {e}")
                sys.exit(3)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Export prompts from Notion to YAML files")
    p.add_argument("--db-id", help="Notion Database ID", default=os.getenv("NOTION_DATABASE_ID"))
    p.add_argument("--output", help="Output directory", default=os.getenv("OUTPUT_DIR", "prompts"))
    p.add_argument("--page-size", type=int, help="Notion page size (1–100)", default=int(os.getenv("PAGE_SIZE", "100")))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    api_key = os.getenv("NOTION_API_KEY")
    if not api_key or not args.db_id:
        logger.error("ERROR: NOTION_API_KEY and NOTION_DATABASE_ID must be set.")
        sys.exit(1)

    client = Client(auth=api_key)
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.explicit_start = True

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    retained: List[Path] = []
    try:
        has_more = True
        cursor = None
        while has_more:
            resp = client.databases.query(
                database_id=args.db_id,
                page_size=args.page_size,
                start_cursor=cursor,
            ) if cursor else client.databases.query(
                database_id=args.db_id,
                page_size=args.page_size,
            )
            for page in resp.get("results", []):
                if page.get("archived"): continue
                prompt = extract_properties(page)
                path = write_yaml(prompt, output_dir)
                retained.append(path.resolve())
            has_more = resp.get("has_more", False)
            cursor = resp.get("next_cursor")
    except APIResponseError as exc:
        logger.error(f"Notion API error: {exc}")
        sys.exit(2)

    existing = [p.resolve() for p in Path(args.output).rglob("*.yaml")]
    delete_removed(existing, retained)
    logger.info("Export complete.")

if __name__ == "__main__":
    main()
