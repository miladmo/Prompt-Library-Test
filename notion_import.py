#!/usr/bin/env python3
"""
notion_import.py — Importiert lokale YAML-Prompts in deine Notion-Datenbank.
Erwartet im aktuellen Verzeichnis ein Unterverzeichnis `prompts/` mit YAML-Dateien.
Liest die Umgebungsvariablen NOTION_API_KEY und NOTION_DATABASE_ID.
Führt ein „Upsert“ durch: findet eine bestehende Page per Titel, updated sie,
oder legt sie neu an. Speichert Page-ID ↔ Slug in page_map.json.
"""
import os
import sys
import json
import yaml
from pathlib import Path
from notion_client import Client, APIResponseError

# ---- Config ----
API_KEY = os.getenv("NOTION_API_KEY")
DB_ID   = os.getenv("NOTION_DATABASE_ID")
if not API_KEY or not DB_ID:
    print("ERROR: Bitte NOTION_API_KEY und NOTION_DATABASE_ID setzen.", file=sys.stderr)
    sys.exit(1)

client = Client(auth=API_KEY)
page_map_path = Path("page_map.json")

# Lade ggf. vorhandenes Mapping
try:
    slug_to_id = json.loads(page_map_path.read_text(encoding="utf-8"))
except (FileNotFoundError, json.JSONDecodeError):
    slug_to_id = {}

def find_page_by_title(title: str) -> str | None:
    """Versucht, eine existierende Notion-Page mit genau diesem Title zu finden."""
    try:
        resp = client.databases.query(
            database_id=DB_ID,
            filter={
                "property": "Name",
                "title": {"equals": title}
            }
        )
        results = resp.get("results", [])
        if results:
            return results[0]["id"]
    except APIResponseError as e:
        print(f"ERROR beim Suchen von '{title}': {e}", file=sys.stderr)
    return None

def upsert_prompt(file_path: Path):
    """Lädt eine YAML, extrahiert Felder und erstellt/updated die Page in Notion."""
    data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    name = data.get("name", file_path.stem)
    print(f"Processing: {name}", file=sys.stderr)

    # Extrahiere System- und User-Prompt
    tpl = data.get("template","")
    try:
        system_txt = tpl.split("</system>")[0].replace("<system>\n", "")
        user_txt   = tpl.split("</user>")[-2].split("<user>\n")[-1]
    except Exception:
        system_txt = ""
        user_txt   = ""

    props = {
        "Name":           {"title":       [{"text": {"content": name}}]},
        "System Prompt":  {"rich_text":  [{"text": {"content": system_txt}}]},
        "User Template":  {"rich_text":  [{"text": {"content": user_txt}}]},
        "Kategorie":      {"select":     {"name": data["name"].split("/")[1]}},
        "Tags":           {"multi_select": [{"name": t} for t in data.get("tags",[])]},
        "Version":        {"rich_text":  [{"text": {"content": data.get("metadata",{}).get("version","")}}]},
    }

    # Upsert-Logic
    page_id = slug_to_id.get(name) or find_page_by_title(name)
    if page_id:
        try:
            client.pages.update(page_id=page_id, properties=props)
            print(f"Updated: {name}", file=sys.stderr)
        except APIResponseError as e:
            print(f"ERROR updating '{name}': {e}", file=sys.stderr)
            sys.exit(2)
    else:
        try:
            res = client.pages.create(parent={"database_id": DB_ID}, properties=props)
            slug_to_id[name] = res["id"]
            print(f"Created: {name}", file=sys.stderr)
        except APIResponseError as e:
            print(f"ERROR creating '{name}': {e}", file=sys.stderr)
            sys.exit(2)

def main():
    for file in sorted(Path("prompts").rglob("*.yaml")):
        upsert_prompt(file)
    # Speichere aktualisiertes Mapping
    page_map_path.write_text(json.dumps(slug_to_id, indent=2), encoding="utf-8")
    print("Import complete.", file=sys.stderr)

if __name__ == "__main__":
    main()
