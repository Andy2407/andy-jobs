#!/usr/bin/env bash
# Setup: lokaler launchd-Cron für Andy's Jobsuche-Crawler
# Läuft 4× täglich (06/10/14/18 Uhr) auf deinem Mac.
set -e

BASE="$(cd "$(dirname "$0")/.." && pwd)"
PLIST_SRC="$BASE/crawler/com.andy.jobsuche.plist.template"
PLIST_DST="$HOME/Library/LaunchAgents/com.andy.jobsuche.plist"

echo "📦 Setup Andy's Jobsuche-Crawler (lokal)"
echo "   Base: $BASE"
echo

# 1) Python venv + deps
if [ ! -d "$BASE/crawler/.venv" ]; then
  echo "🔨 Erstelle Python venv…"
  python3 -m venv "$BASE/crawler/.venv"
fi
echo "📚 Installiere Dependencies…"
"$BASE/crawler/.venv/bin/pip" install --quiet --upgrade pip
"$BASE/crawler/.venv/bin/pip" install --quiet -r "$BASE/crawler/requirements.txt"
echo "   ✅ requests + beautifulsoup4 + lxml installiert"

# 2) Plist erzeugen mit absolutem Pfad
# HINWEIS: Der automatische Crawl läuft 4x täglich (08/10/14/18 Uhr CEST) zuverlässig
# in der GitHub Actions Cloud (.github/workflows/crawl.yml).
# Lokales launchd auf macOS Desktop wird durch macOS TCC Sandbox blockiert (Fehler 78).
# Für manuelle lokale Läufe direkt crawler_v2.py verwenden:

mkdir -p "$BASE/logs"
echo
echo "🔁 Starte manuellen Crawl mit crawler_v2.py…"
"$BASE/crawler/.venv/bin/python" "$BASE/crawler/crawler_v2.py"

echo
echo "✅ Lokale Umgebung bereit!"
echo
echo "   Dashboard lokal:  $BASE/jobsuche_standalone.html"
echo "   Live-Dashboard:   https://andy2407.github.io/andy-jobs/"
echo "   Manuell crawlen:  $BASE/crawler/.venv/bin/python $BASE/crawler/crawler_v2.py"
echo "   Logs:             $BASE/logs/"

