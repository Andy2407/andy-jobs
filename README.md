# Andy's Jobsuche v12 — Live-Crawler-Dashboard

Mobile-first Jobsuche-Dashboard für Andreas Schengel (Senior PM / KI-Manager / GFZ-EE-Lead, München).
Crawlt 4× täglich automatisch über 6 Quellen, filtert gegen Andys Profil, schreibt `data.js` + `data.json`.
Dashboard (`jobsuche_v12.html`) lädt `data.js` und rendert dynamisch.

## 🌍 Live-Zugriff

**Online (von überall, iPhone/iPad ohne Mac):**
- 🔗 https://andy2407.github.io/andy-jobs/

**Offline auf iPhone (über iCloud Drive):**
- iPhone: Dateien-App → iCloud Drive → Jobsuche → `jobsuche_standalone.html` → "In Safari öffnen" → Teilen → "Zum Home-Bildschirm"
- Mac muss nur EINMAL pro Tag laufen, damit iCloud die neue Version syncht.

**Lokal auf Mac:**
- `~/Desktop/ordner/Bewerbungen 2026/jobsuche_v12.html` direkt im Browser öffnen.

## 🎯 Was ist drin

- **Crawler** (Python 3.9+, lokal oder GitHub Actions)
- **Dashboard** (eine HTML-Datei, läuft im Browser ohne Server)
- **6 aktive Quellen**: Bundesagentur · Akkodis Sitemap · arbeitnow API · 22 Personio-Subdomains · Greenhouse APIs · StepStone HTML-Suche
- **Filter** (siehe `crawler/profile.py`): hart gegen SW-Eng · SW-Tester · SAP · Junior · Bau · DB · Defense/Marine · Sales · Sachbearbeiter
- **Standort**: München + 25 km ODER ≥ 80 % Remote / Hybrid (max 1–2 Tage vor Ort akzeptabel)

## 🚀 Setup-Optionen

### Option A — Lokal auf deinem Mac (bereits eingerichtet)

```bash
# Erstmaliges Setup (nur falls auf neuem Mac)
cd ~/Desktop/ordner/Bewerbungen\ 2026/crawler
chmod +x setup_local.sh crawl_and_push.sh
./setup_local.sh
```

Was läuft:
- launchd-Job `com.andy.jobsuche` ist installiert → ruft `crawler/crawl_and_push.sh` auf:
  1. Crawl mit Python-venv (~80-100s)
  2. Schreibt: `data.js`, `data.json`, `index.html`, `jobsuche_standalone.html`, `~/Library/Mobile Documents/.../Jobsuche/jobsuche_standalone.html` (iCloud)
  3. Wenn Git-Repo da: `git add` + `git commit` + `git push` → GitHub Pages aktualisiert sich.
- Zeitplan: **4× täglich** 06/10/14/18 Uhr lokal.
- Dashboard lokal: `open ~/Desktop/ordner/Bewerbungen\ 2026/jobsuche_v12.html`

Status / Logs:
```bash
launchctl list | grep com.andy.jobsuche       # Status
tail -f ~/Desktop/ordner/Bewerbungen\ 2026/logs/crawl-$(date +%Y-%m-%d).log
```

Stoppen:
```bash
launchctl unload ~/Library/LaunchAgents/com.andy.jobsuche.plist
```

### Option B — GitHub Pages (bereits eingerichtet)

Ist live unter https://andy2407.github.io/andy-jobs/.

- Repo: https://github.com/Andy2407/andy-jobs (Public, weil GitHub Pages auf Free-Plan nur Public-Repos unterstützt; keine sensitiven Daten committed: keine PDFs, kein Lebenslauf)
- Aktualisierungs-Workflow: läuft entweder über lokales `launchd` (Mac an) ODER über `.github/workflows/crawl.yml` (Cloud).
- Push-Befehle nach lokalem Crawl (manuell):
  ```bash
  cd ~/Desktop/ordner/Bewerbungen\ 2026
  git add data.js data.json index.html jobsuche_v12.html jobsuche_standalone.html
  git commit -m "data update"
  git push
  ```

### iPhone-Setup (1× einrichten)

1. Safari öffnen → https://andy2407.github.io/andy-jobs/
2. Teilen-Button → "Zum Home-Bildschirm" → blaues "A"-Icon erscheint
3. Tippen → Dashboard öffnet vollbildig wie eine App (Notizen + Filter + Tabs werden in localStorage gespeichert).

Für reine Offline-Nutzung (auch ohne Internet): Dateien-App → iCloud Drive → Jobsuche → `jobsuche_standalone.html` → "In Safari öffnen" → Teilen → "Zum Home-Bildschirm". Diese Version hat alle Daten inline, läuft ohne Netz.

## 📁 Struktur

```
Bewerbungen 2026/
├── jobsuche_v12.html          # Dashboard (lädt data.js)
├── data.js                    # Wird vom Crawler geschrieben (window.JOBSUCHE_DATA)
├── data.json                  # Identische Daten als JSON (für externe Tools)
├── README.md                  # diese Datei
├── .gitignore                 # schützt Bewerbungs-Materialien
├── .github/
│   └── workflows/
│       └── crawl.yml          # GitHub Actions Cron
├── crawler/
│   ├── crawler.py             # Hauptskript
│   ├── profile.py             # Andy's Profil + Filterregeln (HIER tunen!)
│   ├── requirements.txt
│   ├── setup_local.sh         # Einmal-Setup lokal (venv + launchd)
│   └── com.andy.jobsuche.plist.template
├── logs/                      # crawl-YYYY-MM-DD.log
└── (deine privaten Bewerbungs-Materialien — NICHT auf GitHub)
```

## 🛠️ Filter anpassen

Alles in `crawler/profile.py`:

- **`TITLE_BLOCK`** — Titel-Substrings, die zu sofortigem Verwerfen führen.
- **`TITLE_BOOST`** — Keyword → Punkte. Andy-relevante Begriffe geben mehr.
- **`LOCATION_BOOST`** — Standort-Bonus (München, Remote, Hybrid).
- **`COMPANY_BLOCK`** — Firmen-Blacklist (Everlast, Aconext).
- **`location_passes()`** — Standort-Logik (München-Nähe ODER Remote/Hybrid-Hinweis).
- **`MIN_SCORE_TO_INCLUDE`** — Schwelle (aktuell 22).

Nach Anpassung einfach Crawler erneut starten:
```bash
cd ~/Desktop/ordner/Bewerbungen\ 2026/crawler
.venv/bin/python crawler.py
```

## 📊 Aktueller Stand

Letzter erfolgreicher Crawl: ~440 verifizierte Treffer in ~110 Sekunden.
Quellen-Verteilung typisch: Akkodis ~40 · Bundesagentur ~60 · Greenhouse ~100 · arbeitnow ~50 · StepStone ~150 · Personio ~5.

## 🚫 Was nicht funktioniert (Stand Mai 2026)

- **Indeed**: Cloudflare-Captcha (403). Bräuchte Playwright + Headless-Browser.
- **Xing**: JavaScript-rendered, keine HTML-Job-Cards. Bräuchte Playwright.
- **LinkedIn**: Login-Pflicht, sehr aggressive Bot-Detection.
- **Brainlab / BMW Group / CARIAD / Cognizant Mobility / Munich Re Karriereportal**: JavaScript-only, kein einfaches HTML-Listing.

→ Phase 2: Playwright-basierter Sub-Crawler dafür. Aktuell: Initiativbewerbungs-Tab im Dashboard rotiert über diese Firmen.

## 🛡️ Profil & harte Ausschlüsse

Andy IST: Senior PM · KI-Manager · SE-Teamleiter · GFZ-EE-Package-Lead · Konzeptkonstrukteur · Modul-/Baugruppenverantwortlicher · Studio Ingenieur · Agiler PM/PO.

Andy ist NICHT: SW/AI/ML/DevOps Engineer · Backend/Frontend/Full-Stack Dev · Embedded SW/Firmware · Software-Tester / QA · SAP-Berater · Head-of-AI / VP / Chief / C-Level · Junior / Werkstudent / Praktikant · Bauingenieur / TGA / Versorgungstechnik.

Branchen-Blacklist: Bau · DB / Schienenverkehr · Rüstung / Marine / Defense.

Firmen-Blacklist: Everlast / Evolast · Aconext. IAV nur für Initiativbewerbungen ausgeschlossen.

## 🔄 Updates am Profil

Wenn ein Job-Titel falsch klassifiziert wird:
1. `crawler/profile.py` öffnen.
2. Keyword in `TITLE_BLOCK` (zum Ausschließen) oder `TITLE_BOOST` (zum Promoten) ergänzen.
3. Crawler neu starten — Effekt sofort sichtbar.

## 📝 Lizenz

Privates Projekt für Andreas Schengel. Code-Architektur orientiert sich am Übergabe-Dokument vom 30.04.2026.
