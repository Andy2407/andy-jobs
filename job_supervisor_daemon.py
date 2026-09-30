#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Master-Supervisor Daemon für Andy's Jobsuche & Bewerbungs-Maschine
Architektur-Standard: Übertragen aus dem KI-Trading-System (master.py / worker.py)
Stand: 27.09.2026 (GOAT MODE)

Aufgaben:
  1. 24/7 Autonomie: Überwacht kontinuierlich den Systemzustand, solange der Mac läuft.
  2. Mobile Auftrags-Queue: Reagiert in Echtzeit auf Aufträge vom iPhone (AUFTRAG_QUEUE.json in iCloud).
  3. Masterclass Pipeline: Baut vollautomatisch CV V9 + MS, führt das 5-Perspektiven-Gremium aus und kompiliert PDFs.
  4. Dual-Sync: Spiegelt fertige Mappen und Standalone-Dashboards direkt in iCloud Drive.
  5. Watchdog & Heartbeat: Protokolliert Status in supervisor_status.json.
"""

import sys, os, time, json, signal, subprocess, argparse
from datetime import datetime
from pathlib import Path

ROOT = Path("/Users/andreasschengel/Desktop/ordner/Bewerbungen 2026")
JOBSUCHE_DIR = ROOT / "Jobsuche"
JOBSUCHE_QUEUE = JOBSUCHE_DIR / "AUFTRAG_QUEUE.json"
LOCAL_QUEUE = ROOT / "AUFTRAG_QUEUE.json"
STATUS_FILE = ROOT / "supervisor_status.json"
LOCK_FILE = ROOT / "supervisor.lock"
LOG_FILE = ROOT / "logs" / "supervisor.log"

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except:
        pass

def write_status(state, details=None):
    data = {
        "status": state,
        "pid": os.getpid(),
        "timestamp": datetime.now().isoformat(),
        "details": details or {}
    }
    try:
        STATUS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        if JOBSUCHE_DIR.exists():
            (JOBSUCHE_DIR / "supervisor_status.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log(f"Status-Schreibfehler: {e}")

def get_queue():
    """Liest die Queue vorrangig lokal."""
    for qpath in [LOCAL_QUEUE, JOBSUCHE_QUEUE]:
        if qpath.exists():
            try:
                data = json.loads(qpath.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
            except:
                pass
    return []

def save_queue(queue_data):
    """Speichert die Queue lokal und im Jobsuche-Ordner."""
    txt = json.dumps(queue_data, ensure_ascii=False, indent=2)
    try:
        LOCAL_QUEUE.write_text(txt, encoding="utf-8")
    except:
        pass
    try:
        if JOBSUCHE_DIR.exists():
            JOBSUCHE_QUEUE.write_text(txt, encoding="utf-8")
    except:
        pass

def process_queue_item(item):
    """Verarbeitet einen einzelnen Bewerbungsauftrag."""
    slug = item.get("company_slug", item.get("company_name", "Unbekannt").replace(" ", "_"))
    comp = item.get("company_name", "Unbekannt")
    title = item.get("job_title", "Stelle")
    
    log(f"🎯 Verarbeite Auftrag aus Queue: {comp} — {title}")
    
    # Konfigurationsdatei für build_masterclass_bewerbung.py vorbereiten
    cfg_path = ROOT / f"_temp_auftrag_{slug}.json"
    cfg_path.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
    
    cmd = [sys.executable, str(ROOT / "_helper/build_masterclass_bewerbung.py"), str(cfg_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    
    if cfg_path.exists():
        cfg_path.unlink()
        
    if proc.returncode == 0:
        log(f"✅ Masterclass Mappe für {comp} erfolgreich erstellt!")
        item["status"] = "COMPLETED"
        item["completed_at"] = datetime.now().isoformat()
        return True
    else:
        log(f"❌ Fehler bei Erstellung für {comp}:\n{proc.stdout}\n{proc.stderr}")
        item["status"] = "FAILED"
        item["error"] = proc.stderr[:300]
        return False

def sync_dashboard_to_jobsuche():
    """Spiegelt das Standalone-HTML-Dashboard in den Jobsuche-Ordner."""
    src = ROOT / "jobsuche_standalone.html"
    if src.exists() and JOBSUCHE_DIR.exists():
        try:
            dest = JOBSUCHE_DIR / "jobsuche_standalone.html"
            import shutil
            shutil.copy2(src, dest)
            log("📱 Standalone-Dashboard in Jobsuche synchronisiert.")
        except Exception as e:
            log(f"Jobsuche Dashboard Sync Fehler: {e}")

def run_loop():
    """Hauptüberwachungsschleife des Daemons."""
    log("🦅 Job-Supervisor Daemon GESTARTET (Modus: KI-Trading-System Vorbild)")
    LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
    
    last_crawl = 0
    crawl_interval = 7200  # alle 2 Stunden lokaler Crawl-Check
    
    try:
        while True:
            now = time.time()
            write_status("RUNNING", {"last_heartbeat": datetime.now().isoformat()})
            
            # 1. Mobile Queue prüfen
            queue = get_queue()
            pending = [it for it in queue if it.get("status") == "PENDING"]
            if pending:
                log(f"📥 {len(pending)} offene Aufträge in der Mobile-Queue gefunden.")
                for item in pending:
                    item["status"] = "PROCESSING"
                    save_queue(queue)
                    process_queue_item(item)
                    save_queue(queue)
                    
            # 2. Downloads überwachen & neue Motivationsschreiben einsortieren
            try:
                sortierer = ROOT / "_helper/auto_bewerbungs_sortierer.py"
                if sortierer.exists():
                    subprocess.run([sys.executable, str(sortierer)], capture_output=True, timeout=30)
            except Exception as e:
                log(f"Sortierer-Fehler: {e}")

            # 3. Regelmäßiger Dashboard Sync
            sync_dashboard_to_jobsuche()
            
            # 3. Zyklischer Crawler (falls gewünscht)
            if now - last_crawl > crawl_interval:
                log("🔄 Starte zyklischen Crawler-Durchlauf...")
                try:
                    crawl_script = ROOT / "crawler/crawler.py"
                    if crawl_script.exists():
                        subprocess.run([sys.executable, str(crawl_script)], capture_output=True, timeout=600)
                        last_crawl = now
                        log("✅ Zyklischer Crawler abgeschlossen.")
                except Exception as e:
                    log(f"Crawler-Fehler: {e}")
                    
            time.sleep(30)
    except KeyboardInterrupt:
        log("Supervisor durch Benutzer beendet.")
    finally:
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()
        write_status("STOPPED")

def main():
    parser = argparse.ArgumentParser(description="Andy's Job-Supervisor Daemon")
    parser.add_argument("action", choices=["start", "stop", "status", "run-once", "queue-add"], help="Aktion")
    parser.add_argument("--json", help="JSON-String oder Dateipfad für queue-add")
    args = parser.parse_args()
    
    if args.action == "status":
        if STATUS_FILE.exists():
            print(STATUS_FILE.read_text(encoding="utf-8"))
        else:
            print(json.dumps({"status": "STOPPED", "message": "Kein Statusfile vorhanden"}))
            
    elif args.action == "run-once":
        log("Führe Einzel-Durchlauf durch...")
        queue = get_queue()
        pending = [it for it in queue if it.get("status") == "PENDING"]
        for it in pending:
            it["status"] = "PROCESSING"
            save_queue(queue)
            process_queue_item(it)
            save_queue(queue)
        sync_dashboard_to_jobsuche()
        log("Einzel-Durchlauf abgeschlossen.")
        
    elif args.action == "start":
        if LOCK_FILE.exists():
            pid = LOCK_FILE.read_text().strip()
            print(f"Supervisor läuft bereits (PID {pid}).")
            sys.exit(0)
        run_loop()
        
    elif args.action == "stop":
        if LOCK_FILE.exists():
            pid = int(LOCK_FILE.read_text().strip())
            try:
                os.kill(pid, signal.SIGTERM)
                print(f"Supervisor (PID {pid}) beendet.")
            except ProcessLookupError:
                print(f"Prozess {pid} existiert nicht mehr.")
            if LOCK_FILE.exists():
                LOCK_FILE.unlink()
            write_status("STOPPED")
        else:
            print("Kein aktiver Supervisor gefunden.")
            
    elif args.action == "queue-add":
        if not args.json:
            print("Fehler: --json erforderlich für queue-add.")
            sys.exit(1)
        data = None
        if Path(args.json).exists():
            data = json.loads(Path(args.json).read_text(encoding="utf-8"))
        else:
            data = json.loads(args.json)
        data["status"] = "PENDING"
        data["queued_at"] = datetime.now().isoformat()
        q = get_queue()
        q.append(data)
        save_queue(q)
        print(f"✅ Auftrag für '{data.get('company_name')}' zur Queue hinzugefügt!")

if __name__ == "__main__":
    main()
