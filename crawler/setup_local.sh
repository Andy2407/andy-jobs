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
mkdir -p "$HOME/Library/LaunchAgents"
sed "s|__BASE__|$BASE|g" "$PLIST_SRC" > "$PLIST_DST"
echo "📄 launchd-Plist erstellt: $PLIST_DST"

# 3) Plist laden
launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load -w "$PLIST_DST"
echo "🚀 launchd-Job geladen — läuft 4× täglich (06/10/14/18 Uhr)"

# 4) Erster Crawl manuell
mkdir -p "$BASE/logs"
echo
echo "🔁 Erster manueller Crawl…"
"$BASE/crawler/.venv/bin/python" "$BASE/crawler/crawler.py"

echo
echo "✅ Setup fertig!"
echo
echo "   Dashboard öffnen: $BASE/jobsuche_v12.html"
echo "   Manuell crawlen:  $BASE/crawler/.venv/bin/python $BASE/crawler/crawler.py"
echo "   Job-Status:       launchctl list | grep com.andy.jobsuche"
echo "   Job entfernen:    launchctl unload $PLIST_DST"
echo "   Logs:             $BASE/logs/"
