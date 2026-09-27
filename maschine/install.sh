#!/bin/bash
# Jobmaschine installieren / aktualisieren / anhalten (Andy, 27.09.2026)
#
#   bash maschine/install.sh               einrichten bzw. aktualisieren und starten
#   bash maschine/install.sh --ohne-browser  ohne Playwright-Chromium (spart ~300 MB)
#   bash maschine/install.sh --anhalten    beide LaunchAgents entladen (nichts wird geloescht)
#   bash maschine/install.sh --status      Kurzstatus
#
# Warum ein eigener Ordner im Home statt dem Desktop: macOS (TCC) verbietet Hintergrund-
# jobs den Desktop-Zugriff. Der alte lokale Crawler ist daran seit Mai 2026 gestorben
# (logs/launchd-stderr.log: "Operation not permitted"). Muster wie ~/KI-Trading-System.
set -euo pipefail

BASIS="$HOME/Jobsuche-Maschine"
REPO="$BASIS/repo"
LA="$HOME/Library/LaunchAgents"
UIDN="$(id -u)"
QUELLE="$(cd "$(dirname "$0")" && pwd)"
PY_BASIS="/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3"
[ -x "$PY_BASIS" ] || PY_BASIS="/usr/bin/python3"

anhalten() {
  for L in com.andy.jobmaschine com.andy.jobmaschine.check; do
    launchctl bootout "gui/$UIDN/$L" 2>/dev/null && echo "entladen: $L" || echo "war nicht geladen: $L"
  done
}

case "${1:-}" in
  --anhalten) anhalten; exit 0 ;;
  --status)
    launchctl print "gui/$UIDN/com.andy.jobmaschine" 2>/dev/null | grep -E "state|pid =" | head -3 || echo "Maschine nicht geladen"
    /usr/bin/python3 "$REPO/maschine/systemcheck.py" 2>/dev/null || true
    exit 0 ;;
esac

echo "== Jobmaschine einrichten in $BASIS"
mkdir -p "$BASIS/logs"

# 1) Eigener Klon (schlank, nur letzte 20 Commits)
if [ ! -d "$REPO/.git" ]; then
  git clone --depth 20 --single-branch --branch main https://github.com/Andy2407/andy-jobs.git "$REPO"
else
  git -C "$REPO" fetch --depth 20 origin main && git -C "$REPO" reset --hard origin/main
fi
[ -f "$REPO/maschine/maschine.py" ] || { echo "FEHLER: maschine/ fehlt im Repo (erst pushen)"; exit 1; }

# 2) Eigene Python-Umgebung fuer den Crawler
if [ ! -x "$BASIS/.venv/bin/python" ]; then
  "$PY_BASIS" -m venv "$BASIS/.venv"
fi
"$BASIS/.venv/bin/pip" install -q --upgrade pip
"$BASIS/.venv/bin/pip" install -q -r "$REPO/crawler/requirements.txt" pypdf
if [ "${1:-}" != "--ohne-browser" ]; then
  "$BASIS/.venv/bin/python" -m playwright install chromium >/dev/null 2>&1 && echo "Chromium fuer Playwright bereit" || echo "Hinweis: Chromium-Download fehlgeschlagen, Playwright-Quellen fallen aus"
fi

# 3) LaunchAgents pruefen und laden
for L in com.andy.jobmaschine com.andy.jobmaschine.check; do
  plutil -lint "$QUELLE/$L.plist" >/dev/null
  launchctl bootout "gui/$UIDN/$L" 2>/dev/null || true
  # launchd braucht nach bootout einen Moment ("Bootstrap failed: 5", 27.09.) -> warten + 1x wiederholen
  for _i in 1 2 3 4 5 6 7 8 9 10; do launchctl print "gui/$UIDN/$L" >/dev/null 2>&1 || break; sleep 1; done
  cp "$QUELLE/$L.plist" "$LA/$L.plist"
  if ! launchctl bootstrap "gui/$UIDN" "$LA/$L.plist" 2>/dev/null; then
    sleep 3; launchctl bootstrap "gui/$UIDN" "$LA/$L.plist"
  fi
  echo "geladen: $L"
done

# 4) Doppelklick-Status fuer Andy
cat > "$BASIS/Jobmaschine-Status.command" <<'EOS'
#!/bin/bash
echo "== Jobmaschine"; launchctl print "gui/$(id -u)/com.andy.jobmaschine" 2>/dev/null | grep -E "state|pid =" | head -3
echo; /usr/bin/python3 "$HOME/Jobsuche-Maschine/repo/maschine/systemcheck.py"
echo; echo "== Letzte Log-Zeilen"; tail -15 "$HOME/Jobsuche-Maschine/logs/maschine.log"
echo; read -n 1 -s -r -p "Taste druecken zum Schliessen"
EOS
chmod +x "$BASIS/Jobmaschine-Status.command"

echo "== fertig. Log: $BASIS/logs/maschine.log · Status: $BASIS/Jobmaschine-Status.command"
