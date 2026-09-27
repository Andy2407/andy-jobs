#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Jobmaschine — der 24/7-Dienst auf Andys Mac (NEU 27.09.2026).

WARUM ES DAS GIBT
    Andy (27.09.): "Mach hier ein System wie beim KI Trading System. Wenn mein Rechner an
    ist, dann wird da permanent was gemacht, gesucht, upgedatet."
    Der alte lokale Crawler (com.andy.jobsuche / -v2) ist seit Mai 2026 tot: macOS (TCC)
    verbietet Hintergrundjobs den Zugriff auf den Desktop-Ordner ("Operation not
    permitted", logs/launchd-stderr.log). Am 27.09. mit einem Test-LaunchAgent erneut
    belegt: bash, /usr/bin/python3 und die Crawler-venv duerfen den Desktop nicht lesen,
    iCloud Drive dagegen schon.

WIE ES DAS LOEST (Muster KI-Trading: eigener Ordner im Home, nicht auf dem Desktop)
    ~/Jobsuche-Maschine/
        repo/      eigener Klon von Andy2407/andy-jobs (nur Crawler-Code + Dashboard-Daten)
        .venv/     eigene Python-Umgebung fuer den Crawler
        logs/      maschine.log, crawl-*.log
        status.json, gesehen.json
    Private Bewerbungsunterlagen liegen weiter auf dem Desktop und werden hier NIE gelesen.

WAS DIE MASCHINE TUT
    Alle 15 Min (Pflegetakt):  Klon aktualisieren, Handy-Uebersicht HEUTE.md in iCloud
                               schreiben, neue Top-Treffer melden, Auftraege zaehlen.
    Alle 2 Std, 06-23 Uhr:    Vollcrawl (60+ Quellen, Andy-Fit), dann data.js/data.json +
                               maschine_status.json pushen -> Dashboard live.
                               Uebersprungen, wenn die Cloud (GitHub Actions 08/10/14/18 Uhr)
                               gerade frische Daten geliefert hat.
    Selbst-Update:            Aendert sich maschine.py im Repo, startet sie sich neu
                               (launchd KeepAlive), aber nur nach bestandenem Syntaxcheck.

WAS SIE NIEMALS TUT
    Keine Bewerbung absenden, keine Mail, nichts loeschen, keine privaten Dateien ins Repo.
    index.html / jobsuche_standalone.html werden nie gepusht (die sind in der Cloud mit
    StaticCrypt verschluesselt, lokal waeren sie Klartext).

Start/Stop: siehe maschine/install.sh. Status: ~/Jobsuche-Maschine/Jobmaschine-Status.command
"""
import fcntl
import json
import os
import py_compile
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOME = Path.home()
BASIS = HOME / "Jobsuche-Maschine"
REPO = BASIS / "repo"
PY = BASIS / ".venv/bin/python"
LOGS = BASIS / "logs"
STATUS = BASIS / "status.json"
GESEHEN = BASIS / "gesehen.json"
LOCK = BASIS / "maschine.lock"
ICLOUD = HOME / "Library/Mobile Documents/com~apple~CloudDocs/Jobsuche"
LIVE_DATA_JS = "https://andy2407.github.io/andy-jobs/data.js"

TAKT_PFLEGE_S = 15 * 60
CRAWL_ABSTAND_S = 120 * 60
CRAWL_STUNDEN = range(6, 23)          # 06:00 bis 22:59
CLOUD_FRISCH_S = 75 * 60              # Cloud-Daten juenger -> kein eigener Crawl
CRAWL_TIMEOUT_S = 55 * 60
FIT_ALARM = 75                        # ab diesem Andy-Fit gibt es eine Meldung
DATEN = ["data.js", "data.json"]

LAUFEND = True
START_DATEI_MTIME = Path(__file__).stat().st_mtime


# ------------------------------------------------------------------ Grundwerkzeuge

def jetzt():
    return datetime.now().astimezone()


def log(msg):
    zeile = f"[{jetzt():%Y-%m-%d %H:%M:%S}] {msg}"
    print(zeile, flush=True)
    try:
        LOGS.mkdir(parents=True, exist_ok=True)
        f = LOGS / "maschine.log"
        if f.exists() and f.stat().st_size > 5_000_000:
            f.replace(LOGS / "maschine.log.1")
        with f.open("a", encoding="utf-8") as h:
            h.write(zeile + "\n")
    except Exception:
        pass


def lade_json(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


def schreibe_json(p, obj):
    p = Path(p)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def git(*args, timeout=180, check=True):
    r = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()[:300]}")
    return r.stdout.strip()


def melde(titel, text):
    """macOS-Mitteilung. Kein Versand nach aussen."""
    try:
        t = text.replace('"', "'")[:180]
        subprocess.run(["osascript", "-e", f'display notification "{t}" with title "{titel}"'],
                       capture_output=True, timeout=10)
    except Exception:
        pass


def status_update(**kw):
    st = lade_json(STATUS, {})
    st.update(kw)
    st["herzschlag"] = jetzt().isoformat(timespec="seconds")
    st["pid"] = os.getpid()
    schreibe_json(STATUS, st)
    return st


# ------------------------------------------------------------------ Repo

def repo_sync():
    """Klon auf origin/main bringen. Lokal wird nie Code geaendert, reset ist daher sicher."""
    git("fetch", "--depth", "20", "origin", "main", timeout=240)
    git("reset", "--hard", "origin/main")
    return git("rev-parse", "--short", "HEAD")


def zeitpunkt(iso):
    """generated_at lesen. Ab 27.09. mit Zeitzone; alte naive Stempel stammen fast immer
    aus der Cloud (UTC) und werden so gelesen."""
    ts = datetime.fromisoformat(iso)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def daten_alter_s():
    try:
        return (jetzt() - zeitpunkt(lade_json(REPO / "data.json", {})["generated_at"])).total_seconds()
    except Exception:
        return 10 ** 9


def selbst_update_noetig():
    """Hat sich maschine.py im Repo geaendert und ist die neue Fassung syntaktisch sauber?"""
    neu = REPO / "maschine" / "maschine.py"
    if not neu.exists() or Path(__file__).resolve() != neu.resolve():
        return False
    if neu.stat().st_mtime == START_DATEI_MTIME:
        return False
    try:
        py_compile.compile(str(neu), doraise=True, cfile=str(Path(tempfile.gettempdir()) / "jm_check.pyc"))
        return True
    except Exception as e:
        log(f"Selbst-Update verworfen, neue Fassung fehlerhaft: {e}")
        return False


# ------------------------------------------------------------------ Crawl + Push

def crawl():
    LOGS.mkdir(parents=True, exist_ok=True)
    logf = LOGS / f"crawl-{jetzt():%Y-%m-%d_%H%M}.log"
    t0 = time.time()
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    # FIX 27.09. (erster Echttest): Waehrend des Crawls (bis 55 Min.) lief kein Herzschlag, der
    # Systemcheck haelt die Maschine dann fuer tot. Jetzt: Popen + Herzschlag jede Minute, und ein
    # Stoppsignal beendet auch den Crawler sauber (kein verwaister Prozess im Klon).
    with logf.open("w", encoding="utf-8") as h:
        proc = subprocess.Popen([str(PY), "crawler_v2.py"], cwd=str(REPO / "crawler"), stdout=h,
                                stderr=subprocess.STDOUT, env=env)
        ok = False
        while True:
            try:
                rc = proc.wait(timeout=60)
                ok = rc == 0
                break
            except subprocess.TimeoutExpired:
                status_update(zustand="crawl", crawl_laeuft_s=int(time.time() - t0))
                if not LAUFEND or time.time() - t0 > CRAWL_TIMEOUT_S:
                    proc.terminate()
                    try:
                        proc.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    h.write("\nABGEBROCHEN (Stoppsignal oder Timeout)\n")
                    break
    dauer = int(time.time() - t0)
    # alte Crawl-Logs begrenzen (nur die letzten 40 behalten, Rest bleibt als .gz nicht noetig)
    alte = sorted(LOGS.glob("crawl-*.log"))[:-40]
    for a in alte:
        try:
            a.unlink()
        except Exception:
            pass
    return ok, dauer, logf


def veroeffentlichen(eigene_zeit, zusatz_status):
    """Frische Daten sichern -> hart auf origin -> Daten drueber -> commit -> push (Retry)."""
    tmp = Path(tempfile.mkdtemp(prefix="jm_"))
    for f in DATEN:
        shutil.copy2(REPO / f, tmp / f)
    for versuch in range(1, 6):
        repo_sync()
        fremd = lade_json(REPO / "data.json", {}).get("generated_at", "")
        try:
            cloud_neuer = bool(fremd) and zeitpunkt(fremd) > zeitpunkt(eigene_zeit)
        except Exception:
            cloud_neuer = False
        if cloud_neuer:
            log(f"Cloud war schneller ({fremd} > {eigene_zeit}), eigene Daten verworfen")
            shutil.rmtree(tmp, ignore_errors=True)
            schreibe_status_datei(zusatz_status)
            return push("status: jobmaschine herzschlag")
        for f in DATEN:
            shutil.copy2(tmp / f, REPO / f)
        schreibe_status_datei(zusatz_status)
        if push(f"data: mac crawl {jetzt():%Y-%m-%dT%H:%M%z}"):
            shutil.rmtree(tmp, ignore_errors=True)
            return True
        log(f"Push-Kollision, Versuch {versuch}")
        time.sleep(versuch * 5)
    shutil.rmtree(tmp, ignore_errors=True)
    return False


def schreibe_status_datei(extra):
    """maschine_status.json im Repo = oeffentlicher Herzschlag fuers Dashboard (keine Privatdaten)."""
    st = lade_json(STATUS, {})
    oeffentlich = {
        "herzschlag": jetzt().isoformat(timespec="seconds"),
        "letzter_crawl": st.get("letzter_crawl"),
        "letzter_crawl_ok": st.get("letzter_crawl_ok"),
        "letzter_crawl_dauer_s": st.get("letzter_crawl_dauer_s"),
        "auftraege_offen": st.get("auftraege_offen", 0),
        "takt": "Pflege 15 Min, Crawl alle 2 Std (06-23 Uhr)",
    }
    oeffentlich.update(extra or {})
    schreibe_json(REPO / "maschine_status.json", oeffentlich)


def push(msg):
    git("add", *DATEN, "maschine_status.json")
    if not git("diff", "--cached", "--name-only"):
        return True
    git("-c", "user.name=Jobmaschine (Mac)", "-c", "user.email=bot@users.noreply.github.com",
        "commit", "-q", "-m", msg + "\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>")
    r = subprocess.run(["git", "-C", str(REPO), "push", "-q", "origin", "HEAD:main"],
                       capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        log(f"Push fehlgeschlagen: {r.stderr.strip()[:200]}")
        return False
    return True


def live_stand():
    try:
        req = urllib.request.Request(LIVE_DATA_JS + f"?t={int(time.time())}", headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=25) as r:
            kopf = r.read(400).decode("utf-8", "replace")
        m = re.search(r'"generated_at":\s*"([^"]+)"', kopf)
        return m.group(1) if m else None
    except Exception:
        return None


# ------------------------------------------------------------------ Handy: iCloud

AUFTRAG_VORLAGE = """# Aufträge für die Bewerbungs-Werkstatt

Eine Zeile pro Stelle, beginnend mit `- ` und dem Link. Die Werkstatt (Claude, 3× täglich)
baut dafür das komplette Set: Anforderungs-Matrix, Motivationsschreiben, zugeschnittener
Lebenslauf (Basis V9), Gremium-Prüfung, Portal-Texte. Erledigte Zeilen bekommen ein ✅.

Vom iPhone: im Dashboard auf „🛠 Set in der Werkstatt bauen lassen“ tippen, die Zeile
wird kopiert. Dann hier einfügen (Dateien-App › iCloud Drive › Jobsuche › AUFTRAEGE.md).

## Offen

"""


def icloud_einrichten():
    try:
        ICLOUD.mkdir(exist_ok=True)
        (ICLOUD / "Bewerbungs-Sets").mkdir(exist_ok=True)
        (ICLOUD / "Lebenslauf").mkdir(exist_ok=True)
        a = ICLOUD / "AUFTRAEGE.md"
        if not a.exists():
            a.write_text(AUFTRAG_VORLAGE, encoding="utf-8")
        return True
    except Exception as e:
        log(f"iCloud nicht beschreibbar: {e}")
        return False


def offene_auftraege():
    try:
        txt = (ICLOUD / "AUFTRAEGE.md").read_text(encoding="utf-8")
    except Exception:
        return []
    out = []
    for z in txt.splitlines():
        z = z.strip()
        if z.startswith("- ") and "http" in z and "✅" not in z and "[erledigt]" not in z.lower():
            out.append(z[2:])
    return out


def _fit(j):
    f = j.get("fit")
    return f if isinstance(f, (int, float)) else -1


def handy_uebersicht(neu):
    d = lade_json(REPO / "data.json", {})
    jobs = d.get("jobs", [])
    bs = lade_json(REPO / "crawler" / "bewerbungen_status.json", {})
    sets = [s for s in bs.get("_sets_bereit", []) if not s.get("versendet")]
    st = lade_json(STATUS, {})
    auftr = offene_auftraege()

    def firma(j):
        return (j.get("clean_company") or j.get("company") or "?").strip()

    offen = [j for j in jobs if _fit(j) >= 65
             and not (j.get("bewerbung", {}) or {}).get("status") in ("gesendet", "offen")]
    offen.sort(key=lambda j: -_fit(j))

    z = [f"# Jobmaschine · Stand {jetzt():%d.%m.%Y %H:%M}", ""]
    hb_ok = st.get("letzter_crawl_ok")
    z.append(f"**Maschine:** läuft · letzter Mac-Crawl {st.get('letzter_crawl', '–')[:16].replace('T', ' ')}"
             f"{' ✅' if hb_ok else (' ⚠️ Fehler' if hb_ok is False else '')} · Datenstand {d.get('generated_at', '–')[:16].replace('T', ' ')}")
    z.append(f"**Dashboard:** https://andy2407.github.io/andy-jobs/ (Reiter „Werkstatt“)")
    z.append("")
    z.append(f"## 📦 Sets bereit zum Absenden ({len(sets)})")
    if not sets:
        z.append("Noch keins offen. Die Werkstatt läuft 07:30, 12:30 und 17:30.")
    for s in sets:
        g = s.get("gremium", {})
        z.append(f"- **{s.get('firma')} · {s.get('stelle')}** ({s.get('datum')})  ")
        z.append(f"  Gremium MS {g.get('hr')}/{g.get('fach')}/{g.get('ceo')} · Forensik {g.get('forensik')}  ")
        z.append(f"  Unterlagen: Bewerbungs-Sets › {s.get('icloud_ordner')} · Link: {s.get('url')}")
    z.append("")
    if neu:
        z.append(f"## 🔥 Neu seit der letzten Meldung ({len(neu)})")
        for j in neu[:10]:
            ko = f" ⚠️ {'; '.join(j.get('fit_ko') or [])}" if j.get("fit_ko") else ""
            z.append(f"- **{_fit(j)}** · {j.get('title')} · {firma(j)}{ko}  \n  {j.get('url')}")
        z.append("")
    z.append(f"## 🎯 Beste offene Treffer (Andy-Fit ab 65, {len(offen)})")
    for j in offen[:15]:
        ko = f" ⚠️ {'; '.join(j.get('fit_ko') or [])}" if j.get("fit_ko") else ""
        z.append(f"- **{_fit(j)}** · {j.get('title')} · {firma(j)} · {j.get('location', '')}{ko}  \n  {j.get('url')}")
    z.append("")
    z.append(f"## 📥 Aufträge an die Werkstatt ({len(auftr)} offen)")
    for a in auftr[:10]:
        z.append(f"- {a}")
    z.append("")
    z.append("_Automatisch erzeugt von der Jobmaschine auf dem Mac. Nicht bearbeiten, wird überschrieben._")
    txt = "\n".join(z) + "\n"
    ziel = ICLOUD / "HEUTE.md"
    try:
        if not ziel.exists() or ziel.read_text(encoding="utf-8") != txt:
            ziel.write_text(txt, encoding="utf-8")
    except Exception as e:
        log(f"HEUTE.md nicht geschrieben: {e}")
    return len(auftr)


def neue_treffer():
    d = lade_json(REPO / "data.json", {})
    gesehen = set(lade_json(GESEHEN, []))
    erst = not gesehen
    neu = [j for j in d.get("jobs", []) if _fit(j) >= FIT_ALARM and j.get("url") not in gesehen
           and not (j.get("bewerbung", {}) or {}).get("status") in ("gesendet", "offen", "absage")]
    for j in d.get("jobs", []):
        if _fit(j) >= FIT_ALARM:
            gesehen.add(j.get("url"))
    schreibe_json(GESEHEN, sorted(u for u in gesehen if u))
    if erst:
        return []  # erster Lauf: nur merken, nicht 30 Meldungen auf einmal
    neu.sort(key=lambda j: -_fit(j))
    if neu:
        top = neu[0]
        melde("Jobmaschine: neue Top-Stelle",
              f"{_fit(top)} · {top.get('title', '')[:60]} · {(top.get('clean_company') or top.get('company') or '')[:30]}"
              + (f" (+{len(neu) - 1} weitere)" if len(neu) > 1 else ""))
    return neu


# ------------------------------------------------------------------ Hauptschleife

def crawl_faellig(st):
    if jetzt().hour not in CRAWL_STUNDEN:
        return False, "Nachtruhe"
    letzter = st.get("letzter_crawl_versuch")
    if letzter:
        try:
            if (jetzt() - datetime.fromisoformat(letzter)).total_seconds() < CRAWL_ABSTAND_S:
                return False, "Abstand"
        except Exception:
            pass
    if daten_alter_s() < CLOUD_FRISCH_S:
        return False, "Cloud-Daten frisch"
    return True, "faellig"


def zyklus():
    st = status_update(zustand="pflege")
    try:
        kopf = repo_sync()
        st = status_update(repo_stand=kopf, letzter_sync=jetzt().isoformat(timespec="seconds"))
    except Exception as e:
        log(f"Sync fehlgeschlagen (offline?): {e}")
        st = status_update(letzter_sync_fehler=str(e)[:200])

    faellig, grund = crawl_faellig(st)
    if faellig and LAUFEND:
        log("Vollcrawl startet")
        status_update(zustand="crawl", letzter_crawl_versuch=jetzt().isoformat(timespec="seconds"))
        ok, dauer, logf = crawl()
        if not LAUFEND:
            log("Crawl wegen Stoppsignal abgebrochen, nichts veröffentlicht")
            repo_sync()
            return
        eigene = lade_json(REPO / "data.json", {}).get("generated_at", "")
        n = len(lade_json(REPO / "data.json", {}).get("jobs", []))
        status_update(letzter_crawl=jetzt().isoformat(timespec="seconds"), letzter_crawl_ok=ok,
                      letzter_crawl_dauer_s=dauer, letzter_crawl_jobs=n, letzter_crawl_log=str(logf))
        log(f"Vollcrawl {'OK' if ok else 'FEHLER'} in {dauer}s, {n} Stellen")
        if ok and n > 50:
            gepusht = veroeffentlichen(eigene, {"quelle": "mac"})
            status_update(letzter_push_ok=gepusht, letzter_push=jetzt().isoformat(timespec="seconds"))
            log(f"Veröffentlicht: {'ja' if gepusht else 'NEIN'}")
        elif ok:
            log("Crawl lieferte unter 50 Stellen, nicht veröffentlicht (Schutz gegen Teilausfall)")
            repo_sync()
        else:
            repo_sync()
    else:
        # Herzschlag hoechstens alle 2 Std oeffentlich machen, ohne Crawl
        letzte = st.get("letzter_herzschlag_push")
        alt = True
        if letzte:
            try:
                alt = (jetzt() - datetime.fromisoformat(letzte)).total_seconds() > CRAWL_ABSTAND_S
            except Exception:
                pass
        if alt and jetzt().hour in CRAWL_STUNDEN:
            try:
                schreibe_status_datei({"quelle": "mac", "crawl_uebersprungen": grund})
                if push("status: jobmaschine herzschlag"):
                    status_update(letzter_herzschlag_push=jetzt().isoformat(timespec="seconds"))
            except Exception as e:
                log(f"Herzschlag-Push fehlgeschlagen: {e}")
            try:
                repo_sync()
            except Exception:
                pass

    icloud_einrichten()
    neu = neue_treffer()
    n_auftr = handy_uebersicht(neu)
    status_update(zustand="wartet", auftraege_offen=n_auftr, letzte_pflege=jetzt().isoformat(timespec="seconds"))


def beenden(*_):
    global LAUFEND
    LAUFEND = False
    log("Stoppsignal erhalten, beende nach diesem Schritt")


def main():
    BASIS.mkdir(exist_ok=True)
    LOGS.mkdir(exist_ok=True)
    lock = open(LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Jobmaschine läuft bereits (Lock belegt). Ende.")
        return 0
    signal.signal(signal.SIGTERM, beenden)
    signal.signal(signal.SIGINT, beenden)
    einmal = "--einmal" in sys.argv
    log(f"Jobmaschine gestartet (pid {os.getpid()}{', Einzellauf' if einmal else ''})")
    while LAUFEND:
        try:
            zyklus()
        except Exception as e:
            log(f"Zyklus-Fehler: {type(e).__name__}: {e}")
            status_update(zustand="fehler", letzter_fehler=f"{type(e).__name__}: {e}"[:300])
        if einmal:
            break
        if selbst_update_noetig():
            log("Neue Fassung von maschine.py im Repo, Neustart über launchd")
            return 0
        for _ in range(TAKT_PFLEGE_S // 5):
            if not LAUFEND:
                break
            time.sleep(5)
    log("Jobmaschine beendet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
