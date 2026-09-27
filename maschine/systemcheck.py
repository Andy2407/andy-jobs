#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Jobmaschine-Systemcheck — der Waechter ueber dem Waechter (NEU 27.09.2026).

Muster: ~/KI-Trading-System/systemcheck.py. Prueft von AUSSEN, ob die Jobmaschine wirklich
arbeitet, statt ihr zu glauben. Laeuft per LaunchAgent alle 15 Min, beendet sich danach.

    python3 systemcheck.py              pruefen und berichten
    python3 systemcheck.py --heilen     zusaetzlich: Maschine neu einhaengen/anstossen
    python3 systemcheck.py --still      nur eine Zeile (fuer launchd)

Er startet nichts, was schon betreut wird: kein zweiter KeepAlive-Job auf dieselbe Datei
(genau das war beim KI-Trading monatelang die versteckte Ausfallursache).
"""
import json
import os
import subprocess
import sys
import urllib.request
import re
import time
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
BASIS = HOME / "Jobsuche-Maschine"
STATUS = BASIS / "status.json"
ERGEBNIS = BASIS / "systemcheck_status.json"
ICLOUD = HOME / "Library/Mobile Documents/com~apple~CloudDocs/Jobsuche"
LABEL = "com.andy.jobmaschine"
PLIST = HOME / "Library/LaunchAgents" / f"{LABEL}.plist"
LIVE = "https://andy2407.github.io/andy-jobs/data.js"
GRUEN, GELB, ROT = "GRÜN", "GELB", "ROT"


def alter_min(iso):
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(iso)
        if t.tzinfo is None:          # alte naive Stempel stammen aus der Cloud = UTC
            t = t.replace(tzinfo=timezone.utc)
        return (datetime.now().astimezone() - t).total_seconds() / 60
    except Exception:
        return None


def agent_laeuft():
    r = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"], capture_output=True, text=True)
    if r.returncode != 0:
        return False, None
    m = re.search(r"\bpid = (\d+)", r.stdout)
    return True, (int(m.group(1)) if m else None)


def live_generated_at():
    try:
        req = urllib.request.Request(LIVE + f"?t={int(time.time())}", headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=25) as r:
            kopf = r.read(400).decode("utf-8", "replace")
        m = re.search(r'"generated_at":\s*"([^"]+)"', kopf)
        return m.group(1) if m else None
    except Exception:
        return None


def pruefen():
    befunde = []
    st = {}
    try:
        st = json.loads(STATUS.read_text(encoding="utf-8"))
    except Exception:
        # Erststart: Maschine schreibt ihren ersten Herzschlag gerade. Nicht "heilen"!
        # (27.09.: der Check hat die Maschine beim Erststart sonst sofort abgeschossen)
        befunde.append((GELB, "Noch kein Status, Maschine startet gerade"))
        return GELB, befunde, {"pid": agent_laeuft()[1], "herzschlag_min": None}
    geladen, pid = agent_laeuft()
    if not geladen:
        befunde.append((ROT, "LaunchAgent com.andy.jobmaschine nicht geladen"))
    elif not pid:
        befunde.append((GELB, "LaunchAgent geladen, aber kein laufender Prozess"))
    hb = alter_min(st.get("herzschlag"))
    if hb is not None and hb > 40:
        befunde.append((ROT, f"Kein Herzschlag seit {int(hb) if hb else '?'} Min."))
    stunde = datetime.now().hour
    if 8 <= stunde <= 22:
        lc = alter_min(st.get("letzter_crawl"))
        if st.get("letzter_crawl_ok") is False:
            befunde.append((GELB, "Letzter Mac-Crawl mit Fehler, Log: " + str(st.get("letzter_crawl_log", ""))))
        live = live_generated_at()
        la = alter_min(live)
        if la is None:
            befunde.append((GELB, "Live-Dashboard nicht lesbar (offline?)"))
        elif la > 6 * 60:
            befunde.append((ROT, f"Live-Dashboard seit {int(la / 60)} Std. ohne neue Daten (Cloud UND Mac still)"))
        if lc is not None and lc > 5 * 60 and (la is None or la > 3 * 60):
            befunde.append((GELB, f"Mac hat seit {int(lc / 60)} Std. nicht gecrawlt"))
        if st.get("letzter_push_ok") is False:
            befunde.append((GELB, "Letzter Push zu GitHub fehlgeschlagen"))
    if not os.access(ICLOUD, os.W_OK):
        befunde.append((GELB, "iCloud-Ordner Jobsuche nicht beschreibbar"))
    try:
        frei = os.statvfs(str(HOME))
        gb = frei.f_bavail * frei.f_frsize / 1e9
        if gb < 3:
            befunde.append((GELB, f"Nur noch {gb:.1f} GB frei"))
    except Exception:
        pass
    stufe = ROT if any(b[0] == ROT for b in befunde) else (GELB if befunde else GRUEN)
    return stufe, befunde, {"pid": pid, "herzschlag_min": hb}


def heilen(stufe, befunde):
    geladen, pid = agent_laeuft()
    uid = os.getuid()
    if not geladen and PLIST.exists():
        subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(PLIST)], capture_output=True)
        return "LaunchAgent neu eingehängt"
    # Nur anstossen, wenn der Herzschlag wirklich steht (> 40 Min.). Die Maschine schlaegt auch
    # waehrend eines Crawls jede Minute, ein langer Crawl ist also kein Grund.
    if any("Kein Herzschlag" in b[1] for b in befunde):
        subprocess.run(["launchctl", "kickstart", "-k", f"gui/{uid}/{LABEL}"], capture_output=True)
        return "Maschine neu angestoßen"
    return None


def main():
    stufe, befunde, info = pruefen()
    aktion = heilen(stufe, befunde) if "--heilen" in sys.argv and stufe != GRUEN else None
    alt = {}
    try:
        alt = json.loads(ERGEBNIS.read_text(encoding="utf-8"))
    except Exception:
        pass
    erg = {"zeit": datetime.now().astimezone().isoformat(timespec="seconds"), "stufe": stufe,
           "befunde": [f"{s}: {t}" for s, t in befunde], "aktion": aktion, **info}
    BASIS.mkdir(exist_ok=True)
    ERGEBNIS.write_text(json.dumps(erg, ensure_ascii=False, indent=2), encoding="utf-8")
    # Mitteilung nur beim Wechsel nach ROT, nicht alle 15 Minuten
    if stufe == ROT and alt.get("stufe") != ROT:
        t = "; ".join(t for s, t in befunde if s == ROT)[:170].replace('"', "'")
        subprocess.run(["osascript", "-e", f'display notification "{t}" with title "Jobmaschine: Störung"'],
                       capture_output=True)
    try:
        zeilen = [f"# Jobmaschine Systemcheck · {datetime.now():%d.%m.%Y %H:%M}", "", f"**Stufe: {stufe}**", ""]
        zeilen += [f"- {s}: {t}" for s, t in befunde] or ["- alles in Ordnung"]
        if aktion:
            zeilen += ["", f"Selbstheilung: {aktion}"]
        (ICLOUD / "SYSTEMCHECK.md").write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    except Exception:
        pass
    if "--still" in sys.argv:
        print(f"{erg['zeit']} {stufe} {len(befunde)} Befund(e){' · ' + aktion if aktion else ''}")
    else:
        print(json.dumps(erg, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
