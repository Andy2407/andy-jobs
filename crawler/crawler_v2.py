#!/usr/bin/env python3
"""Andy's Jobsuche-Crawler v4 — +RemoteOK +Remotive +WeWorkRemotely +Indeed (Playwright optional).

Quellen (19+1 optional):
- Akkodis Sitemap, arbeitnow API, Personio (42), Greenhouse (46),
  Lever, Ashby, Workable, Recruitee, SmartRecruiters (Bosch & Co.),
  Bundesagentur JSON-API, StepStone, sz-jobs.de, kimeta, jobvector,
  LinkedIn anonymous,
  + RemoteOK API, + Remotive API, + WeWorkRemotely RSS,
  + Indeed via Playwright (nur wenn playwright installiert).

Output: data.json + data.js + index.html + standalone.html (+ iCloud).
"""

import json
import re
import sys
import time
import logging
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, urljoin, unquote

import requests
from bs4 import BeautifulSoup

from profile import score_job, categorize, clean_title, MIN_SCORE_TO_INCLUDE, OTHER_MIN_SCORE, USER_BLOCKED_URLS

BASE = Path(__file__).resolve().parent.parent
DATA_PATH = BASE / "data.json"
LOG_DIR = BASE / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOG_PATH = LOG_DIR / f"crawl-{datetime.now().strftime('%Y-%m-%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("crawl")

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


# ============================================================
# AKKODIS via Sitemap
# ============================================================
def crawl_akkodis(session, limit_per_run: int = 100) -> list:
    log.info("[Akkodis] Sitemap…")
    try:
        r = session.get("https://karriere.akkodis.com/sitemap.xml", timeout=15)
        r.raise_for_status()
    except Exception as e:
        log.warning(f"[Akkodis] {e}")
        return []
    job_urls = re.findall(r"<loc>(https?://karriere\.akkodis\.com/offer/[^<]+)</loc>", r.text)
    job_urls = list(dict.fromkeys(job_urls))
    log.info(f"[Akkodis] {len(job_urls)} URLs")
    pri = ["muenchen", "bayern", "automotive", "fahrzeug", "ee", "elektrik",
           "projektleiter", "projektmanager", "modul", "baugruppen", "konzept",
           "ki", "ai", "smart", "gesamtfahrzeug", "senior"]
    job_urls.sort(key=lambda u: -sum(1 for k in pri if k in u.lower()))
    jobs = []
    CITIES = ["München", "Munich", "Ingolstadt", "Garching", "Ismaning", "Unterschleißheim",
              "Starnberg", "Stuttgart", "Sindelfingen", "Böblingen", "Berlin", "Hamburg",
              "Frankfurt", "Köln", "Düsseldorf", "Leipzig", "Hannover", "Nürnberg",
              "Augsburg", "Regensburg", "Ulm", "Dresden", "Bremen", "Wolfsburg",
              "Heilbronn", "Karlsruhe", "Mannheim", "Neutraubling", "Chemnitz"]
    for u in job_urls[:limit_per_run]:
        try:
            jr = session.get(u, timeout=12)
            if jr.status_code != 200:
                continue
            soup = BeautifulSoup(jr.text, "lxml")
            title_el = soup.find("h1") or soup.find("h2")
            title = title_el.get_text(strip=True) if title_el else ""
            body = soup.get_text(" ", strip=True)[:3000]
            found = [c for c in CITIES if c in body]
            loc = " · ".join(found[:3]) if found else ""
            for kw in ["hybrides Arbeiten", "Remote & Präsenz", "Homeoffice", "remote"]:
                if kw.lower() in body.lower():
                    loc = (loc + " · Hybrid Remote").strip(" ·")
                    break
            if not loc and "muenchen" in u.lower():
                loc = "München"
            jobs.append({"source": "akkodis", "url": u, "title": title,
                         "company": "Akkodis Group", "location": loc,
                         "description": body[:600], "raw_text": body})
        except Exception as e:
            log.debug(f"[Akkodis] {u}: {e}")
        time.sleep(0.12)
    log.info(f"[Akkodis] {len(jobs)} Detail-Jobs")
    return jobs


# ============================================================
# arbeitnow API
# ============================================================
def crawl_arbeitnow(session, max_pages: int = 15) -> list:
    log.info("[arbeitnow] API…")
    jobs = []
    for page in range(1, max_pages + 1):
        try:
            r = session.get("https://www.arbeitnow.com/api/job-board-api",
                            params={"page": page}, timeout=15)
            if r.status_code != 200:
                break
            data = r.json().get("data", [])
            if not data:
                break
            for j in data:
                jobs.append({
                    "source": "arbeitnow", "url": j.get("url"),
                    "title": j.get("title", ""),
                    "company": j.get("company_name", ""),
                    "location": j.get("location", ""),
                    "description": (j.get("description") or "")[:600],
                    "raw_text": (j.get("description") or "")[:3000],
                    "remote": bool(j.get("remote")),
                })
        except Exception as e:
            log.warning(f"[arbeitnow] p{page}: {e}")
            break
        time.sleep(0.25)
    log.info(f"[arbeitnow] {len(jobs)} Jobs")
    return jobs


# ============================================================
# Personio (42 Subs)
# ============================================================
PERSONIO_COMPANIES = [
    ("appliedai", "appliedAI Initiative", None),
    ("filics", "Filics", None),
    ("attempto", "attempto GmbH", "https://www.attempto.eu/de/karriere/job/{id}?language=de"),
    ("amiconsult", "amiconsult GmbH", "https://amiconsult.de/job/{id}?language=de"),
    ("perelyn", "Perelyn", None), ("vaeridion", "VÆRIDION", None),
    ("isarvalley", "Isar Aerospace", None),
    ("elexon-gmbh", "elexon", None), ("eigenherd-gmbh", "Eigenherd", None),
    ("vulcan-energie-ressourcen-gmbh", "Vulcan", None),
    ("lifte-h2", "LIFTE H2", None),
    ("the-mobility-house", "Mobility House", None),
    ("ineratec", "INERATEC", None), ("sunfire", "Sunfire", None),
    ("mitocare", "MITOcare", None), ("planfox", "PLANFOX", None),
    ("medbelle", "Medbelle", None), ("eternohealth", "Eterno Health", None),
    ("celonis", "Celonis", None), ("personio", "Personio", None),
    ("amplimind", "amplimind", None), ("encoviva", "encoviva", None),
    ("liveeo-gmbh", "LiveEO", None), ("stackfuel-gmbh", "StackFuel", None),
    ("planworx", "PLANWORX", None), ("alasco", "Alasco", None),
    ("clue", "Clue", None),
    ("jungvonmatt", "Jung von Matt", None), ("peepz", "peepz", None),
    ("fyrfeed", "fyrfeed", None), ("kreuzwerker", "Kreuzwerker", None),
    ("netconomy", "NETCONOMY", None),
    ("thost-projektmanagement", "THOST", None),
    ("bachert-partner-1", "bachert&partner", None),
    ("p3-group", "P3 group", None),
    ("agile-robots-se", "Agile Robots", None),  # FIX 2026-06-11: alter Slug "agilerobots" tot (307); echtes Board 87 Jobs — Radar-Fund (800-Mio-$-Runde 02.06., Bloomberg)
    ("kinexon", "Kinexon", None), ("konux-gmbh", "KONUX", None),
    ("luminovo", "Luminovo", None), ("logivations", "Logivations", None),
    ("kaeser-kompressoren", "KAESER", None),
    ("mep-werke", "MEP Werke", None), ("trumpf", "TRUMPF", None),
    # NEU 2026-06-01 (Robotik/Mechatronik München, ATS-verifiziert: 100% München-Treffer)
    ("franka-robotics", "Franka Robotics", None),
    ("magazino", "Magazino", None),
    # NEU 2026-06-03 (Handoff Andy, Stellen verifiziert 02.06.2026 — München-Treffer):
    # ACHTUNG: pmgholding (PMMG Group) BEWUSST NICHT aufgenommen — der Titel "Senior Consultant"
    # trifft den Consultant-Hardblock in profile.py; Andy-Entscheidung 03.06.: "PMMG weglassen".
    # OmniVision (HRworks) + FEV (career.fev.com) erreicht kein Crawler -> laufen als manual_jobs
    # in user_overrides.json (siehe load_manual_jobs).
    ("avenyr", "AVENYR GmbH", None),
    ("vdwbayern", "VdW Bayern", None),
    ("start2", "Start2 Group", None),
]


def crawl_personio(session) -> list:
    jobs, ok = [], 0
    for sub, name, alt_url in PERSONIO_COMPANIES:
        try:
            r = session.get(f"https://{sub}.jobs.personio.de/?language=de", timeout=10)
            if r.status_code != 200:
                continue
            ok += 1
            soup = BeautifulSoup(r.text, "lxml")
            for a in soup.select('a[href*="/job/"]'):
                href = a.get("href", "")
                m = re.search(r"/job/(\d+)", href)
                if not m:
                    continue
                jid = m.group(1)
                if href.startswith("/"):
                    detail = f"https://{sub}.jobs.personio.de{href}"
                elif href.startswith("http"):
                    detail = href
                else:
                    detail = f"https://{sub}.jobs.personio.de/{href}"
                if alt_url:
                    detail = alt_url.format(id=jid)
                title_el = a.find(["h2", "h3"]) or a
                title = title_el.get_text(strip=True)
                jobs.append({"source": f"personio:{sub}", "url": detail,
                             "title": title, "company": name,
                             "location": "", "description": "", "raw_text": title})
        except Exception as e:
            log.debug(f"[personio:{sub}] {e}")
        time.sleep(0.18)
    log.info(f"[Personio] {len(jobs)} ({ok}/{len(PERSONIO_COMPANIES)})")
    return jobs


# ============================================================
# Greenhouse
# ============================================================
GREENHOUSE_COMPANIES = [
    # NEU 2026-06-01 (Andy): nur DACH / Mobility / Hardware mit potenziellen PM-/Produkt-Rollen.
    # US-Pure-AI/SWE/Defense entfernt (openai, anthropic, stripe, scaleai, elevenlabs, perplexityai,
    # huggingface, stabilityai, neon, supabase, vercel, linear, notion, mongodb, databricks, cohere,
    # anduril, joby, wayve, mithril, thinkingmachines, pitch, contentful, lightyear, idagio, blinkist,
    # remotecom, klarna, taxfix) — die liefern nur Software-Engineer-/ML-Stellen ohne DE-Bezug = Rauschen.
    "celonis", "flix", "formlabs", "applied-intuition", "tiermobility", "tier",
    "n26", "traderepublic", "sennder", "gostudent",
    "raisin", "mambu", "awin", "infarm", "choco", "omio",
    "scalable", "scalablecapital", "getyourguide",
    "zalando", "hellofresh", "deliveryhero", "sumup", "bitpanda", "grover",
    # NEU 2026-06-01 (München-Bezug, ATS-verifiziert)
    "roboyo",
]


def crawl_greenhouse(session) -> list:
    jobs, ok = [], 0
    for co in GREENHOUSE_COMPANIES:
        try:
            r = session.get(f"https://boards-api.greenhouse.io/v1/boards/{co}/jobs", timeout=12)
            if r.status_code != 200:
                continue
            ok += 1
            for j in r.json().get("jobs", []):
                jobs.append({
                    "source": f"greenhouse:{co}",
                    "url": j.get("absolute_url"),
                    "title": j.get("title", ""), "company": co.capitalize(),
                    "location": (j.get("location") or {}).get("name", ""),
                    "description": "", "raw_text": j.get("title", ""),
                })
        except Exception as e:
            log.debug(f"[gh:{co}] {e}")
        time.sleep(0.08)
    log.info(f"[Greenhouse] {len(jobs)} ({ok}/{len(GREENHOUSE_COMPANIES)})")
    return jobs


# ============================================================
# Lever / Ashby / Workable / Recruitee / SmartRecruiters
# ============================================================
# NEU 2026-06-01 (Andy): US-Pure-AI/SWE/Defense raus (intersystems, spacex, palantir, freenome,
# anthropic, openai). Munich Electrification behalten (München, E-Mobility-Hardware, lieferte im
# God-Mode-Lauf den NPI-Treffer).
LEVER_COMPANIES = ["munichelectrification", "vehicle", "finn"]


def crawl_lever(session) -> list:
    jobs, ok = [], 0
    for co in LEVER_COMPANIES:
        try:
            r = session.get(f"https://api.lever.co/v0/postings/{co}?mode=json", timeout=12)
            if r.status_code != 200:
                continue
            ok += 1
            for j in r.json():
                cat = (j.get("categories") or {})
                jobs.append({
                    "source": f"lever:{co}", "url": j.get("hostedUrl"),
                    "title": j.get("text", ""), "company": co.capitalize(),
                    "location": cat.get("location", ""),
                    "description": "", "raw_text": j.get("text", ""),
                })
        except Exception as e:
            log.debug(f"[lever:{co}] {e}")
        time.sleep(0.08)
    log.info(f"[Lever] {len(jobs)} ({ok}/{len(LEVER_COMPANIES)})")
    return jobs


# UPDATE 2026-06-10 (Andy, hart): RobCo (Robotik-Startup München, rob.co) fehlte komplett —
# Andy musste die Firma selbst zufällig finden. RobCo nutzt Ashby (jobs.ashbyhq.com/robco,
# verifiziert via Embed-iframe auf rob.co/de/karriere). Ashby-API liefert sauberes JSON.
# NEU 2026-06-01 (Andy): Ashby-Liste war ausschließlich US-Pure-AI/SWE (anthropic, openai,
# elevenlabs, anysphere, perplexity, mistral, stabilityai, weaviate) — kein DE-Produktentwicklungs-
# Bezug, reines Rauschen. Geleert; kann später mit DACH-Ashby-Boards gefüllt werden.
ASHBY_COMPANIES = ["robco", "orbem"]


def crawl_ashby(session) -> list:
    jobs, ok = [], 0
    for co in ASHBY_COMPANIES:
        try:
            r = session.get(f"https://api.ashbyhq.com/posting-api/job-board/{co}", timeout=12)
            if r.status_code != 200:
                continue
            ok += 1
            for j in r.json().get("jobs", []):
                jobs.append({
                    "source": f"ashby:{co}",
                    "url": j.get("jobUrl") or j.get("applyUrl"),
                    "title": j.get("title", ""), "company": co.capitalize(),
                    "location": j.get("locationName", "") or j.get("location", ""),
                    "description": "", "raw_text": j.get("title", ""),
                })
        except Exception as e:
            log.debug(f"[ashby:{co}] {e}")
        time.sleep(0.08)
    log.info(f"[Ashby] {len(jobs)} ({ok}/{len(ASHBY_COMPANIES)})")
    return jobs


WORKABLE_COMPANIES = ["fluxysmunich", "tractive", "konux"]


def crawl_workable(session) -> list:
    jobs, ok = [], 0
    for co in WORKABLE_COMPANIES:
        try:
            r = session.get(f"https://apply.workable.com/api/v3/accounts/{co}/jobs",
                            params={"limit": 100}, timeout=12)
            if r.status_code != 200:
                continue
            ok += 1
            for j in r.json().get("results", []):
                loc = j.get("location") or {}
                jobs.append({
                    "source": f"workable:{co}",
                    "url": j.get("url") or j.get("shortlink"),
                    "title": j.get("title", ""), "company": co.capitalize(),
                    "location": loc.get("city", "") or loc.get("country", ""),
                    "description": "", "raw_text": j.get("title", ""),
                })
        except Exception as e:
            log.debug(f"[workable:{co}] {e}")
        time.sleep(0.08)
    log.info(f"[Workable] {len(jobs)} ({ok}/{len(WORKABLE_COMPANIES)})")
    return jobs


RECRUITEE_COMPANIES = ["sennder", "gridx"]


def crawl_recruitee(session) -> list:
    jobs, ok = [], 0
    for co in RECRUITEE_COMPANIES:
        try:
            r = session.get(f"https://{co}.recruitee.com/api/offers/", timeout=12)
            if r.status_code != 200:
                continue
            ok += 1
            for j in r.json().get("offers", []):
                jobs.append({
                    "source": f"recruitee:{co}",
                    "url": j.get("careers_url") or j.get("url"),
                    "title": j.get("title", ""), "company": co.capitalize(),
                    "location": j.get("location", "") or j.get("city", ""),
                    "description": "", "raw_text": j.get("title", ""),
                })
        except Exception as e:
            log.debug(f"[recruitee:{co}] {e}")
        time.sleep(0.08)
    log.info(f"[Recruitee] {len(jobs)} ({ok}/{len(RECRUITEE_COMPANIES)})")
    return jobs


SMARTRECRUITERS_COMPANIES = [
    "BoschGroup", "Bosch-HomeComfort", "Brainlab", "Vattenfall",
    "MiltenyiBiotec", "SIXT",
    "REWEInternationalDienstleistungsgesellschaftmbH",
    "DiscoverDeloitte",
    "Gerresheimer",  # NEU 2026-06-01 (MedTech-Verpackung/Pharma-Glas, SmartRecruiters)
]


def crawl_smartrecruiters(session) -> list:
    jobs, ok = [], 0
    for co in SMARTRECRUITERS_COMPANIES:
        try:
            offset = 0
            while True:
                r = session.get(
                    f"https://api.smartrecruiters.com/v1/companies/{co}/postings",
                    params={"limit": 100, "offset": offset, "country": "de"},
                    timeout=12,
                )
                if r.status_code != 200:
                    break
                data = r.json()
                content = data.get("content", [])
                if not content:
                    break
                if offset == 0:
                    ok += 1
                for j in content:
                    loc = j.get("location") or {}
                    city = loc.get("city", "") or ""
                    country = loc.get("country", "") or ""
                    jobs.append({
                        "source": f"smartrecruiters:{co}",
                        "url": (j.get("ref") or "")
                            .replace("api.smartrecruiters.com/v1", "jobs.smartrecruiters.com")
                            or f"https://jobs.smartrecruiters.com/{co}/{j.get('id','')}",
                        "title": j.get("name", ""), "company": co,
                        "location": f"{city} {country}".strip(),
                        "description": "", "raw_text": j.get("name", ""),
                    })
                if len(content) < 100:
                    break
                offset += 100
                time.sleep(0.15)
        except Exception as e:
            log.debug(f"[sr:{co}] {e}")
        time.sleep(0.15)
    log.info(f"[SmartRecruiters] {len(jobs)} ({ok}/{len(SMARTRECRUITERS_COMPANIES)})")
    return jobs


# ============================================================
# Bundesagentur — offizielle JSON-API mit X-API-Key
# ============================================================
BA_API_QUERIES = [
    {"was": "KI Manager"}, {"was": "AI Project Manager"}, {"was": "AI Manager"},
    {"was": "Senior Projektmanager", "wo": "München", "umkreis": "25"},
    {"was": "Senior Projektmanager"},
    {"was": "Senior Project Manager", "wo": "München", "umkreis": "25"},
    {"was": "Senior Project Manager"},
    {"was": "Programmleiter", "wo": "München", "umkreis": "25"},
    {"was": "Programmmanager", "wo": "München", "umkreis": "25"},
    {"was": "Projektleiter Automotive", "wo": "München", "umkreis": "25"},
    {"was": "Projektleiter Fahrzeug", "wo": "München", "umkreis": "25"},
    {"was": "EE-Projektleiter", "wo": "München", "umkreis": "25"},
    {"was": "Modulleiter", "wo": "München", "umkreis": "25"},
    {"was": "Baugruppenverantwortlicher", "wo": "München", "umkreis": "25"},
    {"was": "Projektmanager Pharma", "wo": "München", "umkreis": "25"},
    {"was": "Projektmanager MedTech", "wo": "München", "umkreis": "25"},
    {"was": "Konzeptkonstrukteur", "wo": "München", "umkreis": "25"},
    {"was": "SE-Teamleiter", "wo": "München", "umkreis": "25"},
    {"was": "PMO", "wo": "München", "umkreis": "25"},
    # NEU 2026-06-01 (Andy-Fokus: Produktentwicklung / Konzept / Prototyp / Teilprojektleitung)
    {"was": "Projektleiter Produktentwicklung", "wo": "München", "umkreis": "25"},
    {"was": "Teilprojektleiter", "wo": "München", "umkreis": "25"},
    {"was": "Projektleiter Entwicklung", "wo": "München", "umkreis": "25"},
    {"was": "Entwicklungsprojektleiter", "wo": "München", "umkreis": "25"},
    {"was": "Technischer Projektleiter", "wo": "München", "umkreis": "25"},
    {"was": "Projektleiter Vorentwicklung", "wo": "München", "umkreis": "25"},
    {"was": "Projektingenieur Entwicklung", "wo": "München", "umkreis": "25"},
    {"was": "Konstruktionsleiter", "wo": "München", "umkreis": "25"},
    {"was": "Projektleiter Produktentwicklung"},
    {"was": "Teilprojektleiter Entwicklung"},
    {"was": "Senior Consultant", "wo": "München", "umkreis": "25"},
    {"was": "Agile Projektmanager", "wo": "München", "umkreis": "25"},
    {"was": "Scrum Master", "wo": "München", "umkreis": "25"},
    {"was": "Product Owner", "wo": "München", "umkreis": "25"},
    # Engineering-Dienstleister Firmen (NEU v5)
    {"was": "Bertrandt"},
    {"was": "FERCHAU"},
    {"was": "EDAG"},
    {"was": "ARRK Engineering"},
    {"was": "IAV"},
    {"was": "Akkodis"},
    {"was": "Capgemini Engineering"},
    {"was": "Brunel"},
    {"was": "Expleo"},
    {"was": "MHP"},
]


def crawl_bundesagentur(session) -> list:
    jobs = []
    hdrs = {**HEADERS, "X-API-Key": "jobboerse-jobsuche"}
    base = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs"
    seen = set()
    for q in BA_API_QUERIES:
        params = {**q, "size": "100"}
        try:
            r = session.get(base, params=params, headers=hdrs, timeout=15)
            if r.status_code != 200:
                continue
            for st in r.json().get("stellenangebote", []):
                ref = st.get("refnr")
                if not ref or ref in seen:
                    continue
                seen.add(ref)
                title = st.get("titel", "") or st.get("beruf", "")
                jobs.append({
                    "source": "bundesagentur",
                    "url": f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{ref}",
                    "title": title[:200],
                    "company": st.get("arbeitgeber", "") or "",
                    "location": (st.get("arbeitsort") or {}).get("ort", "") or q.get("wo", ""),
                    "description": "", "raw_text": title,
                })
        except Exception as e:
            log.warning(f"[BA-API] {q}: {e}")
        time.sleep(0.3)
    log.info(f"[Bundesagentur] {len(jobs)} ({len(BA_API_QUERIES)} Suchen)")
    return jobs


# ============================================================
# StepStone
# ============================================================
STEPSTONE_QUERIES = [
    # Generische Rollen
    ("senior-projektmanager", "muenchen"), ("ai-project-manager", "muenchen"),
    ("ki-manager", "muenchen"), ("ki-manager", None),
    ("projektmanager-digital", "muenchen"), ("project-manager-pharma", "muenchen"),
    ("project-manager-biotech", "muenchen"),
    ("projektmanager-medizintechnik", "muenchen"),
    ("projektmanager-automotive", "muenchen"),
    ("projektleiter-automotive", "muenchen"),
    ("projektleiter-automotive", None), ("modulleiter", "muenchen"),
    ("baugruppenverantwortlicher", "muenchen"), ("programmleiter", "muenchen"),
    ("programmmanager", "muenchen"), ("ai-project-manager", None),
    ("senior-projektmanager", None), ("senior-projektleiter", "muenchen"),
    ("konzeptkonstrukteur", "muenchen"), ("se-teamleiter", "muenchen"),
    ("pmo", "muenchen"),
    # NEU 2026-06-01 (Andy-Fokus Produktentwicklung/Teilprojektleitung/Konzept/Prototyp)
    ("projektleiter-produktentwicklung", "muenchen"),
    ("teilprojektleiter", "muenchen"),
    ("projektleiter-entwicklung", "muenchen"),
    ("technischer-projektleiter", "muenchen"),
    ("entwicklungsprojektleiter", "muenchen"),
    ("projektleiter-vorentwicklung", "muenchen"),
    ("konstruktionsleiter", "muenchen"),
    ("projektleiter-produktentwicklung", None),
    ("teilprojektleiter", None),
    # Engineering-Dienstleister firmen-spezifisch (NEU v5)
    ("bertrandt", "muenchen"), ("bertrandt", None),
    ("alten", "muenchen"), ("alten", None),
    ("ferchau", "muenchen"), ("ferchau", None),
    ("edag", "muenchen"), ("edag", None),
    ("mhp", "muenchen"),
    ("akkodis", "muenchen"),
    ("arrk", "muenchen"),
    ("capgemini-engineering", "muenchen"),
    ("p3-group", "muenchen"),
    ("magna", "muenchen"),
    ("cognizant-mobility", "muenchen"),
    ("brunel", "muenchen"),
    ("expleo", "muenchen"),
    ("yer", "muenchen"),
    ("apriori", "muenchen"),
]


def crawl_stepstone(session) -> list:
    jobs = []
    for q, loc in STEPSTONE_QUERIES:
        url = (f"https://www.stepstone.de/jobs/{q}/in-{loc}" if loc
               else f"https://www.stepstone.de/jobs/{q}")
        try:
            r = session.get(url, timeout=15)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "lxml")
            seen = set()
            for a in soup.select('a[href*="/stellenangebote--"]'):
                href = a.get("href", "")
                if "-inline.html" not in href:
                    continue
                full = (href if href.startswith("http") else
                        "https://www.stepstone.de" + href).split("?")[0]
                if full in seen:
                    continue
                seen.add(full)
                title = a.get_text(" ", strip=True)
                if not title or len(title) < 5:
                    continue
                m = re.search(r"--(.+?)--(\d+)-inline\.html$", full)
                meta = m.group(1) if m else ""
                jobs.append({"source": "stepstone", "url": full, "title": title[:200],
                             "company": "", "location": loc or "",
                             "description": "", "raw_text": title + " " + meta})
        except Exception as e:
            log.debug(f"[StepStone] {q}: {e}")
        time.sleep(0.4)
    log.info(f"[StepStone] {len(jobs)} ({len(STEPSTONE_QUERIES)} Suchen)")
    return jobs


# ============================================================
# sz-jobs.de
# ============================================================
def crawl_szjobs(session) -> list:
    jobs = []
    base = "https://www.sz-jobs.de"
    paths = [
        "/stellenangebote/muenchen", "/stellenangebote/muenchen?seite=2",
        "/stellenangebote/muenchen?seite=3", "/stellenangebote/muenchen?seite=4",
        "/suche?freitext=Senior+Projektmanager&ort=M%C3%BCnchen",
        "/suche?freitext=KI+Manager&ort=M%C3%BCnchen",
        "/suche?freitext=Projektleiter+Automotive&ort=M%C3%BCnchen",
        "/suche?freitext=Senior+Project+Manager&ort=M%C3%BCnchen",
        "/suche?freitext=Programmleiter&ort=M%C3%BCnchen",
    ]
    for p in paths:
        try:
            r = session.get(base + p, timeout=15)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "lxml")
            seen = set()
            for a in soup.select('a[href*="/jobs/"]'):
                href = a.get("href", "")
                if not re.search(r"/jobs/\d+/", href):
                    continue
                full = (href if href.startswith("http") else base + href).split("?")[0]
                if full in seen:
                    continue
                seen.add(full)
                title = a.get_text(" ", strip=True)
                if not title or len(title) < 5:
                    continue
                jobs.append({"source": "sz-jobs", "url": full, "title": title[:200],
                             "company": "", "location": "München",
                             "description": "", "raw_text": title})
        except Exception as e:
            log.debug(f"[sz-jobs] {p}: {e}")
        time.sleep(0.4)
    log.info(f"[sz-jobs] {len(jobs)}")
    return jobs


# ============================================================
# kimeta
# ============================================================
KIMETA_QUERIES = [
    "stellenangebote-projektmanager-in-münchen",
    "stellenangebote-projektleiter-in-münchen",
    "it-projektmanager-jobs-münchen",
    "stellenangebote-senior-projektmanager-in-münchen",
    "ki-manager-jobs-münchen", "ai-project-manager-jobs-münchen",
    "projektmanager-automotive-jobs-münchen",
    "projektmanager-pharma-jobs-münchen",
    "modulleiter-jobs-münchen", "programmleiter-jobs-münchen",
    "baugruppenverantwortlicher-jobs-münchen",
    # NEU 2026-06-01 (Andy-Fokus)
    "stellenangebote-teilprojektleiter-in-münchen",
    "projektleiter-produktentwicklung-jobs-münchen",
    "technischer-projektleiter-jobs-münchen",
    "entwicklungsprojektleiter-jobs-münchen",
]


def crawl_kimeta(session) -> list:
    jobs = []
    base = "https://www.kimeta.de"
    for q in KIMETA_QUERIES:
        try:
            r = session.get(f"{base}/{q}", timeout=15)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "lxml")
            seen = set()
            for a in soup.select('a[href*="/display-job/"]'):
                href = a.get("href", "")
                full = (href if href.startswith("http") else base + href).split("?")[0]
                if full in seen:
                    continue
                seen.add(full)
                title = a.get_text(" ", strip=True)
                if not title or len(title) < 5:
                    continue
                jobs.append({"source": "kimeta", "url": full, "title": title[:200],
                             "company": "", "location": "München",
                             "description": "", "raw_text": title})
        except Exception as e:
            log.debug(f"[kimeta] {q}: {e}")
        time.sleep(0.4)
    log.info(f"[kimeta] {len(jobs)} ({len(KIMETA_QUERIES)} Suchen)")
    return jobs


# ============================================================
# jobvector
# ============================================================
def crawl_jobvector(session) -> list:
    jobs = []
    queries = [
        ("ki-manager", "muenchen"), ("ai-project-manager", "muenchen"),
        ("senior-projektmanager", "muenchen"),
        ("projektleiter-automotive", "muenchen"),
        ("baugruppenverantwortlicher", "muenchen"),
        ("modulleiter", "muenchen"),
        ("projektleiter-produktentwicklung", "muenchen"),
        ("teilprojektleiter", "muenchen"),
        ("technischer-projektleiter", "muenchen"),
    ]
    for q, loc in queries:
        url = f"https://www.jobvector.de/jobs/?wo={loc}&was={q}"
        try:
            r = session.get(url, timeout=15)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "lxml")
            seen = set()
            for a in soup.select('a[href*="/job/"]'):
                href = a.get("href", "")
                m = re.search(r"/job/[a-z0-9-]+-[a-f0-9]{16}/?", href)
                if not m:
                    continue
                full = (href if href.startswith("http") else
                        "https://www.jobvector.de" + href).split("?")[0]
                if full in seen:
                    continue
                seen.add(full)
                title = a.get_text(" ", strip=True)
                if not title or len(title) < 5:
                    continue
                jobs.append({"source": "jobvector", "url": full, "title": title[:200],
                             "company": "", "location": loc or "",
                             "description": "", "raw_text": title})
        except Exception as e:
            log.debug(f"[jobvector] {q}: {e}")
        time.sleep(0.4)
    log.info(f"[jobvector] {len(jobs)}")
    return jobs


# ============================================================
# LinkedIn Anonymous Search
# ============================================================
LINKEDIN_QUERIES = [
    {"keywords": "Senior Projektmanager", "location": "Munich, Germany", "geoId": "100477049"},
    {"keywords": "KI Manager", "location": "Munich, Germany", "geoId": "100477049"},
    {"keywords": "AI Project Manager", "location": "Munich, Germany", "geoId": "100477049"},
    {"keywords": "Senior Project Manager", "location": "Munich, Germany", "geoId": "100477049"},
    {"keywords": "Projektleiter Automotive", "location": "Munich, Germany", "geoId": "100477049"},
    {"keywords": "Modulleiter", "location": "Munich, Germany", "geoId": "100477049"},
    {"keywords": "Programmleiter", "location": "Munich, Germany", "geoId": "100477049"},
    {"keywords": "Baugruppenverantwortlicher", "location": "Munich, Germany", "geoId": "100477049"},
    {"keywords": "Konzeptkonstrukteur", "location": "Munich, Germany", "geoId": "100477049"},
    {"keywords": "SE-Teamleiter", "location": "Munich, Germany", "geoId": "100477049"},
    {"keywords": "Senior Project Manager", "location": "Germany", "geoId": "101282230",
     "f_WT": "2"},
    {"keywords": "AI Project Manager", "location": "Germany", "geoId": "101282230"},
    {"keywords": "KI Manager", "location": "Germany", "geoId": "101282230"},
    {"keywords": "Agile Projektmanager", "location": "Munich, Germany", "geoId": "100477049"},
    {"keywords": "PMO", "location": "Munich, Germany", "geoId": "100477049"},
    # NEU 2026-06-01 (Andy-Fokus: Produktentwicklung / Teilprojektleitung / Konzept)
    {"keywords": "Projektleiter Produktentwicklung", "location": "Munich, Germany", "geoId": "100477049"},
    {"keywords": "Teilprojektleiter", "location": "Munich, Germany", "geoId": "100477049"},
    {"keywords": "Technischer Projektleiter", "location": "Munich, Germany", "geoId": "100477049"},
    {"keywords": "Entwicklungsprojektleiter", "location": "Munich, Germany", "geoId": "100477049"},
]


def crawl_linkedin(session) -> list:
    jobs = []
    base = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    seen_jids = set()
    for q in LINKEDIN_QUERIES:
        for start in [0, 25, 50]:
            params = {**q, "start": start, "f_TPR": "r604800"}
            try:
                r = session.get(base, params=params, timeout=15)
                if r.status_code != 200:
                    break
                soup = BeautifulSoup(r.text, "lxml")
                cards = soup.select('a[href*="/jobs/view/"]')
                if not cards:
                    break
                added = 0
                for a in cards:
                    href = a.get("href", "").split("?")[0]
                    m = re.search(r"-(\d+)$", href)
                    if not m:
                        continue
                    jid = m.group(1)
                    if jid in seen_jids:
                        continue
                    seen_jids.add(jid)
                    title = a.get_text(" ", strip=True)
                    if not title or len(title) < 5:
                        continue
                    company_el = a.find_next(["h4", "span"])
                    company = (company_el.get_text(" ", strip=True)
                               if company_el else "")[:80]
                    parent = a.find_parent("li") or a.find_parent("div")
                    loc_text = ""
                    if parent:
                        for el in parent.select('[class*="location"], [class*="Location"]'):
                            t = el.get_text(" ", strip=True)
                            if t and len(t) < 100:
                                loc_text = t
                                break
                    if not loc_text:
                        loc_text = q.get("location", "")
                    jobs.append({
                        "source": "linkedin", "url": href,
                        "title": title[:200], "company": company,
                        "location": loc_text, "description": "",
                        "raw_text": title,
                    })
                    added += 1
                if added == 0:
                    break
            except Exception as e:
                log.debug(f"[linkedin] {q}: {e}")
                break
            time.sleep(0.5)
    log.info(f"[LinkedIn] {len(jobs)} ({len(LINKEDIN_QUERIES)} Suchen)")
    return jobs


# ============================================================
# RemoteOK API (NEU v4)
# ============================================================
def crawl_remoteok(session) -> list:
    log.info("[RemoteOK] API…")
    jobs = []
    try:
        # Source-Attribution wie von RemoteOK gefordert
        hdrs = {**HEADERS, "User-Agent": "andy-jobs (https://github.com/Andy2407/andy-jobs) - attribution: remoteok.com"}
        r = session.get("https://remoteok.com/api", headers=hdrs, timeout=15)
        if r.status_code != 200:
            log.warning(f"[RemoteOK] HTTP {r.status_code}")
            return []
        data = r.json()
        # Erstes Item ist Metadaten — überspringen
        items = [j for j in data if isinstance(j, dict) and j.get("id")]
        for j in items:
            tags = j.get("tags") or []
            if isinstance(tags, list):
                tag_str = " ".join(str(t) for t in tags)
            else:
                tag_str = ""
            jobs.append({
                "source": "remoteok",
                "url": j.get("url") or f"https://remoteok.com/remote-jobs/{j.get('slug','')}",
                "title": j.get("position", "") or j.get("title", ""),
                "company": j.get("company", ""),
                "location": j.get("location", "") or "Remote",
                "description": (j.get("description") or "")[:600],
                "raw_text": (j.get("position", "") + " " + tag_str)[:500],
                "remote": True,
            })
    except Exception as e:
        log.warning(f"[RemoteOK] {e}")
    log.info(f"[RemoteOK] {len(jobs)} Jobs")
    return jobs


# ============================================================
# Remotive API (NEU v4)
# ============================================================
def crawl_remotive(session) -> list:
    log.info("[Remotive] API…")
    jobs = []
    queries = [
        {"search": "project manager"},
        {"search": "program manager"},
        {"search": "AI manager"},
        {"category": "project-management"},
    ]
    seen_urls = set()
    for params in queries:
        try:
            r = session.get("https://remotive.com/api/remote-jobs",
                            params={**params, "limit": "100"}, timeout=15)
            if r.status_code != 200:
                continue
            for j in r.json().get("jobs", []):
                u = j.get("url")
                if not u or u in seen_urls:
                    continue
                seen_urls.add(u)
                jobs.append({
                    "source": "remotive",
                    "url": u,
                    "title": j.get("title", ""),
                    "company": j.get("company_name", ""),
                    "location": j.get("candidate_required_location", "") or "Remote",
                    "description": (j.get("description") or "")[:600],
                    "raw_text": j.get("title", ""),
                    "remote": True,
                })
        except Exception as e:
            log.debug(f"[Remotive] {params}: {e}")
        time.sleep(0.4)
    log.info(f"[Remotive] {len(jobs)} Jobs")
    return jobs


# ============================================================
# WeWorkRemotely RSS (NEU v4)
# ============================================================
WWR_FEEDS = [
    "https://weworkremotely.com/categories/remote-management-and-finance-jobs.rss",
    "https://weworkremotely.com/categories/remote-product-jobs.rss",
    "https://weworkremotely.com/categories/all-other-remote-jobs.rss",
]


def crawl_weworkremotely(session) -> list:
    log.info("[WeWorkRemotely] RSS…")
    jobs = []
    for feed in WWR_FEEDS:
        try:
            r = session.get(feed, timeout=15)
            if r.status_code != 200:
                continue
            try:
                root = ET.fromstring(r.text)
            except ET.ParseError:
                continue
            for item in root.findall(".//item"):
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                desc = (item.findtext("description") or "").strip()
                region = (item.findtext("region") or "").strip()
                country = (item.findtext("country") or "").strip()
                if not link:
                    continue
                # WWR-Title-Format: "Company: Job Title"
                company = ""
                if ":" in title:
                    parts = title.split(":", 1)
                    company = parts[0].strip()
                    real_title = parts[1].strip()
                else:
                    real_title = title
                jobs.append({
                    "source": "weworkremotely",
                    "url": link,
                    "title": real_title[:200],
                    "company": company[:80],
                    "location": (region or country or "Remote")[:100],
                    "description": desc[:600],
                    "raw_text": real_title,
                    "remote": True,
                })
        except Exception as e:
            log.debug(f"[WWR] {feed}: {e}")
        time.sleep(0.3)
    log.info(f"[WeWorkRemotely] {len(jobs)} Jobs ({len(WWR_FEEDS)} Feeds)")
    return jobs


# ============================================================
# Indeed via Playwright (NEU v4 — optional, nur wenn playwright verfügbar)
# ============================================================
def crawl_indeed_playwright() -> list:
    log.info("[Indeed-PW] Playwright…")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.info("[Indeed-PW] playwright nicht installiert — skip")
        return []
    jobs = []
    seen = set()
    queries = [
        ("Senior Projektmanager", "München"),
        ("KI Manager", "München"),
        ("AI Project Manager", "München"),
        ("Projektleiter Automotive", "München"),
        ("Senior Project Manager", "München"),
        ("Modulleiter", "München"),
        ("Programmleiter", "München"),
        ("KI Manager", "Deutschland"),
    ]
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ])
            context = browser.new_context(
                user_agent=UA,
                locale="de-DE",
                viewport={"width": 1280, "height": 900},
            )
            page = context.new_page()
            for query, location in queries:
                url = f"https://de.indeed.com/jobs?q={requests.utils.quote(query)}&l={requests.utils.quote(location)}&fromage=14"
                try:
                    page.goto(url, timeout=30000, wait_until="domcontentloaded")
                    page.wait_for_timeout(3000)  # Cloudflare-Challenge Zeit geben
                    html = page.content()
                    if "Just a moment" in html or "Captcha" in html:
                        log.info(f"[Indeed-PW] Captcha bei {query}/{location} — skip")
                        continue
                    soup = BeautifulSoup(html, "lxml")
                    # NEU 2026-06-02: moderne Indeed-Card = div.job_seen_beacon (statt a[data-jk]).
                    # Liefert ~16 statt 6 pro Suche und extrahiert Firma + Ort.
                    cards = soup.select('div.job_seen_beacon')
                    if not cards:
                        cards = soup.select('a[data-jk]')
                    for card in cards:
                        a = card.select_one('a[data-jk]')
                        jk = a.get("data-jk", "") if a else (card.get("data-jk", "") if card.has_attr("data-jk") else "")
                        if not jk:
                            link = card.select_one('a[href*="jk="]')
                            m = re.search(r'jk=([0-9a-fA-F]+)', link.get("href", "")) if link else None
                            jk = m.group(1) if m else ""
                        if not jk or jk in seen:
                            continue
                        seen.add(jk)
                        full = f"https://de.indeed.com/viewjob?jk={jk}"
                        te = card.select_one('h2.jobTitle span[title]') or card.select_one('h2.jobTitle a') or card.select_one('h2.jobTitle span') or card.select_one('.jobTitle')
                        title = te.get_text(" ", strip=True) if te else ""
                        if not title or len(title) < 5:
                            continue
                        ce = card.select_one('[data-testid="company-name"]') or card.select_one('span.companyName')
                        company = ce.get_text(" ", strip=True) if ce else ""
                        le = card.select_one('[data-testid="text-location"]') or card.select_one('.companyLocation')
                        loc = le.get_text(" ", strip=True) if le else location
                        jobs.append({
                            "source": "indeed",
                            "url": full,
                            "title": title[:200],
                            "company": company[:80],
                            "location": (loc[:80] or location),
                            "description": "",
                            "raw_text": title,
                        })
                except Exception as e:
                    log.debug(f"[Indeed-PW] {query}/{location}: {e}")
                page.wait_for_timeout(1500)
            browser.close()
    except Exception as e:
        log.warning(f"[Indeed-PW] Browser-Fehler: {e}")
    log.info(f"[Indeed-PW] {len(jobs)} Jobs ({len(queries)} Suchen)")
    return jobs


# ============================================================
# PW-Firmen-Harvester (NEU 2026-06-10, Andy-Order: "Diese Firmen werden nie
# durchsucht? Sofort abschalten — egal wie, stell sicher, dass diese Firmen
# in der Quelle drin sind.")
# Generischer Playwright-Link-Harvester fuer Karriereseiten mit Browser-Schutz
# (Apple/Siemens/Brose/IAV/ALTEN-DE/...). Laedt die Stellenliste im echten
# Chromium, sammelt alle Links, filtert per Job-URL-Muster; score_job() +
# Live-Verify filtern danach wie bei jeder anderen Quelle.
# Laeuft lokal UND im Cloud-Workflow (dort wird Playwright-Chromium bereits
# fuer Indeed installiert). Diehl bleibt draussen: Defense-Hard-Filter (§-Regel).
# ============================================================
# (Name, Listen-URL [wo moeglich Muenchen/Keyword vorgefiltert], href-Regex,
#  need_muc: True = Link nur uebernehmen, wenn muenchen/munich in Text+URL)
# URLs am 2026-06-10 per HTTP-Check verifiziert (viele alte Vermutungen waren 404/DNS-tot)
PW_COMPANY_SOURCES = [
    ("Apple",          "https://jobs.apple.com/de-de/search?location=munich-MUC",                                  r"/de-de/details/",            False),
    ("Siemens",        "https://jobs.siemens.com/careers?query=Projektmanager&location=Munich%2C%20Bavaria%2C%20Germany", r"/careers/job",        False),
    ("Siemens Healthineers", "https://jobs.siemens-healthineers.com/careers?location=Munich",                      r"/careers/job",               False),
    ("Brose",          "https://www.brose.com/de-de/karriere/",                                                    r"(successfactors|/job)",      True),
    ("Dräxlmaier",     "https://www.draexlmaier.com/karriere",                                                     r"(job|stellen|vacanc)",       True),
    ("IAV",            "https://www.iav.com/de/karriere/",                                                         r"/(jobs?|stellen)[/-]",       True),
    ("Marquardt",      "https://www.marquardt.com/de/karriere",                                                    r"(job|stellen|vacanc)",       True),
    ("Mahle",          "https://www.jobs.mahle.com/germany/en/",                                                   r"/job/",                      True),
    ("Leoni",          "https://www.leoni-germany.com/en/",                                                        r"(job|career/)",              True),
    ("Brunel",         "https://www.brunel.net/de-de/jobs",                                                        r"/de-de/jobs?/.{6,}",         True),
    ("Telefónica",     "https://www.telefonica.de/karriere",                                                       r"(job|stellen)",              True),
    ("Expleo",         "https://careers.expleo.com/de/",                                                           r"/(de/)?jobs?/.{4,}",         True),
    ("Preh",           "https://www.preh.com/karriere/stellenangebote",                                            r"(jobad|jobdb|stellenangebote/.)", True),
    ("Kostal",         "https://www.kostal.com/de/karriere",                                                       r"(job|stellen|vacanc)",       True),
    ("ALTEN",          "https://www.alten-consulting.de/karriere/",                                                r"/(job|stellenangebot)",      False),
]

_PW_LINKTEXT_JUNK = {"mehr erfahren", "details", "apply", "jetzt bewerben", "learn more",
                     "read more", "mehr", "ansehen", "zur stelle", "alle jobs", "karriere"}


def crawl_pw_companies() -> list:
    log.info("[PW-Firmen] Playwright-Harvester…")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.info("[PW-Firmen] playwright nicht installiert — skip")
        return []
    jobs = []
    seen = set()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ])
            context = browser.new_context(user_agent=UA, locale="de-DE",
                                          viewport={"width": 1366, "height": 950})

            def _collect(pg):
                return pg.eval_on_selector_all(
                    "a[href]",
                    "els => els.map(e => ({href: e.href, text: (e.innerText||'').trim()}))")

            for company, url, pat, need_muc in PW_COMPANY_SOURCES:
                cnt = 0
                page = context.new_page()  # frische Page je Quelle — verhindert Navigations-Kaskaden
                try:
                    page.goto(url, timeout=30000, wait_until="domcontentloaded")
                    try:
                        page.wait_for_load_state("networkidle", timeout=12000)  # SPA fertig laden
                    except Exception:
                        pass
                    page.wait_for_timeout(2500)
                    # Cookie-Banner: privacy-schonend ablehnen (nie Accept-All)
                    for sel in ('#onetrust-reject-all-handler',
                                'button:has-text("Ablehnen")',
                                'button:has-text("Alle ablehnen")',
                                'button:has-text("Nur erforderliche")',
                                'button:has-text("Reject all")'):
                        try:
                            page.click(sel, timeout=1200)
                            page.wait_for_timeout(600)
                            break
                        except Exception:
                            pass
                    for _ in range(3):
                        page.mouse.wheel(0, 2600)
                        page.wait_for_timeout(900)
                    links = _collect(page)
                    # SPA-Nachzügler: wenn noch kein Treffer-Muster, einmal nachwarten
                    if not any(re.search(pat, (l.get("href") or ""), re.I) for l in links):
                        page.wait_for_timeout(4000)
                        links = _collect(page)
                except Exception as e:
                    log.warning(f"[PW:{company}] {e}")
                    try:
                        page.close()
                    except Exception:
                        pass
                    continue
                finally:
                    pass
                for l in links:
                    href = (l.get("href") or "").split("#")[0]
                    text = re.sub(r"\s+", " ", l.get("text") or "").strip()
                    if not href or href in seen:
                        continue
                    if not re.search(pat, href, re.I):
                        continue
                    if len(text) < 10 or text.lower() in _PW_LINKTEXT_JUNK:
                        continue
                    if not re.search(r"[a-zäöüß]", text, re.I):
                        continue
                    blob = (href + " " + text).lower()
                    if need_muc and not re.search(r"m(ü|u|%c3%bc)nchen|munich|muenchen", blob):
                        continue
                    seen.add(href)
                    cnt += 1
                    if cnt > 40:
                        break
                    jobs.append({"source": f"pw:{company}", "url": href,
                                 "title": text[:200], "company": company,
                                 "location": "München", "description": "",
                                 "raw_text": text})
                log.info(f"[PW:{company}] {cnt} Job-Links")
                try:
                    page.close()
                except Exception:
                    pass
            browser.close()
    except Exception as e:
        log.warning(f"[PW-Firmen] Browser-Fehler: {e}")
    log.info(f"[PW-Firmen] {len(jobs)} Jobs gesamt ({len(PW_COMPANY_SOURCES)} Firmen)")
    return jobs




# ============================================================
# EDAG — direkter Karriereseiten-Crawler (NEU v6)
# ============================================================
def crawl_edag_karriere(session) -> list:
    log.info("[EDAG-Karriere] Stellenanzeigen…")
    jobs = []
    base = "https://www.edag.com/de/karriere/stellenanzeigen"
    seen = set()
    # Paginierte Seiten + München-Filter
    for page in range(1, 18):
        params = {"tx_successfactors_view[currentPage]": str(page)}
        try:
            r = session.get(base, params=params, timeout=15)
            if r.status_code != 200:
                break
            soup = BeautifulSoup(r.text, "lxml")
            cards = soup.select('a[href*="/karriere/stellenanzeigen/detail/"]')
            if not cards:
                break
            page_added = 0
            for a in cards:
                href = a.get("href", "")
                full = (href if href.startswith("http") else
                        "https://www.edag.com" + href).split("?")[0]
                if full in seen:
                    continue
                seen.add(full)
                title = a.get_text(" ", strip=True)
                if not title or len(title) < 5:
                    continue
                # Standort aus URL-Slug oder Parent-Element
                parent = a.find_parent("li") or a.find_parent("div") or a
                loc_text = ""
                for el in parent.select('[class*="location"], [class*="ort"]'):
                    t = el.get_text(" ", strip=True)
                    if t and len(t) < 80:
                        loc_text = t
                        break
                jobs.append({"source": "edag-karriere", "url": full,
                             "title": title[:200], "company": "EDAG Engineering",
                             "location": loc_text, "description": "",
                             "raw_text": title})
                page_added += 1
            if page_added == 0:
                break
        except Exception as e:
            log.debug(f"[EDAG-Karriere] page {page}: {e}")
            break
        time.sleep(0.4)
    log.info(f"[EDAG-Karriere] {len(jobs)} Jobs (paginated)")
    return jobs


# ============================================================
# Cognizant Mobility — direkte Karriere (NEU v6, falls erreichbar)
# ============================================================
def crawl_cognizant_mobility(session) -> list:
    log.info("[CognizantMobility] Stellenliste…")
    jobs = []
    try:
        r = session.get("https://jobs.cognizant-mobility.com/job-list",
                        timeout=15)
        if r.status_code != 200:
            r = session.get("https://jobs.cognizant-mobility.com/", timeout=15)
        if r.status_code != 200:
            return []
        soup = BeautifulSoup(r.text, "lxml")
        seen = set()
        for a in soup.select('a[href*="/job/"], a[href*="/jobs/"], a[href*="/stelle"]'):
            href = a.get("href", "")
            full = (href if href.startswith("http") else
                    "https://jobs.cognizant-mobility.com" + href).split("?")[0]
            if full in seen or len(full) < 30:
                continue
            seen.add(full)
            title = a.get_text(" ", strip=True)
            if not title or len(title) < 5:
                continue
            jobs.append({"source": "cognizant-mobility", "url": full,
                         "title": title[:200], "company": "Cognizant Mobility",
                         "location": "München", "description": "",
                         "raw_text": title})
    except Exception as e:
        log.warning(f"[CognizantMobility] {e}")
    log.info(f"[CognizantMobility] {len(jobs)} Jobs")
    return jobs


# ============================================================
# Verifikation
# ============================================================
EXPIRED_INDICATORS = [
    "diese url existiert nicht", "url existiert nicht", "stelle wurde besetzt",
    "stellenangebot ist nicht mehr verfügbar", "dieses stellenangebot ist abgelaufen",
    "page not found", "position closed", "job has been filled",
    # NEU 2026-06-02: nacktes "expired" ENTFERNT — es war ein False-Positive-Killer. Es matchte
    # JS/CSS auf LIVE-Seiten (z.B. "tokenExpired", "expired:false" bei Yourfirm) und verwarf
    # massenhaft valide Jobs quer durch alle HTML-Quellen. Ersetzt durch präzise Status-Phrasen:
    "job expired", "this job has expired", "posting has expired", "vacancy has expired",
    "ad has expired", "anzeige ist abgelaufen", "stellenanzeige ist abgelaufen",
    "angebot ist abgelaufen", "inserat ist abgelaufen",
    "nicht mehr verfügbar", "no longer available", "stelle besetzt",
]
SPA_DOMAINS = ("jobs.personio.de", "smartrecruiters.com", "myworkdayjobs.com",
               "ashbyhq.com", "lever.co", "boards.greenhouse.io",
               "workable.com", "recruitee.com", "stepstone.de",
               "linkedin.com", "indeed.com", "remoteok.com", "remotive.com",
               "weworkremotely.com", "remotely.de")


def verify_url(url: str, session) -> tuple:
    """Returnt (ok, status, html_or_none) — html nur wenn vollständig gefetched."""
    if not url:
        return (False, "no-url", None)
    try:
        r = session.get(url, timeout=12, allow_redirects=True)
        if r.status_code in (403, 999):
            return (True, f"ok-{r.status_code}-trusted", None)
        if r.status_code != 200:
            return (False, f"HTTP {r.status_code}", None)
        host = urlparse(url).hostname or ""
        if any(d in host for d in SPA_DOMAINS):
            return (True, "ok-spa", r.text)
        body = r.text.lower()
        for ind in EXPIRED_INDICATORS:
            if ind in body:
                return (False, f"expired: {ind}", None)
        return (True, "ok", r.text)
    except Exception as e:
        return (False, f"err: {type(e).__name__}", None)


# NEU 2026-05-28 (Andy v14): Detail-Parser für Recruiter/Adresse/Kennziffer aus Job-HTML
# Output landet in data.json → DOCX-Generator zieht es automatisch ohne User-Input
def parse_job_details(html: str, url: str = "") -> dict:
    """Extrahiert recruiter, address (street/city), kennziffer, clean_company aus Job-HTML.
    Strategie v15:
      1) JSON-LD Schema.org JobPosting (LinkedIn/StepStone/Greenhouse/Workday — Goldgrube!)
      2) Regex-Fallback für ältere Seiten
    """
    out = {"recruiter": "", "address_street": "", "address_city": "", "kennziffer": "", "clean_company": ""}
    if not html or len(html) < 50:
        return out

    # === SCHRITT 1: JSON-LD JobPosting (Schema.org) ===
    try:
        ld_blocks = re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.DOTALL)
        for ld in ld_blocks:
            try:
                data = json.loads(ld.strip())
            except Exception:
                continue
            items = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
            for item in items:
                if not isinstance(item, dict): continue
                t = item.get("@type", "")
                if isinstance(t, list): t = next((x for x in t if "JobPosting" in str(x)), "")
                if "JobPosting" not in str(t): continue
                # Firma
                hiring = item.get("hiringOrganization", {})
                if isinstance(hiring, dict):
                    co = (hiring.get("name") or "").strip()
                    if co and 2 <= len(co) <= 80:
                        out["clean_company"] = co
                # Adresse
                loc = item.get("jobLocation", {})
                if isinstance(loc, list): loc = loc[0] if loc else {}
                if isinstance(loc, dict):
                    addr = loc.get("address", {})
                    if isinstance(addr, dict):
                        street = (addr.get("streetAddress") or "").strip()
                        plz = (addr.get("postalCode") or "").strip()
                        city = (addr.get("addressLocality") or "").strip()
                        if street and len(street) < 80:
                            out["address_street"] = street
                        if plz and city and re.match(r"^\d{5}$", plz):
                            out["address_city"] = f"{plz} {city}"
                        elif city and not out["address_city"]:
                            out["address_city"] = city
                # Kennziffer NUR aus explizitem identifier.name (NICHT interne LinkedIn-Job-ID)
                ident = item.get("identifier", {})
                if isinstance(ident, dict):
                    ident_name = (ident.get("name") or "").lower()
                    ident_val = (ident.get("value") or "").strip()
                    if ident_val and any(k in ident_name for k in ["kennziffer","reference","referenz","requisition","ref-nr","ref nr"]):
                        if 2 <= len(ident_val) <= 25 and not re.fullmatch(r"\d{4,}", ident_val):
                            out["kennziffer"] = ident_val
            if out["clean_company"] and out["address_city"]:
                break
    except Exception as e:
        log.debug(f"JSON-LD parse err für {url[:60]}: {e}")

    # === SCHRITT 2: Regex-Fallback (Text-basiert) ===
    # HTML-Tags entfernen für sauberes Regex (außer line breaks via Replace)
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;|&#160;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&auml;", "ä", text); text = re.sub(r"&ouml;", "ö", text); text = re.sub(r"&uuml;", "ü", text)
    text = re.sub(r"&Auml;", "Ä", text); text = re.sub(r"&Ouml;", "Ö", text); text = re.sub(r"&Uuml;", "Ü", text)
    text = re.sub(r"&szlig;", "ß", text)
    text = re.sub(r"&quot;", '"', text); text = re.sub(r"&#39;", "'", text)
    text = re.sub(r"\s+", " ", text)

    # === Recruiter / Ansprechpartner ===
    # Pattern 1: "Ansprechpartner(in)? : Frau Schmidt" / "Kontakt: Herr Müller"
    rec_patterns = [
        r"(?:Ansprechpartner(?:in)?|Kontakt(?:person)?|Recruiter|Recruiting|Ihr(?:e)?\s+Ansprechpartner(?:in)?)\s*[:\-]?\s*(Frau|Herr|Dr\.|Mr\.|Mrs\.|Ms\.)\s+([A-ZÄÖÜ][a-zäöüß\-]+(?:\s+[A-ZÄÖÜ][a-zäöüß\-]+){0,2})",
        r"(?:Your\s+contact|Contact\s+person)\s*[:\-]?\s*(?:Ms\.|Mrs\.|Mr\.)?\s*([A-ZÄÖÜ][a-zäöüß\-]+\s+[A-ZÄÖÜ][a-zäöüß\-]+)",
    ]
    for pat in rec_patterns:
        m = re.search(pat, text)
        if m:
            if len(m.groups()) == 2:
                out["recruiter"] = (m.group(1) + " " + m.group(2)).strip()
            else:
                out["recruiter"] = m.group(1).strip()
            break
    # Pattern 2 (Fallback): einfaches "Frau Mustermann" / "Herr Müller" in der Nähe von "Recruiting"/"HR"
    if not out["recruiter"]:
        m = re.search(r"(Frau|Herr)\s+([A-ZÄÖÜ][a-zäöüß\-]{2,15}(?:\s+[A-ZÄÖÜ][a-zäöüß\-]{2,20}){0,2})\s*(?:[·\|]\s*)?(?:Recruiting|HR|Personal|Talent[\s\-]?Acquisition)", text)
        if m:
            out["recruiter"] = (m.group(1) + " " + m.group(2)).strip()

    # === Kennziffer STRIKT — Token MUSS Ziffer enthalten (sonst "nummer", "Reference" etc. matched) ===
    kz_patterns = [
        r"(?:Kennziffer|Referenz(?:nummer)?|Ref(?:erenz)?[\s\.\-]?Nr\.?|Stellen(?:anzeige)?[\s\-]?(?:Nr\.?|ID)|Job[\s\-]?ID|Stellen-?ID|Anzeigen[\s\-]?Nr\.?|Job-?Nummer|Req(?:uisition)?[\s\-]?ID)\s*[:\.\-#]?\s*([A-Z0-9][A-Z0-9\-\/\.]*\d[A-Z0-9\-\/\.]*)",
        r"\b(?:Ref|Req)[\s\.\-]?(?:ID|Nr\.?)?[\s:]+([A-Z0-9]*\d[A-Z0-9\-\/\.]{1,20})\b",
    ]
    KZ_STOPWORDS = {"der","das","die","und","nummer","number","reference","kennzeichen","id","nr"}
    for pat in kz_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            kz = m.group(1).strip().strip(".,;")
            # MUSS Ziffer enthalten + Stopword-Filter + KEINE reine 4+stellige Zahl (= PLZ/Marketing-Müll)
            if (2 <= len(kz) <= 25 and
                kz.lower() not in KZ_STOPWORDS and
                any(c.isdigit() for c in kz) and
                not re.fullmatch(r"\d{4,}", kz)):
                out["kennziffer"] = kz
                break

    # === Adresse (PLZ + Stadt) ===
    # Negative Lookahead: nach 5-stelliger Zahl NIE "Euro/EUR/€/Brutto/p.a./Gehalt/jährlich/monatlich/Standorten/etc."
    NOT_AFTER_PLZ = r"(?!\s*(?:Euro|EUR|€|\$|USD|GBP|Brutto|brutto|netto|p\.\s*a\.?|pro\s+Jahr|monatlich|jährlich|Gehalt|gehalt|Jahresgehalt|Standorte?n?|Mitarbeiter|Stellen|Jobs|Kunden|Bewerber|Niederlassungen?|Filialen|Tagen?|Wochen))"
    BAD_CITIES = {"euro","eur","brutto","netto","gehalt","jahr","monat","jahre","monate","stunden","stunde","monatlich","jährlich",
                  "standorte","standorten","standort","mitarbeiter","mitarbeitende","mitarbeiterin","stellen","jobs","kunden",
                  "bewerber","niederlassungen","filialen","tagen","wochen","tausend","million","prozent"}
    addr_patterns = [
        r"([A-ZÄÖÜ][a-zäöüß\-]+(?:str(?:asse|aße)\.?|[Aa]llee|[Pp]latz|[Rr]ing|[Ww]eg|[Gg]asse|[Bb]oulevard))\s+(\d+(?:\s*[a-z]?)(?:\s*[\-\/]\s*\d+)?)\s*[,\n]?\s*(\d{5})" + NOT_AFTER_PLZ + r"\s+([A-ZÄÖÜ][a-zäöüß\-]{2,25})\b",
    ]
    for pat in addr_patterns:
        m = re.search(pat, text)
        if m:
            plz = m.group(3); stadt = m.group(4)
            if not (plz.startswith("00") or plz == "99999") and stadt.lower() not in BAD_CITIES:
                out["address_street"] = (m.group(1) + " " + m.group(2)).strip()
                out["address_city"] = (plz + " " + stadt).strip()
                break
    # Fallback: PLZ + Ort allein (mit Lookahead + Range + Stopword-Check)
    if not out["address_city"]:
        for m in re.finditer(r"\b(\d{5})" + NOT_AFTER_PLZ + r"\s+([A-ZÄÖÜ][a-zäöüß\-]{2,25})\b", text):
            plz = m.group(1); stadt = m.group(2)
            if plz.startswith("00") or plz == "99999": continue
            if stadt.lower() in BAD_CITIES: continue
            out["address_city"] = (plz + " " + stadt).strip()
            break

    return out


def parallel_verify(jobs, session, max_workers: int = 10) -> list:
    log.info(f"Verifiziere {len(jobs)} URLs (mit Detail-Parse)…")
    out = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(verify_url, j["url"], session): j for j in jobs}
        for f in as_completed(futs):
            j = futs[f]
            ok, status, html = f.result()
            j["verified"] = ok
            j["verify_status"] = status
            if ok:
                # NEU 2026-05-28: Detail-Parse für DOCX-Generator (v15 + clean_company aus JSON-LD)
                if html:
                    try:
                        det = parse_job_details(html, j.get("url", ""))
                        if det.get("recruiter"): j["recruiter"] = det["recruiter"]
                        if det.get("address_street"): j["address_street"] = det["address_street"]
                        if det.get("address_city"): j["address_city"] = det["address_city"]
                        if det.get("kennziffer"): j["kennziffer"] = det["kennziffer"]
                        # clean_company aus JSON-LD: bessere Firmen-Erkennung als company-Feld
                        if det.get("clean_company"): j["clean_company"] = det["clean_company"]
                    except Exception as e:
                        log.debug(f"parse_job_details Fehler für {j.get('url', '')[:80]}: {e}")
                out.append(j)
    parsed = sum(1 for j in out if j.get("recruiter") or j.get("kennziffer") or j.get("address_city"))
    log.info(f"  → {len(out)}/{len(jobs)} live · {parsed} mit Empfänger-Details")
    return out



def _load_existing_first_seen() -> dict:
    """Lädt URL → first_seen (str) aus dem bisherigen data.json, damit Aktualität persistent ist."""
    if not DATA_PATH.exists():
        return {}
    try:
        prev = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        out = {}
        for j in prev.get("jobs", []):
            u = j.get("url")
            fs = j.get("first_seen") or j.get("generated_at") or ""
            if u and isinstance(fs, str) and fs:
                out[u] = fs
        # Globaler Fallback: payload generated_at als Hint für alte Jobs ohne first_seen
        global_ts = prev.get("generated_at") or ""
        if isinstance(global_ts, str):
            for j in prev.get("jobs", []):
                u = j.get("url")
                if u and u not in out and global_ts:
                    out[u] = global_ts
        return out
    except Exception:
        return {}

def _normalize_for_dedupe(s: str) -> str:
    """Normalize string for dedupe: lowercase, alphanumeric only."""
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())[:60]


def apply_filter(jobs) -> list:
    """Filter + dedupe + first_seen persistieren. Sortierung: first_seen DESC, dann score DESC."""
    log.info(f"Filter+Score auf {len(jobs)} Jobs…")
    first_seen_map = _load_existing_first_seen()
    now_iso = datetime.now().isoformat()
    seen_url = set()
    by_hash = {}
    out = []
    blocked = duped = low = 0
    fresh = 0
    for j in jobs:
        url = j.get("url")
        if not url or url in seen_url:
            duped += 1
            continue
        seen_url.add(url)
        # NEU 2026-06-01: einzelne von Andy geblockte Stellen-URLs (user_overrides.json) raus
        if USER_BLOCKED_URLS and any(b in url.lower() for b in USER_BLOCKED_URLS):
            blocked += 1
            continue
        score, reasons = score_job(
            j.get("title", ""), j.get("raw_text", "") or j.get("description", ""),
            j.get("location", ""), j.get("company", "")
        )
        if score < 0:
            blocked += 1
            continue
        if score < MIN_SCORE_TO_INCLUDE:
            low += 1
            continue
        # NEU 2026-06-01: "other"-Kategorie strenger filtern. Das Dashboard zeigt im PM-Tab
        # pm+other zusammen; "other" war zuletzt 159/283 = Rauschen. Echte PM/Auto/KI-Stellen
        # sind nicht betroffen (eigene Kategorie), nur unklare Rest-Treffer fliegen jetzt raus.
        cat = categorize(j.get("title", ""), j.get("description", ""), j.get("company", ""))
        if cat == "other" and score < OTHER_MIN_SCORE:
            low += 1
            continue
        h = (_normalize_for_dedupe(j.get("title", "")) + "|" +
             _normalize_for_dedupe(j.get("company", "")) + "|" +
             _normalize_for_dedupe(j.get("location", "")[:30]))
        if h in by_hash and len(_normalize_for_dedupe(j.get("title",""))) > 5:
            primary = by_hash[h]
            primary.setdefault("alt_sources", []).append({
                "source": j.get("source"), "url": url,
            })
            duped += 1
            continue
        # first_seen: aus altem data.json holen oder NEU markieren
        existing_fs = first_seen_map.get(url)
        if existing_fs and isinstance(existing_fs, str):
            j["first_seen"] = existing_fs
            j["is_new"] = False
        else:
            j["first_seen"] = now_iso
            j["is_new"] = True
            fresh += 1
        j["score"] = score
        j["score_reasons"] = reasons[:5]
        j["category"] = cat
        j["alt_sources"] = []
        by_hash[h] = j
        out.append(j)
    # Sortierung: zuerst nach first_seen DESC (neueste oben), dann score DESC
    out.sort(key=lambda x: (x.get("first_seen") or "", x.get("score") or 0), reverse=True)
    log.info(f"  → {len(out)} · {blocked} blocked · {low} low · {duped} dupes · {fresh} NEU")
    return out


def load_manual_jobs() -> list:
    """Manuelle Stellen aus user_overrides.json -> Job-Schema (NEU 2026-06-03).

    Fuer Treffer, die KEIN Crawler erreicht (HRworks-/JS-Portale wie OmniVision, FEV).
    Die Eintraege liegen persistent im Repo (user_overrides.json -> manual_jobs) und
    ueberstehen JEDEN Lauf. Sie durchlaufen NICHT score_job (wuerden sonst evtl. geblockt),
    sondern werden in main() dedupe-sicher per URL an die verifizierten Jobs angehaengt.
    Pflichtfeld pro Eintrag: url. Optional: title, company, location, category, score,
    score_reasons, contact, verified_on (YYYY-MM-DD), description.
    """
    path = Path(__file__).resolve().parent / "user_overrides.json"
    try:
        ov = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log.debug(f"[manual_jobs] {e}")
        return []
    out = []
    for m in ov.get("manual_jobs", []):
        url = str(m.get("url", "")).strip()
        if not url:
            continue
        vdate = str(m.get("verified_on", "")).strip()
        reasons = [str(r) for r in (m.get("score_reasons") or [])]
        if vdate and not any("erifiziert" in r for r in reasons):
            reasons.insert(0, f"✋ Manuell verifiziert {vdate}")
        out.append({
            "source": str(m.get("source", "manual")),
            "url": url,
            "title": str(m.get("title", "")),
            "company": str(m.get("company", "")),
            "location": str(m.get("location", "")),
            "description": str(m.get("description", "")),
            "category": str(m.get("category", "pm")),
            "score": int(m.get("score", 0) or 0),
            "score_reasons": reasons[:5],
            "first_seen": (vdate + "T12:00:00") if re.match(r"^\d{4}-\d{2}-\d{2}$", vdate)
                          else datetime.now().isoformat(),
            "is_new": True,
            "manual": True,
            "verified": True,
            "verify_status": "manual",
            "recruiter": str(m.get("contact", "")),
            "alt_sources": [],
        })
    log.info(f"[manual_jobs] {len(out)} manuelle Stellen geladen")
    return out


# ============================================================
# NEU 2026-05-28 (Andy explizit): 4 neue Quellen
# ============================================================
def crawl_sii_group(session) -> list:
    """SII Group — Andy explizit 2026-05-28 'gefunden bei SII Group'"""
    log.info("[SII] Karriere-API holen…")
    jobs = []
    candidates = [
        "https://api.smartrecruiters.com/v1/companies/SiiPolska/postings?limit=100&country=de",
        "https://api.smartrecruiters.com/v1/companies/SIIGermany/postings?limit=100",
        "https://api.smartrecruiters.com/v1/companies/SII/postings?limit=100&country=de",
    ]
    for url in candidates:
        try:
            r = session.get(url, timeout=15)
            if r.status_code != 200: continue
            data = r.json()
            for p in data.get("content", []):
                loc = p.get("location", {})
                loc_str = ", ".join(filter(None, [loc.get("city"), loc.get("country")]))
                if "de" not in (loc.get("country") or "").lower() and "germany" not in loc_str.lower():
                    continue
                jobs.append({
                    "source": "sii_group",
                    "url": p.get("ref", p.get("applyUrl", "")),
                    "title": p.get("name", ""),
                    "company": "SII Group",
                    "location": loc_str or "Deutschland",
                    "description": (p.get("jobAd", {}) or {}).get("sections", {}).get("jobDescription", {}).get("text", "")[:1500],
                })
            if jobs: break
        except Exception as e:
            log.debug(f"[SII] {url}: {e}")
    if not jobs:
        try:
            r = session.get("https://de.sii-group.com/de-de/karriere", timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.select("a[href*='job'], a[href*='offer'], a[href*='karriere']"):
                href = a.get("href", ""); title = a.get_text(strip=True)
                if not title or len(title) < 10: continue
                if href.startswith("/"): href = "https://de.sii-group.com" + href
                jobs.append({"source": "sii_group", "url": href, "title": title,
                             "company": "SII Group", "location": "Deutschland", "description": ""})
        except Exception as e:
            log.warning(f"[SII] Fallback: {e}")
    log.info(f"[SII] {len(jobs)} Jobs")
    return jobs


def crawl_rodenstock(session) -> list:
    """Rodenstock — Andy 2026-05-28 als Wunschfirma genannt"""
    log.info("[Rodenstock] Karriere-API…")
    jobs = []
    candidates = [
        "https://boards-api.greenhouse.io/v1/boards/rodenstock/jobs",
        "https://api.smartrecruiters.com/v1/companies/Rodenstock/postings?limit=100",
    ]
    for url in candidates:
        try:
            r = session.get(url, timeout=15)
            if r.status_code != 200: continue
            if "greenhouse" in url:
                for j in r.json().get("jobs", []):
                    loc = (j.get("location") or {}).get("name") or ""
                    jobs.append({"source": "rodenstock", "url": j.get("absolute_url", ""),
                                 "title": j.get("title", ""), "company": "Rodenstock",
                                 "location": loc, "description": ""})
                if jobs: break
            elif "smartrecruiters" in url:
                for p in r.json().get("content", []):
                    loc = p.get("location", {})
                    loc_str = ", ".join(filter(None, [loc.get("city"), loc.get("country")]))
                    jobs.append({"source": "rodenstock", "url": p.get("ref", p.get("applyUrl", "")),
                                 "title": p.get("name", ""), "company": "Rodenstock",
                                 "location": loc_str or "München", "description": ""})
                if jobs: break
        except Exception as e:
            log.debug(f"[Rodenstock] {url}: {e}")
    log.info(f"[Rodenstock] {len(jobs)} Jobs")
    return jobs


def crawl_cariad(session) -> list:
    """CARIAD — VW-Software-Tochter, Andys VW-Scout-Brücke"""
    log.info("[CARIAD] SmartRecruiters…")
    jobs = []
    try:
        r = session.get("https://api.smartrecruiters.com/v1/companies/CariadSE/postings?limit=100&country=de", timeout=15)
        if r.status_code == 200:
            for p in r.json().get("content", []):
                loc = p.get("location", {})
                loc_str = ", ".join(filter(None, [loc.get("city"), loc.get("country")]))
                jobs.append({"source": "cariad", "url": p.get("ref", p.get("applyUrl", "")),
                             "title": p.get("name", ""), "company": "CARIAD",
                             "location": loc_str or "Wolfsburg/Ingolstadt", "description": ""})
    except Exception as e:
        log.warning(f"[CARIAD] {e}")
    log.info(f"[CARIAD] {len(jobs)} Jobs")
    return jobs


def crawl_mtu(session) -> list:
    """MTU Aero Engines — München-OEM (Aerospace)"""
    log.info("[MTU] Workday-API…")
    jobs = []
    try:
        r = session.post("https://mtu.wd3.myworkdayjobs.com/wday/cxs/mtu/External/jobs",
                         timeout=15, json={"limit": 50, "offset": 0, "searchText": ""},
                         headers={"Content-Type": "application/json", "Accept": "application/json"})
        if r.status_code == 200:
            for p in r.json().get("jobPostings", []):
                loc = p.get("locationsText") or ""
                if not any(k in loc.lower() for k in ["münchen", "munich", "remote", "deutschland", "germany"]):
                    continue
                jobs.append({"source": "mtu",
                             "url": "https://mtu.wd3.myworkdayjobs.com" + p.get("externalPath", ""),
                             "title": p.get("title", ""), "company": "MTU Aero Engines",
                             "location": loc, "description": ""})
    except Exception as e:
        log.warning(f"[MTU] {e}")
    log.info(f"[MTU] {len(jobs)} Jobs")
    return jobs


# ============================================================
# NEU 2026-06-01 (Andy God-Mode): Top-Treffer-Firmen als Direkt-Quellen.
# ATS-Endpoints live verifiziert (alle requests-scrapebar, kein Browser nötig).
# ============================================================
def crawl_dvinci(session, host, company, muc_keys) -> list:
    """d.vinci JSON-Feed (FEV, SÜSS MicroTec). Endpoint: https://{host}/jobPublication/list.json
    Root ist ein JSON-Array. Standort-Filter auf muc_keys (München/Garching)."""
    log.info(f"[{company}] d.vinci Feed…")
    jobs = []
    try:
        r = session.get(f"https://{host}/jobPublication/list.json",
                        params={"language": "de"}, timeout=15)
        if r.status_code != 200:
            log.warning(f"[{company}] HTTP {r.status_code}")
            return []
        data = r.json()
        items = data if isinstance(data, list) else (
            data.get("jobPublications") or data.get("items") or [])
        for it in items:
            if not isinstance(it, dict):
                continue
            title = it.get("position", "") or it.get("title", "")
            url = it.get("jobPublicationURL", "") or it.get("url", "")
            jo = it.get("jobOpening", {}) or {}
            loc = jo.get("location", "") or ""
            locs = jo.get("locations", []) or []
            loc_names = [L.get("name", "") for L in locs if isinstance(L, dict)]
            loc_full = (loc + " " + " ".join(loc_names)).strip()
            if not any(k in loc_full.lower() for k in muc_keys):
                continue
            rc = it.get("renderedContent", {}) or {}
            desc = ""
            if isinstance(rc, dict):
                desc = " ".join(str(v) for v in rc.values() if isinstance(v, str))[:1500]
            if not desc:
                desc = (str(it.get("tasks", "")) + " " + str(it.get("profile", "")))[:1500]
            if not url or not title:
                continue
            jobs.append({"source": f"dvinci:{company}", "url": url, "title": title[:200],
                         "company": company, "location": loc_full or "München",
                         "description": desc, "raw_text": title})
    except Exception as e:
        log.warning(f"[{company}] {e}")
    log.info(f"[{company}] {len(jobs)} Jobs (München/Garching)")
    return jobs


def crawl_fev(session) -> list:
    return crawl_dvinci(session, "career.fev.com", "FEV", ["münchen", "munich"])


def crawl_suss(session) -> list:
    return crawl_dvinci(session, "career.suss.com", "SÜSS MicroTec",
                        ["garching", "münchen", "munich"])


def crawl_successfactors_sitemap(session, host, company, muc_regex) -> list:
    """SAP SuccessFactors via sitemap.xml (MAN, Webasto, Knorr-Bremse). Die /search/-SPA ist
    nicht scrapebar, aber die sitemap.xml listet jede Stelle als /job/{Stadt}-{Titel}-{Suffix}-{PLZ}/{id}/.
    Volltext zieht der JSON-LD-Parser später aus der Detailseite."""
    log.info(f"[{company}] SF-Sitemap…")
    jobs = []
    try:
        r = session.get(f"https://{host}/sitemap.xml", timeout=20)
        if r.status_code != 200:
            log.warning(f"[{company}] sitemap HTTP {r.status_code}")
            return []
        text = r.text.replace("&amp;", "&")
        locs = re.findall(r"<loc>\s*([^<]+?)\s*</loc>", text)
        muc = re.compile(muc_regex, re.I)
        seen = set()
        for raw in locs:
            url = unquote(raw.strip())
            if "/job/" not in url or not muc.search(url):
                continue
            m = re.search(r"/job/(.+?)/(\d+)/?$", url)
            if not m:
                continue
            slug, jid = m.group(1), m.group(2)
            if jid in seen:
                continue
            seen.add(jid)
            parts = slug.split("-")
            slug_l = slug.lower()
            KNOWN_CITIES = ["münchen", "muenchen", "garching", "ismaning", "unterschleißheim",
                            "putzbrunn", "stockdorf", "gilching", "augsburg", "penzberg",
                            "taufkirchen", "parsdorf", "ottobrunn", "unterhaching", "haar",
                            "feldkirchen", "aschheim", "kirchheim", "germering", "martinsried"]
            city = next((c.title() for c in KNOWN_CITIES if c in slug_l),
                        parts[0] if parts else "")
            title_words = [p for p in parts[1:] if p and not re.fullmatch(r"\d{4,5}", p)
                           and p.lower() not in ("mwd", "wmd", "fmx", "wmx", "fmd",
                                                  "m", "w", "d", "x")]
            title = " ".join(title_words).strip() or slug.replace("-", " ")
            jobs.append({"source": f"sf:{company}", "url": url, "title": title[:200],
                         "company": company, "location": city,
                         "description": "", "raw_text": title})
    except Exception as e:
        log.warning(f"[{company}] {e}")
    log.info(f"[{company}] {len(jobs)} Jobs (München-Region)")
    return jobs


def crawl_man(session) -> list:
    return crawl_successfactors_sitemap(session, "jobs.man.eu", "MAN Truck & Bus",
                                        r"/job/M[üu]nchen-")


def crawl_webasto(session) -> list:
    return crawl_successfactors_sitemap(session, "jobs.webasto.com", "Webasto",
                                        r"/job/(M[üu]nchen|Stockdorf|Gilching|Garching)-")


def crawl_knorr(session) -> list:
    return crawl_successfactors_sitemap(session, "careers.knorr-bremse.com", "Knorr-Bremse",
                                        r"/job/M[üu]nchen-")


def crawl_silver_atena(session) -> list:
    """Silver Atena TYPO3 (sajobcenter). Liste server-seitig als HTML-Tabelle gerendert:
    karriere.silver-atena.de/stellenangebote, eine Stelle pro <tr> mit 3 <td>
    (Titel+Link, Funktionsbereich, Standort). Standort-Hardfilter macht location_passes."""
    log.info("[Silver Atena] Stellenliste…")
    jobs = []
    base = "https://karriere.silver-atena.de"
    try:
        r = session.get(f"{base}/stellenangebote", timeout=15)
        if r.status_code != 200:
            log.warning(f"[Silver Atena] HTTP {r.status_code}")
            return []
        soup = BeautifulSoup(r.text, "lxml")
        seen = set()
        for tr in soup.select("tr"):
            a = tr.find("a", href=re.compile(r"/stellenangebote/"))
            tds = tr.find_all("td")
            if not a or len(tds) < 3:
                continue
            href = a.get("href", "")
            # Werkstudenten/Praktika über Kategorie-Pfad ausschließen
            if any(x in href.lower() for x in ["/studenten", "/praktik", "/werkstud"]):
                continue
            url = href if href.startswith("http") else base + href
            if url in seen:
                continue
            seen.add(url)
            title = a.get_text(" ", strip=True)
            loc = tds[-1].get_text(" ", strip=True)
            if not title:
                continue
            jobs.append({"source": "silver-atena", "url": url, "title": title[:200],
                         "company": "Silver Atena", "location": loc or "München",
                         "description": "", "raw_text": title})
    except Exception as e:
        log.warning(f"[Silver Atena] {e}")
    log.info(f"[Silver Atena] {len(jobs)} Jobs")
    return jobs


# ---- Workday (generisch, POST) ----
def crawl_workday(session, tenant, wd, site, company, search="München") -> list:
    """Generischer Workday-Crawler. Workday liefert global → searchText (Standort) serverseitig;
    location_passes filtert zusätzlich hart."""
    log.info(f"[{company}] Workday…")
    jobs = []
    url = f"https://{tenant}.wd{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    hdrs = {"Content-Type": "application/json", "Accept": "application/json"}
    try:
        offset = 0
        while offset < 160:
            r = session.post(url, timeout=15, headers=hdrs,
                             json={"limit": 20, "offset": offset, "searchText": search})
            if r.status_code != 200:
                break
            posts = r.json().get("jobPostings", [])
            if not posts:
                break
            for p in posts:
                title = p.get("title", "")
                path = p.get("externalPath", "")
                if not title or not path:
                    continue
                jobs.append({"source": f"workday:{company}",
                             "url": f"https://{tenant}.wd{wd}.myworkdayjobs.com{path}",
                             "title": title[:200], "company": company,
                             "location": p.get("locationsText", "") or "", "description": "",
                             "raw_text": title})
            if len(posts) < 20:
                break
            offset += 20
            time.sleep(0.2)
    except Exception as e:
        log.warning(f"[{company}] {e}")
    log.info(f"[{company}] {len(jobs)} Jobs (Workday)")
    return jobs


def crawl_zeiss_meditec(session) -> list:
    return crawl_workday(session, "zeissgroup", 3, "External", "Carl Zeiss Meditec", "München")


# ---- SuccessFactors-Sitemap-Wrapper (neue München-Firmen) ----
def crawl_kuka(session) -> list:
    return crawl_successfactors_sitemap(session, "jobs.kuka.com", "KUKA",
                                        r"/job/(M[üu]nchen|Augsburg)")
def crawl_gore(session) -> list:
    return crawl_successfactors_sitemap(session, "wlgore.jobs.hr.cloud.sap", "W. L. Gore",
                                        r"(Putzbrunn|M[üu]nchen)")
def crawl_gd(session) -> list:
    return crawl_successfactors_sitemap(session, "careers.gi-de.com", "Giesecke+Devrient",
                                        r"/job/(M[üu]nchen|Munich)")
def crawl_kraussmaffei(session) -> list:
    return crawl_successfactors_sitemap(session, "jobs.kraussmaffei.com", "KraussMaffei",
                                        r"/job/(Parsdorf|M[üu]nchen)")
def crawl_amsosram(session) -> list:
    return crawl_successfactors_sitemap(session, "jobs.ams-osram.com", "ams OSRAM",
                                        r"(M[üu]nchen|Munich)")


# ---- Infineon (Eightfold PCSX) ----
def crawl_infineon(session) -> list:
    log.info("[Infineon] Eightfold PCSX…")
    jobs = []
    hdrs = {**HEADERS, "Referer": "https://jobs.infineon.com/careers", "Accept": "application/json"}
    try:
        start = 0
        while start < 300:
            url = ("https://jobs.infineon.com/api/pcsx/search?domain=infineon.com"
                   f"&start={start}&num=100&location=Munich%2C%20Germany"
                   "&sort_by=distance&filter_distance=40")
            r = session.get(url, headers=hdrs, timeout=15)
            if r.status_code != 200:
                break
            data = r.json()
            positions = data.get("positions") or (data.get("data") or {}).get("positions") or []
            if not positions:
                break
            for p in positions:
                title = p.get("name", "")
                purl = p.get("positionUrl", "") or p.get("canonicalPositionUrl", "")
                locs = p.get("locations", []) or []
                loc = ", ".join(locs) if isinstance(locs, list) else str(locs)
                full = purl if str(purl).startswith("http") else f"https://jobs.infineon.com{purl}"
                if not title:
                    continue
                jobs.append({"source": "infineon", "url": full, "title": title[:200],
                             "company": "Infineon Technologies", "location": loc or "München",
                             "description": "", "raw_text": title})
            if len(positions) < 100:
                break
            start += 100
            time.sleep(0.3)
    except Exception as e:
        log.warning(f"[Infineon] {e}")
    log.info(f"[Infineon] {len(jobs)} Jobs")
    return jobs


# ---- Allianz (Phenom People POST) ----
def crawl_allianz(session) -> list:
    log.info("[Allianz] Phenom…")
    jobs = []
    body = {"lang": "en_global", "deviceType": "desktop", "country": "global",
            "pageName": "search-results", "ddoKey": "refineSearch", "from": 0, "jobs": True,
            "counts": True, "all_fields": ["country", "state", "city", "category"],
            "size": 100, "keywords": "", "global": True,
            "selected_fields": {"city": ["München"]}}
    try:
        r = session.post("https://careers.allianz.com/widgets", json=body, timeout=15,
                         headers={"Content-Type": "application/json", "Accept": "application/json"})
        if r.status_code == 200:
            joblist = (((r.json().get("refineSearch") or {}).get("data") or {}).get("jobs")) or []
            for p in joblist:
                title = p.get("title", "")
                url = p.get("applyUrl") or p.get("jobUrl") or p.get("url", "")
                if not title:
                    continue
                jobs.append({"source": "allianz", "url": url, "title": title[:200],
                             "company": "Allianz", "location": p.get("city", "") or "München",
                             "description": "", "raw_text": title})
    except Exception as e:
        log.warning(f"[Allianz] {e}")
    log.info(f"[Allianz] {len(jobs)} Jobs")
    return jobs


# ============================================================
# Avature-Portale (NEU 2026-06-11, Andy "SPA-Quellen fertigmachen")
# Avature rendert SearchJobs server-seitig; der /feed/-Endpoint liefert mit
# jobRecordsPerPage=100 alle Treffer in EINEM Request (verifiziert R&S: 40
# Muenchen-Jobs, 9.7kB). Kein Browser noetig. Siemens nutzt zwar auch Avature,
# rendert die Liste aber client-seitig -> separater Schritt (Netzwerk-API).
# ============================================================
AVATURE_SOURCES = [
    ("Rohde & Schwarz",
     "https://jobs.rohde-schwarz.com/en_US/careers/SearchJobs/Munich/feed/?jobRecordsPerPage=100",
     "München"),
]


def crawl_avature(session) -> list:
    """Der /feed/-Endpoint liefert RSS 2.0: <item> mit <title><![CDATA[..]]> + <link>.
    20 Items je Seite, Pagination via jobOffset."""
    log.info("[Avature] SearchJobs-RSS-Feeds…")
    jobs, seen = [], set()
    item_pat = re.compile(
        r"<item>[\s\S]*?<title><!\[CDATA\[(.*?)\]\]></title>[\s\S]*?<link>([^<]+)</link>", re.I)
    for company, url, loc in AVATURE_SOURCES:
        cnt = 0
        for offset in (0, 20, 40, 60):
            try:
                r = session.get(f"{url}&jobOffset={offset}", timeout=15)
                if r.status_code != 200:
                    break
                found = item_pat.findall(r.text)
                if not found:
                    break
                new_here = 0
                for title, href in found:
                    href = href.strip().split("?")[0]
                    title = re.sub(r"\s+", " ", title).strip()
                    if not href or href in seen or len(title) < 8:
                        continue
                    seen.add(href)
                    cnt += 1
                    new_here += 1
                    jobs.append({"source": f"avature:{company}", "url": href,
                                 "title": title[:200], "company": company,
                                 "location": loc, "description": "", "raw_text": title})
                if new_here == 0:
                    break
            except Exception as e:
                log.warning(f"[Avature:{company}] {e}")
                break
        log.info(f"[Avature:{company}] {cnt} Jobs")
    log.info(f"[Avature] {len(jobs)} Jobs gesamt")
    return jobs


# ============================================================
# NEURA Robotics (NEU 2026-06-11, Andy: "Mega-Investment, schreibt jetzt
# Muenchen aus — wieso nicht im Dashboard?!")
# Historie: Personio-Board war 06/2026 ein totes Testboard -> Firma hat jetzt
# eigenes Portal jobs.neura-robotics.com (my-job-shop.com/Nuxt + Typesense).
# Weg: sitemap.xml (179 Offer-URLs) + <title> der Detailseite traegt
# "Titel (Stadt) > NEURA Robotics" -> nur ~4kB je Stelle noetig (Stream-Abbruch).
# ============================================================
def crawl_neura(session) -> list:
    log.info("[NEURA] Sitemap + Titel-Snippets…")
    jobs = []
    try:
        r = session.get("https://jobs.neura-robotics.com/sitemap.xml", timeout=15)
        urls = re.findall(r"<loc>(https://jobs\.neura-robotics\.com/offer/[^<]+)</loc>", r.text)
    except Exception as e:
        log.warning(f"[NEURA] Sitemap: {e}")
        return jobs
    log.info(f"[NEURA] {len(urls)} Offer-URLs in Sitemap")
    muc = 0
    for url in urls[:220]:
        try:
            resp = session.get(url, stream=True, timeout=10)
            head = b""
            for chunk in resp.iter_content(chunk_size=2048):
                head += chunk
                if b"</title>" in head or len(head) > 30000:
                    break
            resp.close()
            m = re.search(rb"<title>([^<]+)</title>", head)
            if not m:
                continue
            full = m.group(1).decode("utf-8", "replace").strip()
            # "Concept Engineer (Mensch) (Muenchen) > NEURA Robotics"
            title = re.sub(r"\s*[›>|].*$", "", full).strip()
            cm = re.findall(r"\(([^()]+)\)", title)
            city = cm[-1].strip() if cm else ""
            if not re.search(r"m(ü|u|ue)nchen|munich", city, re.I):
                continue
            clean_title = re.sub(r"\s*\(" + re.escape(city) + r"\)\s*$", "", title).strip()
            clean_title = clean_title.replace("&amp;", "&").replace("&#39;", "'")
            muc += 1
            jobs.append({"source": "neura", "url": url, "title": clean_title[:200],
                         "company": "NEURA Robotics", "location": "München",
                         "description": "", "raw_text": clean_title})
        except Exception:
            continue
    log.info(f"[NEURA] {muc} München-Jobs (von {len(urls)} gesamt)")
    return jobs


# ============================================================
# Job-Portale (NEU 2026-06-01, ATS-Recherche verifiziert)
# ============================================================
PORTAL_QUERIES = ["Projektmanager", "Projektleiter", "Teilprojektleiter",
                  "Produktentwicklung", "technischer Projektleiter", "KI Manager"]


def crawl_xing(session) -> list:
    """Xing Jobs — server-seitiges inline-JSON im HTML (kein Key, Gehalt inklusive)."""
    log.info("[Xing] Jobs…")
    jobs, seen = [], set()
    for q in PORTAL_QUERIES:
        for page in (1, 2):
            url = (f"https://www.xing.com/jobs/search/ki?keywords={requests.utils.quote(q)}"
                   f"&location=M%C3%BCnchen&radius=25&page={page}")
            try:
                r = session.get(url, timeout=15)
                if r.status_code != 200:
                    break
                txt = r.text.replace("\\u002F", "/")
                for m in re.finditer(r'"url":"(https://www\.xing\.com/jobs/[^"]+)"', txt):
                    jurl = m.group(1).split("?")[0]
                    if jurl in seen:
                        continue
                    seen.add(jurl)
                    ctx = txt[max(0, m.start() - 700):m.start() + 700]
                    tm = re.search(r'"title":"([^"]{4,140})"', ctx)
                    cm = (re.search(r'"companyNameOverride":"([^"]{2,80})"', ctx)
                          or re.search(r'"companyName":"([^"]{2,80})"', ctx))
                    lm = re.search(r'"city":"([^"]{2,60})"', ctx)
                    if not tm:
                        continue
                    jobs.append({"source": "xing", "url": jurl, "title": tm.group(1)[:200],
                                 "company": (cm.group(1) if cm else ""),
                                 "location": (lm.group(1) if lm else "München"),
                                 "description": "", "raw_text": tm.group(1)})
                time.sleep(0.4)
            except Exception as e:
                log.debug(f"[Xing] {q} p{page}: {e}")
    log.info(f"[Xing] {len(jobs)} Jobs")
    return jobs


def crawl_talent(session) -> list:
    """talent.com — HTML-Cards mit gehashten CSS-Modulen (Substring-Selektoren)."""
    log.info("[talent.com] Jobs…")
    jobs, seen = [], set()
    for q in PORTAL_QUERIES:
        url = f"https://de.talent.com/jobs?k={requests.utils.quote(q)}&l=M%C3%BCnchen"
        try:
            r = session.get(url, timeout=15)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "lxml")
            for card in soup.select('[class*="JobCard_card__"]'):
                t = card.select_one('[class*="JobCard_title__"]')
                a = card.find("a", href=re.compile(r"/view\?id="))
                if not t:
                    continue
                href = a.get("href", "") if a else ""
                full = ("https://de.talent.com" + href) if href.startswith("/") else href
                if not full or full in seen:
                    continue
                seen.add(full)
                co = card.select_one('[class*="JobCard_company__"]')
                lo = card.select_one('[class*="JobCard_location__"]')
                jobs.append({"source": "talent", "url": full.split("?id=")[0] + "?id=" + full.split("id=")[-1],
                             "title": t.get_text(" ", strip=True)[:200],
                             "company": (co.get_text(" ", strip=True) if co else ""),
                             "location": (lo.get_text(" ", strip=True) if lo else "München"),
                             "description": "", "raw_text": t.get_text(" ", strip=True)})
            time.sleep(0.4)
        except Exception as e:
            log.debug(f"[talent] {q}: {e}")
    log.info(f"[talent.com] {len(jobs)} Jobs")
    return jobs


def crawl_jobrapido(session) -> list:
    """jobrapido.de — HTML-Cards (Firma fehlt oft)."""
    log.info("[jobrapido] Jobs…")
    jobs, seen = [], set()
    for q in PORTAL_QUERIES:
        url = f"https://de.jobrapido.com/?w={requests.utils.quote(q)}&l=M%C3%BCnchen"
        try:
            r = session.get(url, timeout=15)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "lxml")
            for card in soup.select(".result-item__wrapper"):
                tl = card.select_one('[class*="result-item__title"]')
                a = card.find("a", href=True)
                if not tl or not a:
                    continue
                href = a.get("href", "")
                if not href.startswith("http") or href in seen:
                    continue
                seen.add(href)
                lo = card.select_one(".result-item__location")
                jobs.append({"source": "jobrapido", "url": href.split("?")[0],
                             "title": tl.get_text(" ", strip=True)[:200], "company": "",
                             "location": (lo.get_text(" ", strip=True) if lo else "München"),
                             "description": "", "raw_text": tl.get_text(" ", strip=True)})
            time.sleep(0.4)
        except Exception as e:
            log.debug(f"[jobrapido] {q}: {e}")
    log.info(f"[jobrapido] {len(jobs)} Jobs")
    return jobs


def crawl_whatjobs(session) -> list:
    """whatjobs.de — HTML-Cards (Firma als URL-Slug)."""
    log.info("[whatjobs] Jobs…")
    jobs, seen = [], set()
    for q in PORTAL_QUERIES:
        url = f"https://de.whatjobs.com/jobs/{requests.utils.quote(q)}/M%C3%BCnchen"
        try:
            r = session.get(url, timeout=15)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "lxml")
            for card in soup.select('div[class*="jobCard"]'):
                h = card.find(["h2", "h3"])
                a = card.find("a", href=True)
                if not h or not a:
                    continue
                href = a.get("href", "")
                full = href if href.startswith("http") else "https://de.whatjobs.com" + href
                if full in seen:
                    continue
                seen.add(full)
                jobs.append({"source": "whatjobs", "url": full.split("?")[0],
                             "title": h.get_text(" ", strip=True)[:200], "company": "",
                             "location": "München", "description": "",
                             "raw_text": h.get_text(" ", strip=True)})
            time.sleep(0.4)
        except Exception as e:
            log.debug(f"[whatjobs] {q}: {e}")
    log.info(f"[whatjobs] {len(jobs)} Jobs")
    return jobs


def crawl_germantechjobs(session) -> list:
    """germantechjobs.de — RSS-Feed, Titel-Format 'Rolle @ Firma [Gehalt]'. Nur München-Bezug."""
    log.info("[germantechjobs] RSS…")
    jobs = []
    try:
        r = session.get("https://germantechjobs.de/rss", timeout=30)
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.text)
        for item in root.findall(".//item"):
            title_raw = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            desc = (item.findtext("description") or "")[:600]
            if not title_raw or not link:
                continue
            blob = (title_raw + " " + desc).lower()
            if "münchen" not in blob and "munich" not in blob:
                continue
            company, title = "", title_raw
            if " @ " in title_raw:
                title, rest = title_raw.split(" @ ", 1)
                company = rest.split("[")[0].strip()
            jobs.append({"source": "germantechjobs", "url": link.split("?")[0],
                         "title": title.strip()[:200], "company": company,
                         "location": "München", "description": desc, "raw_text": title})
    except Exception as e:
        log.warning(f"[germantechjobs] {e}")
    log.info(f"[germantechjobs] {len(jobs)} Jobs")
    return jobs


# ---- Automotive OEM / Tier1 (SuccessFactors-Sitemap + Workday + Jobbase) ----
def crawl_bmw(session) -> list:
    return crawl_successfactors_sitemap(session, "jobs.bmwgroup.com", "BMW Group", r"/job/M[üu]nchen")
def crawl_bertrandt(session) -> list:
    return crawl_successfactors_sitemap(session, "bertrandt.jobs.hr.cloud.sap", "Bertrandt",
                                        r"/job/(M[üu]nchen|Muenchen|Taufkirchen)")
def crawl_capgemini_eng(session) -> list:
    return crawl_successfactors_sitemap(session, "careers.capgemini.com", "Capgemini",
                                        r"/job/(M[üu]nchen|Muenchen)")
def crawl_schaeffler(session) -> list:
    return crawl_successfactors_sitemap(session, "jobs.schaeffler.com", "Schaeffler",
                                        r"/job/(M[üu]nchen|Muenchen)")
def crawl_zf(session) -> list:
    return crawl_successfactors_sitemap(session, "jobs.zf.com", "ZF", r"/job/(M[üu]nchen|Muenchen)")
def crawl_avl(session) -> list:
    return crawl_successfactors_sitemap(session, "jobs.avl.com", "AVL", r"/job/(M[üu]nchen|Muenchen)")
def crawl_vitesco(session) -> list:
    return crawl_successfactors_sitemap(session, "jobs.vitesco-technologies.com", "Vitesco",
                                        r"/job/(M[üu]nchen|Muenchen)")
def crawl_valeo(session) -> list:
    return crawl_workday(session, "valeo", 3, "valeo_jobs", "Valeo", "München")


def crawl_arrk(session) -> list:
    """ARRK Engineering — Jobbase AJAX-Liste (HTML-Fragment, kein JSON). Nur München-Treffer."""
    log.info("[ARRK] Jobbase…")
    jobs, seen = [], set()
    try:
        hdrs = {**HEADERS, "X-Requested-With": "XMLHttpRequest"}
        for page in range(1, 4):
            url = ("https://arrkeurope.jobbase.io/candidate/job/ajax_list?"
                   f"display_length=100&page={page}&sort=date&sort_dir=DESC&search=")
            r = session.get(url, headers=hdrs, timeout=15)
            if r.status_code != 200:
                break
            soup = BeautifulSoup(r.text, "lxml")
            links = soup.select('a[href*="/job/"]')
            if not links:
                break
            added = 0
            for a in links:
                href = a.get("href", "")
                full = href if href.startswith("http") else "https://arrkeurope.jobbase.io" + href
                if full in seen:
                    continue
                seen.add(full)
                title = a.get_text(" ", strip=True)
                if not title or len(title) < 5:
                    continue
                parent = a.find_parent("tr") or a.find_parent("div") or a
                ptext = parent.get_text(" ", strip=True).lower()
                if "münchen" not in ptext and "munich" not in ptext:
                    continue
                jobs.append({"source": "arrk", "url": full, "title": title[:200],
                             "company": "ARRK Engineering", "location": "München",
                             "description": "", "raw_text": title})
                added += 1
            if added == 0:
                break
            time.sleep(0.3)
    except Exception as e:
        log.warning(f"[ARRK] {e}")
    log.info(f"[ARRK] {len(jobs)} Jobs")
    return jobs


# ============================================================
# NEU 2026-06-02: Yourfirm (KMU-Mittelstand München, server-rendered, ?page=N-Paginierung)
# Stadt-Filter via /stellenangebote/muenchen/, Keyword-Filter macht der lokale score_job.
# ============================================================
def crawl_yourfirm(session) -> list:
    # NEU 2026-06-02: gezielte Keyword-Suche (?q=) statt wahlloser Stadt-Liste.
    # Die nackte /muenchen/-Liste lieferte 148 Zufalls-Jobs aller Branchen (0 PM-Treffer).
    # ?q=Projektmanager etc. liefert direkt Andys Cluster.
    log.info("[Yourfirm] Jobs…")
    jobs, seen = [], set()
    base = "https://www.yourfirm.de"
    for q in PORTAL_QUERIES:
        for page in range(1, 4):
            url = f"{base}/stellenangebote/muenchen/?q={requests.utils.quote(q)}"
            if page > 1:
                url += f"&page={page}"
            try:
                r = session.get(url, timeout=15)
                if r.status_code != 200:
                    break
                soup = BeautifulSoup(r.text, "lxml")
                added = 0
                for a in soup.select('a[href^="/job/"]'):
                    href = a.get("href", "").split("?")[0]
                    title = a.get_text(" ", strip=True)
                    if not title or len(title) < 4:
                        continue
                    full = base + href
                    if full in seen:
                        continue
                    seen.add(full)
                    parts = href.strip("/").split("/")
                    firma = ""
                    if len(parts) > 1:
                        firma = re.sub(r"-(gmbh|co-kg|kg|ag|se|mbh|und|co)\b", " ", parts[1]).replace("-", " ").strip().title()
                    jobs.append({"source": "yourfirm", "url": full, "title": title[:200],
                                 "company": firma[:80], "location": "München", "description": "",
                                 "raw_text": title})
                    added += 1
                if added == 0:
                    break
                time.sleep(0.3)
            except Exception as e:
                log.warning(f"[Yourfirm] {e}")
                break
    log.info(f"[Yourfirm] {len(jobs)} Jobs")
    return jobs


# ============================================================
# NEU 2026-06-02: remotely.de (deutsche Remote-Jobbörse, eigener Bestand).
# Detailseiten bot-geblockt (requests sieht "nicht mehr verfügbar"), ABER im echten Browser live
# (verifiziert). Listen + Sitemap gehen mit requests. Darum: Sitemap-Slugs lesen, Titel daraus,
# location=Remote, und remotely.de in SPA_DOMAINS → verify_url akzeptiert ohne expired-Check.
# ============================================================
def crawl_remotely(session) -> list:
    log.info("[remotely.de] Jobs…")
    jobs = []
    try:
        r = session.get("https://www.remotely.de/sitemap-jobs.xml", timeout=25)
        locs = re.findall(r"<loc>(.*?)</loc>", r.text)
    except Exception as e:
        log.warning(f"[remotely.de] Sitemap: {e}")
        return []
    PM = ["-projektmanager", "-projektleiter", "-project-manager", "-program-manager",
          "-programm-manager", "-teilprojektleiter", "-pmo-", "-ki-manager", "-ai-project",
          "-ai-program", "-prozessmanager", "-technical-project", "-senior-project",
          "-it-projektleit", "-it-projektmanager", "-projekt-manager", "-portfolio-manager",
          "-produktmanager"]
    cand = []
    for l in locs:
        if not any(k in l.lower() for k in PM):
            continue
        slug = l.rstrip("/").split("/job/")[-1]
        title = re.sub(r"-(mwd|m-w-d|wmd|w-m-d|all-genders|fully-remote|remote|deutschlandweit|"
                       r"homeoffice|m-f-d|mfd|gn|divers)\b.*$", "", slug).replace("-", " ").strip()
        sc, _ = score_job(title, "", "Remote Deutschland", "")
        if sc >= 30:
            cand.append((sc, title, l))
    cand.sort(key=lambda x: x[0], reverse=True)
    seen_keys = set()
    for sc, title, l in cand:
        # Dedup nach Kern-Titel: remotely.de listet denselben Job doppelt (mit/ohne Rechtsform
        # im Firmen-Slug, z.B. "stur ..." und "stur gmbh ...").
        key = re.sub(r'[^a-z0-9]', '',
                     re.sub(r'\b(gmbh|ag|se|kg|co|mbh|kgaa|ohg|initiative|group|holding|deutschland)\b',
                            '', title.lower()))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        jobs.append({"source": "remotely", "url": l, "title": title[:200], "company": "",
                     "location": "Remote Deutschland", "description": "", "raw_text": title})
        if len(jobs) >= 150:
            break
    log.info(f"[remotely.de] {len(jobs)} Jobs (aus {len(locs)} Sitemap-URLs, Score>=30, Top-150)")
    return jobs


# ============================================================
# NEU 2026-06-02: jobninja.com (server-rendered, Firma+Standort ausgezeichnet).
# München-Suche zeigt auch deutschlandweit → nur München/Remote-Standort behalten.
# ============================================================
def crawl_jobninja(session) -> list:
    log.info("[jobninja] Jobs…")
    jobs, seen = [], set()
    base = "https://www.jobninja.com"
    for q in PORTAL_QUERIES:
        url = f"{base}/search?keywords={requests.utils.quote(q)}&location=M%C3%BCnchen"
        try:
            r = session.get(url, timeout=15)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "lxml")
            for a in soup.select('a[href*="/jobs/"]'):
                href = a.get("href", "").split("?")[0]
                if not href.startswith("/jobs/"):
                    continue
                full = base + href
                if full in seen:
                    continue
                card = a.find_parent(['article', 'li', 'div'])
                if not card:
                    continue
                loc_el = card.select_one('[class*="location"]')
                loc = loc_el.get_text(" ", strip=True) if loc_el else ""
                if not re.search(r'münchen|munich|remote|homeoffice|home office', loc, re.I):
                    continue
                seen.add(full)
                co_el = card.select_one('[class*="company"]')
                company = co_el.get_text(" ", strip=True) if co_el else ""
                slug = href.split("/jobs/")[-1]
                title = re.sub(r'-+\d+$', '', slug)
                title = re.sub(r'-(m-w-d|mwd|in)$', '', title).replace("-", " ").strip()
                jobs.append({"source": "jobninja", "url": full, "title": title[:200],
                             "company": company[:80], "location": loc[:80] or "München",
                             "description": "", "raw_text": title})
        except Exception as e:
            log.debug(f"[jobninja] {q}: {e}")
        time.sleep(0.3)
    log.info(f"[jobninja] {len(jobs)} Jobs")
    return jobs


# ============================================================
# Main
# ============================================================
def main():
    started = datetime.now()
    log.info(f"=== Crawl v4 gestartet {started.isoformat()} ===")
    s = make_session()
    all_jobs = []
    sources_session = [
        (crawl_akkodis, "Akkodis"),
        (crawl_arbeitnow, "arbeitnow"),
        (crawl_personio, "Personio"),
        (crawl_greenhouse, "Greenhouse"),
        (crawl_lever, "Lever"),
        (crawl_ashby, "Ashby"),
        (crawl_workable, "Workable"),
        (crawl_recruitee, "Recruitee"),
        (crawl_smartrecruiters, "SmartRecruiters"),
        (crawl_bundesagentur, "Bundesagentur (API)"),
        (crawl_stepstone, "StepStone"),
        (crawl_szjobs, "sz-jobs.de"),
        (crawl_kimeta, "kimeta.de"),
        (crawl_jobvector, "jobvector"),
        (crawl_linkedin, "LinkedIn (anonymous)"),
        (crawl_remoteok, "RemoteOK"),
        (crawl_remotive, "Remotive"),
        (crawl_weworkremotely, "WeWorkRemotely"),
        (crawl_edag_karriere, "EDAG-Karriere"),
        (crawl_cognizant_mobility, "Cognizant-Mobility"),
        # NEU 2026-05-28 (Andy explizit):
        (crawl_sii_group, "SII Group"),
        (crawl_rodenstock, "Rodenstock"),
        (crawl_cariad, "CARIAD"),
        (crawl_mtu, "MTU Aero Engines"),
        # NEU 2026-06-01 (Andy God-Mode: Top-Treffer-Firmen als Direkt-Quellen, ATS-verifiziert)
        (crawl_fev, "FEV"),
        (crawl_suss, "SÜSS MicroTec"),
        (crawl_man, "MAN Truck & Bus"),
        (crawl_webasto, "Webasto"),
        (crawl_knorr, "Knorr-Bremse"),
        (crawl_silver_atena, "Silver Atena"),
        # NEU 2026-06-01 Phase 2 (Robotik/MedTech/Tech/Industrie München, ATS-verifiziert)
        (crawl_zeiss_meditec, "Carl Zeiss Meditec"),
        (crawl_kuka, "KUKA"),
        (crawl_gore, "W. L. Gore"),
        (crawl_gd, "Giesecke+Devrient"),
        (crawl_kraussmaffei, "KraussMaffei"),
        (crawl_amsosram, "ams OSRAM"),
        (crawl_infineon, "Infineon"),
        (crawl_allianz, "Allianz"),
        (crawl_avature, "Avature (Rohde & Schwarz)"),
        (crawl_neura, "NEURA Robotics"),
        # NEU 2026-06-01 Phase 2 (Job-Portale, keyfrei)
        (crawl_xing, "Xing"),
        (crawl_talent, "talent.com"),
        (crawl_jobrapido, "jobrapido"),
        (crawl_whatjobs, "whatjobs"),
        (crawl_germantechjobs, "germantechjobs"),
        # NEU 2026-06-01 Phase 3 (Automotive OEM/Tier1 München, ATS-verifiziert; BMW = 482 MUC!)
        (crawl_bmw, "BMW Group"),
        (crawl_bertrandt, "Bertrandt"),
        (crawl_capgemini_eng, "Capgemini Engineering"),
        (crawl_schaeffler, "Schaeffler"),
        (crawl_zf, "ZF"),
        (crawl_avl, "AVL"),
        (crawl_vitesco, "Vitesco"),
        (crawl_valeo, "Valeo"),
        (crawl_arrk, "ARRK Engineering"),
        # NEU 2026-06-02 (Andy Voll-Ausbau): KMU-Mittelstand-Portal München
        (crawl_yourfirm, "Yourfirm"),
        # NEU 2026-06-02: deutsche Remote-Jobbörse (eigener Bestand, Sitemap-basiert)
        (crawl_remotely, "remotely.de"),
        # NEU 2026-06-02: jobninja.com (server-rendered, München/Remote-gefiltert)
        (crawl_jobninja, "jobninja.com"),
    ]
    sources_no_session = [
        (crawl_indeed_playwright, "Indeed (Playwright)"),
        (crawl_pw_companies, "PW-Firmen (Apple/Siemens/Brose/IAV/ALTEN…)"),
    ]
    source_names = []
    for fn, name in sources_session:
        try:
            all_jobs.extend(fn(s))
        except Exception as e:
            log.error(f"[{name}] Fehler: {e}")
        source_names.append(name)
    for fn, name in sources_no_session:
        try:
            all_jobs.extend(fn())
        except Exception as e:
            log.error(f"[{name}] Fehler: {e}")
        source_names.append(name)

    filtered = apply_filter(all_jobs)
    verified = parallel_verify(filtered, s, max_workers=10)
    # NEU 2026-06-01: Nach JSON-LD-Verifikation steht die Firma oft erst sauber in clean_company
    # (beim Filter war company leer, z.B. StepStone). Blacklist erneut gegen clean_company prüfen,
    # damit Deutsche Bahn / Drees & Sommer / Strabag etc. auch dann rausfliegen, wenn ihr Name
    # erst aus der Detailseite kam.
    before_recheck = len(verified)
    verified = [j for j in verified
                if score_job(j.get("title", ""),
                             j.get("description", ""),
                             j.get("location", ""),
                             j.get("clean_company") or j.get("company") or "")[0] >= 0]
    if before_recheck != len(verified):
        log.info(f"  → clean_company-Recheck: {before_recheck - len(verified)} nachträglich geblockt")

    # NEU 2026-06-03: Manuelle Stellen (HRworks/JS-Portale, die kein Crawler erreicht) mergen.
    # Sie durchlaufen NICHT score_job (sonst ggf. geblockt), werden aber dedupe-sicher per URL
    # angehängt und wie Crawler-Jobs sortiert/angezeigt ("manual":true-Flag fürs Frontend).
    manual = load_manual_jobs()
    if manual:
        existing_urls = {j.get("url") for j in verified}
        added = [m for m in manual if m["url"] not in existing_urls]
        verified.extend(added)
        verified.sort(key=lambda x: (x.get("first_seen") or "", x.get("score") or 0), reverse=True)
        log.info(f"  → {len(added)}/{len(manual)} manuelle Stellen gemergt")

    payload = {
        "generated_at": started.isoformat(),
        "duration_s": (datetime.now() - started).total_seconds(),
        "stats": {
            "raw": len(all_jobs),
            "filtered": len(filtered),
            "verified": len(verified),
            "by_category": {},
            "sources": source_names,
        },
        "jobs": [{k: v for k, v in j.items() if k != "raw_text"} for j in verified],
    }
    for j in verified:
        c = j.get("category", "other")
        payload["stats"]["by_category"][c] = payload["stats"]["by_category"].get(c, 0) + 1

    DATA_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    DATA_JS = BASE / "data.js"
    data_js = "window.JOBSUCHE_DATA = " + json.dumps(payload, ensure_ascii=False) + ";\n"
    DATA_JS.write_text(data_js, encoding="utf-8")

    HTML_SRC = BASE / "jobsuche_v12.html"
    if HTML_SRC.exists():
        html = HTML_SRC.read_text(encoding="utf-8")
        inline = '<script>' + data_js + '</script>'
        html_inline = html.replace('<script src="data.js"></script>', inline)
        (BASE / "jobsuche_standalone.html").write_text(html_inline, encoding="utf-8")
        (BASE / "index.html").write_text(html, encoding="utf-8")
        ICLOUD = (Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/Jobsuche")
        if ICLOUD.parent.exists():
            ICLOUD.mkdir(exist_ok=True)
            (ICLOUD / "jobsuche_standalone.html").write_text(html_inline, encoding="utf-8")
            log.info(f"iCloud: {ICLOUD}/jobsuche_standalone.html")

    log.info(f"=== Crawl v4 fertig: {len(verified)} Jobs ===")
    log.info(f"Dauer: {payload['duration_s']:.1f}s · Kategorien: {payload['stats']['by_category']}")


if __name__ == "__main__":
    main()
