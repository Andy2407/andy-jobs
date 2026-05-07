#!/usr/bin/env python3
"""Andy's Jobsuche-Crawler v3 — LinkedIn anonymous + kimeta-fix + BA-API.

Quellen (16):
- Akkodis Sitemap
- arbeitnow.com API (paginated)
- Personio-Subdomains (42 Firmen)
- Greenhouse JSON-API (46 DE-Tech)
- Lever JSON-API (8)
- Ashby JSON-API (8)
- Workable / Recruitee JSON-API
- SmartRecruiters Public-API (8 Companies, Bosch+Brainlab)
- Bundesagentur JSON-API (offiziell, mit X-API-Key)
- StepStone HTML-Suche (21 Queries)
- sz-jobs.de HTML-Suche (München-Schwerpunkt)
- kimeta.de HTML-Suche (Aggregator, 1168+ München-Treffer)
- jobvector HTML-Suche (MINT)
- LinkedIn Anonymous-Search (/jobs-guest/.../seeMoreJobPostings)

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
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup

from profile import score_job, categorize, clean_title, MIN_SCORE_TO_INCLUDE

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
    ("agilerobots", "Agile Robots", None),
    ("kinexon", "Kinexon", None), ("konux-gmbh", "KONUX", None),
    ("luminovo", "Luminovo", None), ("logivations", "Logivations", None),
    ("kaeser-kompressoren", "KAESER", None),
    ("mep-werke", "MEP Werke", None), ("trumpf", "TRUMPF", None),
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
# Greenhouse (46 DE-Tech)
# ============================================================
GREENHOUSE_COMPANIES = [
    "celonis", "n26", "traderepublic", "sennder", "gostudent", "pitch",
    "taxfix", "raisin", "mambu", "contentful", "awin", "infarm",
    "choco", "tier", "tiermobility", "lightyear", "omio", "klarna",
    "scalable", "scalablecapital", "getyourguide", "idagio", "blinkist",
    "remotecom", "zalando", "hellofresh", "deliveryhero", "sumup",
    "openai", "anthropic", "stripe", "scaleai", "elevenlabs",
    "perplexityai", "huggingface", "stabilityai", "neon", "supabase",
    "vercel", "linear", "notion", "applied-intuition", "anduril",
    "joby", "wayve", "cohere",
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
# Lever
# ============================================================
LEVER_COMPANIES = ["munichelectrification", "intersystems", "vehicle", "spacex",
                   "palantir", "freenome", "anthropic", "openai"]


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


# ============================================================
# Ashby
# ============================================================
ASHBY_COMPANIES = ["anthropic", "openai", "elevenlabs", "anysphere",
                   "perplexity", "mistral", "stabilityai", "weaviate"]


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


# ============================================================
# Workable
# ============================================================
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


# ============================================================
# Recruitee
# ============================================================
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


# ============================================================
# SmartRecruiters Public-API (Bosch & Co.)
# ============================================================
SMARTRECRUITERS_COMPANIES = [
    "BoschGroup", "Bosch-HomeComfort", "Brainlab", "Vattenfall",
    "MiltenyiBiotec", "SIXT",
    "REWEInternationalDienstleistungsgesellschaftmbH",
    "DiscoverDeloitte",
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
# Bundesagentur — offizielle JSON-API mit X-API-Key (NEU v3)
# ============================================================
BA_API_QUERIES = [
    {"was": "KI Manager"},
    {"was": "AI Project Manager"},
    {"was": "AI Manager"},
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
    {"was": "Senior Consultant", "wo": "München", "umkreis": "25"},
    {"was": "Agile Projektmanager", "wo": "München", "umkreis": "25"},
    {"was": "Scrum Master", "wo": "München", "umkreis": "25"},
    {"was": "Product Owner", "wo": "München", "umkreis": "25"},
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
    log.info(f"[Bundesagentur] {len(jobs)} (über {len(BA_API_QUERIES)} API-Suchen)")
    return jobs


# ============================================================
# StepStone HTML-Suche
# ============================================================
STEPSTONE_QUERIES = [
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
# sz-jobs.de — Süddeutsche Stellenmarkt
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
# kimeta.de — Aggregator (FIX v3: korrekte URL-Pattern)
# ============================================================
KIMETA_QUERIES = [
    "stellenangebote-projektmanager-in-münchen",
    "stellenangebote-projektleiter-in-münchen",
    "it-projektmanager-jobs-münchen",
    "stellenangebote-senior-projektmanager-in-münchen",
    "ki-manager-jobs-münchen",
    "ai-project-manager-jobs-münchen",
    "projektmanager-automotive-jobs-münchen",
    "projektmanager-pharma-jobs-münchen",
    "modulleiter-jobs-münchen",
    "programmleiter-jobs-münchen",
    "baugruppenverantwortlicher-jobs-münchen",
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
# jobvector — MINT
# ============================================================
def crawl_jobvector(session) -> list:
    jobs = []
    queries = [
        ("ki-manager", "muenchen"), ("ai-project-manager", "muenchen"),
        ("senior-projektmanager", "muenchen"),
        ("projektleiter-automotive", "muenchen"),
        ("baugruppenverantwortlicher", "muenchen"),
        ("modulleiter", "muenchen"),
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
# LinkedIn Anonymous Search (NEU v3)
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
     "f_WT": "2"},  # Remote DE
    {"keywords": "AI Project Manager", "location": "Germany", "geoId": "101282230"},
    {"keywords": "KI Manager", "location": "Germany", "geoId": "101282230"},
    {"keywords": "Agile Projektmanager", "location": "Munich, Germany", "geoId": "100477049"},
    {"keywords": "PMO", "location": "Munich, Germany", "geoId": "100477049"},
]


def crawl_linkedin(session) -> list:
    jobs = []
    base = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    seen_jids = set()
    for q in LINKEDIN_QUERIES:
        for start in [0, 25, 50]:  # 3 Seiten pro Query
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
    log.info(f"[LinkedIn] {len(jobs)} (über {len(LINKEDIN_QUERIES)} Suchen, anonymous)")
    return jobs


# ============================================================
# Verifikation
# ============================================================
EXPIRED_INDICATORS = [
    "diese url existiert nicht", "url existiert nicht", "stelle wurde besetzt",
    "stellenangebot ist nicht mehr verfügbar", "dieses stellenangebot ist abgelaufen",
    "page not found", "position closed", "job has been filled", "expired",
    "nicht mehr verfügbar", "no longer available", "stelle besetzt",
]
SPA_DOMAINS = ("jobs.personio.de", "smartrecruiters.com", "myworkdayjobs.com",
               "ashbyhq.com", "lever.co", "boards.greenhouse.io",
               "workable.com", "recruitee.com", "stepstone.de",
               "linkedin.com")


def verify_url(url: str, session) -> tuple:
    if not url:
        return (False, "no-url")
    try:
        r = session.get(url, timeout=12, allow_redirects=True)
        if r.status_code in (403, 999):  # 999 = LinkedIn-Block
            return (True, f"ok-{r.status_code}-trusted")
        if r.status_code != 200:
            return (False, f"HTTP {r.status_code}")
        host = urlparse(url).hostname or ""
        if any(d in host for d in SPA_DOMAINS):
            return (True, "ok-spa")
        body = r.text.lower()
        for ind in EXPIRED_INDICATORS:
            if ind in body:
                return (False, f"expired: {ind}")
        return (True, "ok")
    except Exception as e:
        return (False, f"err: {type(e).__name__}")


def parallel_verify(jobs, session, max_workers: int = 10) -> list:
    log.info(f"Verifiziere {len(jobs)} URLs…")
    out = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(verify_url, j["url"], session): j for j in jobs}
        for f in as_completed(futs):
            j = futs[f]
            ok, status = f.result()
            j["verified"] = ok
            j["verify_status"] = status
            if ok:
                out.append(j)
    log.info(f"  → {len(out)}/{len(jobs)} live")
    return out


def apply_filter(jobs) -> list:
    log.info(f"Filter+Score auf {len(jobs)} Jobs…")
    seen = set()
    out = []
    blocked = duped = low = 0
    for j in jobs:
        url = j.get("url")
        if not url or url in seen:
            duped += 1
            continue
        seen.add(url)
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
        j["score"] = score
        j["score_reasons"] = reasons[:5]
        j["category"] = categorize(j.get("title", ""), j.get("description", ""))
        out.append(j)
    out.sort(key=lambda x: x["score"], reverse=True)
    log.info(f"  → {len(out)} · {blocked} blocked · {low} low · {duped} dupes")
    return out


# ============================================================
# Main
# ============================================================
def main():
    started = datetime.now()
    log.info(f"=== Crawl v3 gestartet {started.isoformat()} ===")
    s = make_session()
    all_jobs = []
    sources = [
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
    ]
    for fn, name in sources:
        try:
            all_jobs.extend(fn(s))
        except Exception as e:
            log.error(f"[{name}] Fataler Fehler: {e}")

    filtered = apply_filter(all_jobs)
    verified = parallel_verify(filtered, s, max_workers=10)

    payload = {
        "generated_at": started.isoformat(),
        "duration_s": (datetime.now() - started).total_seconds(),
        "stats": {
            "raw": len(all_jobs),
            "filtered": len(filtered),
            "verified": len(verified),
            "by_category": {},
            "sources": [n for _, n in sources],
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
            log.info(f"iCloud Drive: {ICLOUD}/jobsuche_standalone.html")

    log.info(f"=== Crawl v3 fertig: {len(verified)} Jobs ===")
    log.info(f"Dauer: {payload['duration_s']:.1f}s · Kategorien: {payload['stats']['by_category']}")


if __name__ == "__main__":
    main()
