# Andy's Jobsuche v12 — Live-Crawler-Dashboard

Mobile-first Jobsuche-Dashboard für Andreas Schengel (Senior PM / KI-Manager / GFZ-EE-Lead, München).
Crawlt 4× täglich automatisch über 1.000+ Quellen, filtert gegen Andys Profil, schreibt `data.js` + `data.json`.
Dashboard (`jobsuche_v12.html`) lädt `data.js` und rendert dynamisch.

## 🎯 Was ist drin

- **Crawler** (Python 3.9+, lokal oder GitHub Actions)
- **Dashboard** (eine HTML-Datei, läuft im Browser ohne Server)
- **6 aktive Quellen**: Bundesagentur · Akkodis Sitemap · arbeitnow API · 22 Personio-Subdomains · Greenhouse APIs · StepStone HTML-Suche
- **Filter** (siehe `crawler/profile.py`): hart gegen SW-Eng · SW-Tester · SAP · Junior · Bau · DB · Defense/Marine · Sales · Sachbearbeiter
- **Standort**: München + 25 km ODER ≥ 80 % Remote / Hybrid (max 1–2 Tage vor Ort akzeptabel)

## 🚀 Setup-Optionen

### Option A — Lokal auf deinem Mac (1 Befehl)

```bash
cd ~/Desktop/ordner/Bewerbungen\ 2026/crawler
chmod +x setup_local.sh
./setup_local.sh
```

Was passiert:
- Python venv + Dependencies werden installiert.
- `~/Library/LaunchAgents/com.andy.jobsuche.plist` wird angelegt → läuft **4× täglich** (06/10/14/18 Uhr).
- Erster Crawl wird sofort ausgeführt.
- Dashboard öffnen: `open ~/Desktop/ordner/Bewerbungen\ 2026/jobsuche_v12.html`

Status / Logs:
```bash
launchctl list | grep com.andy.jobsuche       # Status
tail -f ~/Desktop/ordner/Bewerbungen\ 2026/logs/crawl-$(date +%Y-%m-%d).log
```

Stoppen:
```bash
launchctl unload ~/Library/LaunchAgents/com.andy.jobsuche.plist
```

### Option B — GitHub Pages (online, von überall, iPhone-tauglich)

So kommst du von überall an dein Dashboard (auch iPhone als Bookmark):

1. **GitHub-Repo erstellen** (privat — siehe Hinweis unten):
   - Auf [github.com](https://github.com) einloggen → "New repository" → Name z. B. `andy-jobs`, **Private**, kein README/gitignore vorab.

2. **Repo hochladen** (Terminal in `~/Desktop/ordner/Bewerbungen 2026`):
   ```bash
   cd ~/Desktop/ordner/Bewerbungen\ 2026
   git init
   git add jobsuche_v12.html data.js data.json crawler/ .github/ .gitignore README.md
   git commit -m "initial: jobsuche dashboard"
   git branch -M main
   git remote add origin https://github.com/<DEIN-USERNAME>/andy-jobs.git
   git push -u origin main
   ```

3. **GitHub Pages aktivieren**:
   - Repo-Seite → Settings → Pages → Source: `Deploy from a branch` → Branch: `main`, Folder: `/ (root)` → Save.
   - Nach ~1 Min ist das Dashboard online unter:
     `https://<DEIN-USERNAME>.github.io/andy-jobs/jobsuche_v12.html`

4. **Cron in der Cloud** (`.github/workflows/crawl.yml` ist bereits eingerichtet):
   - Repo-Seite → Actions → "Jobsuche Crawl" → läuft automatisch 4× täglich (04/08/12/16 UTC = 06/10/14/18 MESZ).
   - Manuell triggern: Actions → Workflow → "Run workflow".
   - Bot committed nach jedem Lauf neue `data.js` → GitHub Pages serviert sie automatisch.

5. **iPhone**:
   - Safari öffnen, URL eingeben → Teilen-Button → "Zum Home-Bildschirm".
   - Das Manifest (`<link rel="apple-touch-icon">`) liefert ein blaues "A"-Icon.

⚠️ **Privatsphäre**: Repo unbedingt **Private** machen. Bei `Public` wäre dein Job-Such-Verlauf öffentlich. `.gitignore` schließt PDFs, Lebenslauf, Bewerbungsentwürfe schon aus — aber Git-History ist permanent, also lieber Private von Anfang an.

### Option C — Beides (empfohlen)

Lokales Setup für sofortigen Zugriff zu Hause + GitHub Pages für unterwegs. GitHub Actions sorgt dafür, dass das Online-Dashboard auch frisch ist, wenn dein Mac aus ist.

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
