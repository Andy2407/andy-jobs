#!/usr/bin/env bash
# Wrapper: Crawl ausführen, dann data.js / data.json / index.html / jobsuche_standalone.html
# committen + pushen (für lokales launchd, damit GitHub Pages frisch bleibt).
set -e
BASE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$BASE"

# 1) Crawler
"$BASE/crawler/.venv/bin/python" "$BASE/crawler/crawler.py"

# 2) Wenn Git-Repo existiert: committen + pushen
if [ -d "$BASE/.git" ]; then
  git -C "$BASE" add data.js data.json index.html jobsuche_v12.html jobsuche_standalone.html 2>/dev/null || true
  if git -C "$BASE" diff --cached --quiet; then
    echo "Keine Änderungen für Push."
  else
    git -C "$BASE" commit -m "data update $(date -u +%Y-%m-%dT%H:%MZ)" || true
    git -C "$BASE" push 2>&1 | tail -3 || echo "Push-Fehler (offline?)"
  fi
fi
