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
# Greenhouse
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
    "joby", "wayve", "cohere", "mongodb", "formlabs", "databricks", "flix",
    "bitpanda", "grover", "mithril", "thinkingmachines",
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
                    cards = soup.select('a[data-jk]')
                    if not cards:
                        cards = soup.select('a[href*="/viewjob"]')
                    seen = set()
                    for a in cards:
                        jk = a.get("data-jk", "")
                        href = a.get("href", "")
                        if jk:
                            full = f"https://de.indeed.com/viewjob?jk={jk}"
                        elif "/viewjob" in href:
                            full = "https://de.indeed.com" + href if href.startswith("/") else href
                        else:
                            continue
                        if full in seen:
                            continue
                        seen.add(full)
                        title = a.get_text(" ", strip=True) or (a.find("h2") or a).get_text(" ", strip=True)
                        if not title or len(title) < 5:
                            continue
                        jobs.append({
                            "source": "indeed",
                            "url": full,
                            "title": title[:200],
                            "company": "",
                            "location": location,
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
    "page not found", "position closed", "job has been filled", "expired",
    "nicht mehr verfügbar", "no longer available", "stelle besetzt",
]
SPA_DOMAINS = ("jobs.personio.de", "smartrecruiters.com", "myworkdayjobs.com",
               "ashbyhq.com", "lever.co", "boards.greenhouse.io",
               "workable.com", "recruitee.com", "stepstone.de",
               "linkedin.com", "indeed.com", "remoteok.com", "remotive.com",
               "weworkremotely.com")


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
    """Extrahiert recruiter, address (street/city), kennziffer aus Job-HTML.
    Gibt Dict zurück; leere Strings wenn nicht gefunden.
    Patterns für Bundesagentur, LinkedIn, StepStone, Personio, Greenhouse, Workday."""
    out = {"recruiter": "", "address_street": "", "address_city": "", "kennziffer": ""}
    if not html or len(html) < 50:
        return out
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
                # NEU 2026-05-28: Detail-Parse für DOCX-Generator
                if html:
                    try:
                        det = parse_job_details(html, j.get("url", ""))
                        if det.get("recruiter"): j["recruiter"] = det["recruiter"]
                        if det.get("address_street"): j["address_street"] = det["address_street"]
                        if det.get("address_city"): j["address_city"] = det["address_city"]
                        if det.get("kennziffer"): j["kennziffer"] = det["kennziffer"]
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
        j["category"] = categorize(j.get("title", ""), j.get("description", ""))
        j["alt_sources"] = []
        by_hash[h] = j
        out.append(j)
    # Sortierung: zuerst nach first_seen DESC (neueste oben), dann score DESC
    out.sort(key=lambda x: (x.get("first_seen") or "", x.get("score") or 0), reverse=True)
    log.info(f"  → {len(out)} · {blocked} blocked · {low} low · {duped} dupes · {fresh} NEU")
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
    ]
    sources_no_session = [
        (crawl_indeed_playwright, "Indeed (Playwright)"),
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
