#!/usr/bin/env python3
"""
notion_import.py — Importiert lokale YAML-Prompts in deine Notion-Datenbank.
Erwartet im aktuellen Verzeichnis ein Unterverzeichnis `prompts/` mit YAML-Dateien.
Liest die Umgebungsvariablen NOTION_API_KEY und NOTION_DATABASE_ID.
"""
import os, sys, yaml
from pathlib import Path
from notion_client import Client, APIResponseError

API_KEY = os.getenv("NOTION_API_KEY")
DB_ID   = os.getenv("NOTION_DATABASE_ID")
if not API_KEY or not DB_ID:
    print("ERROR: NOTION_API_KEY und NOTION_DATABASE_ID müssen gesetzt sein", file=sys.stderr)
    sys.exit(1)

client = Client(auth=API_KEY)

def upsert_prompt(file_path: Path):
    data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    props = {
        "Name":        {"title":       [{"text": {"content": data["name"]}}]},
        "System Prompt": {
            "rich_text": [{"text": {"content": data["template"].split("</system>")[0].replace("<system>\n", "")}}]
        },
        "User Template": {
            "rich_text": [{"text": {"content": data["template"].split("</user>")[-2].split("<user>\n")[-1]}}]
        },
        "Kategorie":   {"select":      {"name": data["name"].split("/")[1]}},
        "Tags":        {"multi_select": [{"name": t} for t in data.get("tags", [])]},
        "Version":     {"rich_text":  [{"text": {"content": data["metadata"]["version"]}}]},
    }
    # Versuche, eine Page zu finden (Optional: per stored mapping)
    # Hier einfach neu anlegen:
    try:
        client.pages.create(parent={"database_id": DB_ID}, properties=props)
        print(f"Created {file_path.name}")
    except APIResponseError as e:
        print(f"Notion API error on {file_path.name}: {e}", file=sys.stderr)
        sys.exit(2)

def main():
    for file in Path("prompts").rglob("*.yaml"):
        upsert_prompt(file)
    print("Import complete.")

if __name__ == "__main__":
    main()
