#!/usr/bin/env python3
"""Andy's Jobsuche-Crawler v1
Sammelt Stellen aus mehreren Quellen, filtert gegen Andys Profil, schreibt data.json.

Quellen:
- Akkodis Sitemap (alle Akkodis-Jobs)
- arbeitnow.com API (Remote DE/EN)
- Personio-Subdomains (HTML-Parse)
- Bundesagentur (HTML-Suche)

Output:
- data.json neben jobsuche_v12.html
- logs/crawl-YYYY-MM-DD.log
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

# === Pfade ===
BASE = Path(__file__).resolve().parent.parent  # /Bewerbungen 2026/
DATA_PATH = BASE / "data.json"
LOG_DIR = BASE / "logs"
LOG_DIR.mkdir(exist_ok=True)

# === Logging ===
LOG_PATH = LOG_DIR / f"crawl-{datetime.now().strftime('%Y-%m-%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("crawl")

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
           "Accept-Language": "de-DE,de;q=0.9,en;q=0.8"}


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


# ============================================================
# QUELLE: AKKODIS via Sitemap
# ============================================================
def crawl_akkodis(session: requests.Session, limit_per_run: int = 80) -> list[dict]:
    """Liest Akkodis Sitemap, holt Job-Details für eine Auswahl."""
    log.info("[Akkodis] Sitemap holen…")
    url = "https://karriere.akkodis.com/sitemap.xml"
    try:
        r = session.get(url, timeout=15)
        r.raise_for_status()
    except Exception as e:
        log.warning(f"[Akkodis] Sitemap-Fehler: {e}")
        return []

    # Sitemap robust per Regex parsen (NS-Variante http vs https)
    job_urls = re.findall(r"<loc>(https?://karriere\.akkodis\.com/offer/[^<]+)</loc>", r.text)
    job_urls = list(dict.fromkeys(job_urls))  # dedupe, Reihenfolge erhalten
    log.info(f"[Akkodis] {len(job_urls)} Job-URLs in Sitemap")

    # Bevorzugung: München / Bayern / Auto / Engineering keywords im Slug
    priority_keywords = ["muenchen", "bayern", "automotive", "fahrzeug", "ee", "elektrik",
                         "projektleiter", "projektmanager", "modul", "baugruppen",
                         "konzept", "ki", "ai", "smart", "gesamtfahrzeug"]
    def prio(u: str) -> int:
        return sum(1 for k in priority_keywords if k in u.lower())
    job_urls.sort(key=prio, reverse=True)

    jobs = []
    fetched = 0
    for u in job_urls[:limit_per_run]:
        if fetched >= limit_per_run:
            break
        try:
            jr = session.get(u, timeout=12)
            if jr.status_code != 200:
                continue
            soup = BeautifulSoup(jr.text, "lxml")
            title_el = soup.find("h1") or soup.find("h2")
            title = title_el.get_text(strip=True) if title_el else ""
            body = soup.get_text(" ", strip=True)[:3000]
            # Standort robust: bekannte Stadtnamen im Body suchen, ggf. + Remote-Hinweis
            loc_text = ""
            CITIES = ["München", "Munich", "Ingolstadt", "Stuttgart", "Sindelfingen",
                      "Böblingen", "Berlin", "Hamburg", "Frankfurt", "Köln",
                      "Düsseldorf", "Leipzig", "Hannover", "Nürnberg", "Augsburg",
                      "Regensburg", "Ulm", "Dresden", "Bremen", "Wolfsburg",
                      "Heilbronn", "Karlsruhe", "Mannheim", "Neutraubling", "Chemnitz",
                      "Garching", "Ismaning", "Unterschleißheim", "Starnberg",
                      "Jena", "Erfurt", "Rostock", "Kiel", "Lübeck", "Saarbrücken",
                      "Münster", "Neubrandenburg"]
            found_cities = [c for c in CITIES if c in body]
            if found_cities:
                loc_text = " · ".join(found_cities[:3])
            # Remote/Hybrid-Hinweise anhängen
            for kw in ["hybrides Arbeiten", "Remote & Präsenz", "Homeoffice", "remote"]:
                if kw.lower() in body.lower():
                    loc_text = (loc_text + " · Hybrid Remote").strip(" ·")
                    break
            if not loc_text:
                slug = urlparse(u).path.lower()
                if "muenchen" in slug:
                    loc_text = "München"
            jobs.append({
                "source": "akkodis",
                "url": u,
                "title": title,
                "company": "Akkodis Group",
                "location": loc_text,
                "description": body[:600],
                "raw_text": body,
            })
            fetched += 1
        except Exception as e:
            log.debug(f"[Akkodis] {u}: {e}")
        time.sleep(0.15)  # rate-limit
    log.info(f"[Akkodis] {len(jobs)} Jobs detail-gefetcht")
    return jobs


# ============================================================
# QUELLE: arbeitnow.com API
# ============================================================
def crawl_arbeitnow(session: requests.Session, max_pages: int = 12) -> list:
    log.info("[arbeitnow] API holen…")
    jobs = []
    base = "https://www.arbeitnow.com/api/job-board-api"
    for page in range(1, max_pages + 1):
        try:
            r = session.get(base, params={"page": page}, timeout=15)
            if r.status_code != 200:
                break
            data = r.json().get("data", [])
            if not data:
                break
            for j in data:
                jobs.append({
                    "source": "arbeitnow",
                    "url": j.get("url"),
                    "title": j.get("title", ""),
                    "company": j.get("company_name", ""),
                    "location": j.get("location", ""),
                    "description": (j.get("description") or "")[:600],
                    "raw_text": (j.get("description") or "")[:3000],
                    "remote": bool(j.get("remote")),
                })
        except Exception as e:
            log.warning(f"[arbeitnow] page {page}: {e}")
            break
        time.sleep(0.3)
    log.info(f"[arbeitnow] {len(jobs)} Jobs")
    return jobs


# ============================================================
# QUELLE: Personio-Subdomains
# ============================================================
PERSONIO_COMPANIES = [
    # (subdomain, anzeige-name, alternative URL für Stellen-Detail falls Personio-Sub leitet)
    ("appliedai", "appliedAI Initiative", None),
    ("attempto", "attempto GmbH", "https://www.attempto.eu/de/karriere/job/{id}?language=de"),
    ("amiconsult", "amiconsult GmbH", "https://amiconsult.de/job/{id}?language=de"),
    ("elexon-gmbh", "elexon GmbH", None),
    ("eigenherd-gmbh", "Eigenherd GmbH", None),
    ("mitocare", "MITOcare GmbH", None),
    ("planworx", "PLANWORX AG", None),
    ("planfox", "PLANFOX Digital Health", None),
    ("amplimind", "amplimind", None),
    ("encoviva", "encoviva", None),
    ("peepz", "peepz GmbH", None),
    ("fyrfeed", "fyrfeed", None),
    ("liveeo-gmbh", "LiveEO GmbH", None),
    ("lifte-h2", "LIFTE H2", None),
    ("stackfuel-gmbh", "StackFuel GmbH", None),
    ("vulcan-energie-ressourcen-gmbh", "Vulcan Energie Ressourcen", None),
    ("jungvonmatt", "Jung von Matt", None),
    ("perelyn", "Perelyn", None),
    ("celonis", "Celonis", None),
    ("personio", "Personio", None),
    ("isarvalley", "Isar Aerospace", None),
    ("vaeridion", "VÆRIDION", None),
]


def crawl_personio(session: requests.Session) -> list[dict]:
    jobs = []
    for sub, name, alt_url in PERSONIO_COMPANIES:
        listing_url = f"https://{sub}.jobs.personio.de/?language=de"
        try:
            r = session.get(listing_url, timeout=12)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "lxml")
            for a in soup.select('a[href*="/job/"]'):
                href = a.get("href", "")
                m = re.search(r"/job/(\d+)", href)
                if not m:
                    continue
                job_id = m.group(1)
                if href.startswith("/"):
                    detail = f"https://{sub}.jobs.personio.de{href}"
                else:
                    detail = href
                if alt_url:
                    detail = alt_url.format(id=job_id)
                title_el = a.find(["h2", "h3"]) or a
                title = title_el.get_text(strip=True)
                # Standort suchen — Eltern-Container nach "loc" / "Standort" durchforsten
                container = a.find_parent()
                loc_text = ""
                for sel in ["[class*=location]", "[class*=Location]", "[class*=ort]"]:
                    el = (container or soup).select_one(sel)
                    if el:
                        loc_text = el.get_text(" ", strip=True)
                        break
                jobs.append({
                    "source": f"personio:{sub}",
                    "url": detail,
                    "title": title,
                    "company": name,
                    "location": loc_text,
                    "description": "",
                    "raw_text": title,
                })
        except Exception as e:
            log.debug(f"[personio:{sub}] {e}")
        time.sleep(0.2)
    log.info(f"[Personio] {len(jobs)} Jobs (über {len(PERSONIO_COMPANIES)} Firmen)")
    return jobs


# ============================================================
# QUELLE: Greenhouse / Lever / Workable / Ashby JSON-APIs
# ============================================================
GREENHOUSE_COMPANIES = ["openai", "anthropic", "stripe", "scaleai"]  # Beispielliste, später erweitern
LEVER_COMPANIES = ["palantir", "spacex"]  # selten DE-Stellen
WORKABLE_ACCOUNTS = []  # bei Bedarf erweitern


def crawl_greenhouse(session: requests.Session) -> list[dict]:
    jobs = []
    for co in GREENHOUSE_COMPANIES:
        url = f"https://boards-api.greenhouse.io/v1/boards/{co}/jobs"
        try:
            r = session.get(url, timeout=12)
            if r.status_code != 200:
                continue
            for j in r.json().get("jobs", []):
                jobs.append({
                    "source": f"greenhouse:{co}",
                    "url": j.get("absolute_url"),
                    "title": j.get("title", ""),
                    "company": co.capitalize(),
                    "location": (j.get("location") or {}).get("name", ""),
                    "description": "",
                    "raw_text": j.get("title", ""),
                })
        except Exception as e:
            log.debug(f"[gh:{co}] {e}")
    log.info(f"[Greenhouse] {len(jobs)} Jobs")
    return jobs


# ============================================================
# QUELLE: Bundesagentur (HTML-Suche, weil API Key braucht)
# ============================================================
BA_QUERIES = [
    ("KI Manager", None),
    ("AI Project Manager", None),
    ("Senior Projektmanager", "München"),
    ("Senior Projektmanager", None),  # bundesweit
    ("Programmleiter", "München"),
    ("Projektleiter Automotive", "München"),
    ("EE-Projektleiter", "München"),
    ("Modulleiter", "München"),
    ("Baugruppenverantwortlicher", "München"),
    ("Projektmanager Pharma", "München"),
    ("Projektmanager MedTech", "München"),
    ("Senior Project Manager", "München"),
]


def crawl_bundesagentur(session: requests.Session) -> list[dict]:
    jobs = []
    for query, location in BA_QUERIES:
        params = {"was": query, "umkreis": "25" if location else "200", "angebotsart": "1"}
        if location:
            params["wo"] = location
        url = "https://www.arbeitsagentur.de/jobsuche/suche"
        try:
            r = session.get(url, params=params, timeout=15)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "lxml")
            # BA listet Jobs als <a href="/jobsuche/jobdetail/REFNR">
            seen = set()
            for a in soup.select('a[href*="/jobsuche/jobdetail/"]'):
                href = a.get("href", "")
                m = re.search(r"/jobsuche/jobdetail/([^/?#]+)", href)
                if not m:
                    continue
                ref = m.group(1)
                if ref in seen:
                    continue
                seen.add(ref)
                full_url = urljoin("https://www.arbeitsagentur.de", href)
                title = a.get_text(" ", strip=True)
                # Aria-Label oft besser als Linktext
                if a.get("aria-label"):
                    title = a["aria-label"]
                cleaned_title = clean_title(title)
                jobs.append({
                    "source": "bundesagentur",
                    "url": full_url,
                    "title": cleaned_title[:200],
                    "company": "",  # BA-Detail hätte Firma, hier zu langsam
                    "location": location or "",
                    "description": "",
                    "raw_text": cleaned_title,
                })
        except Exception as e:
            log.warning(f"[BA] {query}/{location}: {e}")
        time.sleep(0.5)
    log.info(f"[Bundesagentur] {len(jobs)} Jobs (über {len(BA_QUERIES)} Suchen)")
    return jobs


# ============================================================
# QUELLE: Indeed RSS Feeds (de.indeed.com)
# ============================================================
INDEED_QUERIES = [
    ("KI Manager", "München", 25),
    ("AI Project Manager", "München", 25),
    ("Senior Projektmanager", "München", 25),
    ("Senior Projektleiter", "München", 25),
    ("Projektleiter Automotive", "München", 25),
    ("Modulleiter", "München", 25),
    ("EE-Projektleiter", "München", 50),
    ("Programmleiter", "München", 25),
    ("Projektmanager Pharma", "München", 25),
    ("Projektmanager MedTech", "München", 25),
    ("Senior Project Manager", "München", 25),
    ("Senior Project Manager", "Remote", None),
    ("KI Manager", "Deutschland", None),
    ("AI Project Manager", "Deutschland", None),
    ("Baugruppenverantwortlicher", "München", 50),
    ("Konzeptkonstrukteur", "München", 50),
    ("SE-Teamleiter", "München", 50),
    ("Studio Ingenieur", "München", 50),
]


def crawl_indeed(session: requests.Session) -> list:
    jobs = []
    for query, location, radius in INDEED_QUERIES:
        params = {"q": query, "fromage": "14", "format": "rss2"}
        if location:
            params["l"] = location
        if radius:
            params["radius"] = str(radius)
        url = "https://de.indeed.com/jobs"
        try:
            r = session.get(url, params=params, timeout=15)
            if r.status_code != 200:
                continue
            # RSS parsen
            try:
                root = ET.fromstring(r.text)
            except ET.ParseError:
                continue
            seen_in_query = set()
            for item in root.findall(".//item"):
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                desc = (item.findtext("description") or "").strip()
                if not link or link in seen_in_query:
                    continue
                seen_in_query.add(link)
                # Indeed-Description hat oft "Company - City"
                m_co = re.search(r"<b>([^<]+)</b>", desc)
                company = m_co.group(1) if m_co else ""
                # Location oft im title hinten "(Indeed) - City"
                jobs.append({
                    "source": "indeed",
                    "url": link,
                    "title": title[:200],
                    "company": company[:80],
                    "location": location or "",
                    "description": "",
                    "raw_text": title + " " + desc[:500],
                })
        except Exception as e:
            log.debug(f"[Indeed] {query}/{location}: {e}")
        time.sleep(0.4)
    log.info(f"[Indeed] {len(jobs)} Jobs (über {len(INDEED_QUERIES)} RSS-Suchen)")
    return jobs


# ============================================================
# QUELLE: StepStone (HTML-Suchseite, Filter inline.html-Direktlinks)
# ============================================================
STEPSTONE_QUERIES = [
    ("senior-projektmanager", "muenchen"),
    ("ai-project-manager", "muenchen"),
    ("ki-manager", "muenchen"),
    ("ki-manager", None),
    ("projektmanager-digital", "muenchen"),
    ("project-manager-pharma", "muenchen"),
    ("project-manager-biotech", "muenchen"),
    ("projektmanager-medizintechnik", "muenchen"),
    ("projektmanager-automotive", "muenchen"),
    ("projektleiter-automotive", "muenchen"),
    ("projektleiter-automotive", None),
    ("modulleiter", "muenchen"),
    ("baugruppenverantwortlicher", "muenchen"),
    ("programmleiter", "muenchen"),
    ("ai-project-manager", None),
    ("senior-projektmanager", None),
]


def crawl_stepstone(session: requests.Session) -> list:
    jobs = []
    for query, location in STEPSTONE_QUERIES:
        if location:
            url = f"https://www.stepstone.de/jobs/{query}/in-{location}"
        else:
            url = f"https://www.stepstone.de/jobs/{query}"
        try:
            r = session.get(url, timeout=15)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "lxml")
            seen_urls = set()
            # Stepstone job-card-Links sind /stellenangebote--TITLE-CITY-COMPANY--ID-inline.html
            for a in soup.select('a[href*="/stellenangebote--"]'):
                href = a.get("href", "")
                if "-inline.html" not in href:
                    continue
                full = href if href.startswith("http") else "https://www.stepstone.de" + href
                # Strip query params
                full = full.split("?")[0]
                if full in seen_urls:
                    continue
                seen_urls.add(full)
                title = a.get_text(" ", strip=True)
                if not title or len(title) < 5:
                    continue
                # Ort/Firma optional aus URL extrahieren
                m = re.search(r"--(.+?)--(\d+)-inline\.html$", full)
                meta = m.group(1) if m else ""
                jobs.append({
                    "source": "stepstone",
                    "url": full,
                    "title": title[:200],
                    "company": "",
                    "location": location or "",
                    "description": "",
                    "raw_text": title + " " + meta,
                })
        except Exception as e:
            log.debug(f"[StepStone] {query}/{location}: {e}")
        time.sleep(0.5)
    log.info(f"[StepStone] {len(jobs)} Jobs (über {len(STEPSTONE_QUERIES)} Suchen)")
    return jobs


# ============================================================
# QUELLE: Xing (HTML-Suche)
# ============================================================
XING_QUERIES = [
    ("Senior Projektmanager", "München"),
    ("KI Manager", "München"),
    ("AI Project Manager", "München"),
    ("Projektleiter Automotive", "München"),
    ("Modulleiter", "München"),
    ("Programmleiter", "München"),
]


def crawl_xing(session: requests.Session) -> list:
    jobs = []
    for query, location in XING_QUERIES:
        url = "https://www.xing.com/jobs/search"
        try:
            r = session.get(url, params={"keywords": query, "location": location}, timeout=15)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "lxml")
            for a in soup.select('a[href*="/jobs/"]'):
                href = a.get("href", "")
                m = re.search(r"/jobs/([a-z0-9-]+)-(\d+)", href)
                if not m:
                    continue
                full = "https://www.xing.com" + href if href.startswith("/") else href
                full = full.split("?")[0]
                title = a.get_text(" ", strip=True)
                if not title or len(title) < 5:
                    continue
                jobs.append({
                    "source": "xing",
                    "url": full,
                    "title": title[:200],
                    "company": "",
                    "location": location or "",
                    "description": "",
                    "raw_text": title,
                })
        except Exception as e:
            log.debug(f"[Xing] {query}/{location}: {e}")
        time.sleep(0.5)
    log.info(f"[Xing] {len(jobs)} Jobs (über {len(XING_QUERIES)} Suchen)")
    return jobs


# ============================================================
# QUELLE: jobvector (MINT-spezialisiert, RSS möglich)
# ============================================================
def crawl_jobvector(session: requests.Session) -> list:
    queries = ["ki-manager", "ai-project-manager", "senior-projektmanager", "projektleiter-automotive"]
    jobs = []
    for q in queries:
        url = f"https://www.jobvector.de/jobs/{q}/"
        try:
            r = session.get(url, timeout=15)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "lxml")
            for a in soup.select('a[href*="/jobs/"][href*="-job-"]'):
                href = a.get("href", "")
                full = href if href.startswith("http") else "https://www.jobvector.de" + href
                full = full.split("?")[0]
                title = a.get_text(" ", strip=True)
                if not title or len(title) < 5:
                    continue
                jobs.append({
                    "source": "jobvector",
                    "url": full,
                    "title": title[:200],
                    "company": "",
                    "location": "",
                    "description": "",
                    "raw_text": title,
                })
        except Exception as e:
            log.debug(f"[jobvector] {q}: {e}")
        time.sleep(0.4)
    log.info(f"[jobvector] {len(jobs)} Jobs")
    return jobs


# ============================================================
# Verifikation: HTTP 200 + nicht expired
# ============================================================
EXPIRED_INDICATORS = [
    "diese url existiert nicht", "url existiert nicht", "stelle wurde besetzt",
    "stellenangebot ist nicht mehr verfügbar", "dieses stellenangebot ist abgelaufen",
    "page not found", "position closed", "job has been filled", "expired",
    "nicht mehr verfügbar", "no longer available",
]


SPA_DOMAINS = ("jobs.personio.de", "smartrecruiters.com", "myworkdayjobs.com",
               "ashbyhq.com", "lever.co", "boards.greenhouse.io",
               "workable.com", "recruitee.com")


def verify_url(url: str, session: requests.Session) -> tuple:
    try:
        r = session.get(url, timeout=12, allow_redirects=True)
        # 403 = Bot-Block (Stepstone/Cloudflare etc.) → vertraue der Crawl-Quelle, marker live
        if r.status_code == 403:
            return (True, "ok-403-trusted")
        if r.status_code != 200:
            return (False, f"HTTP {r.status_code}")
        host = urlparse(url).hostname or ""
        is_spa = any(d in host for d in SPA_DOMAINS)
        if is_spa:
            return (True, "ok-spa")
        body = r.text.lower()
        for ind in EXPIRED_INDICATORS:
            if ind in body:
                return (False, f"expired: {ind}")
        return (True, "ok")
    except Exception as e:
        return (False, f"err: {type(e).__name__}")


def parallel_verify(jobs: list[dict], session: requests.Session, max_workers: int = 6) -> list[dict]:
    log.info(f"Verifiziere {len(jobs)} URLs parallel…")
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


# ============================================================
# Filter + Score + Categorize
# ============================================================
def apply_filter(jobs: list[dict]) -> list[dict]:
    log.info(f"Filter+Score auf {len(jobs)} Jobs…")
    seen_urls = set()
    out = []
    blocked = 0
    duped = 0
    low_score = 0
    for j in jobs:
        if not j.get("url") or j["url"] in seen_urls:
            duped += 1
            continue
        seen_urls.add(j["url"])
        score, reasons = score_job(
            j.get("title", ""), j.get("raw_text", "") or j.get("description", ""),
            j.get("location", ""), j.get("company", "")
        )
        if score < 0:
            blocked += 1
            continue
        if score < MIN_SCORE_TO_INCLUDE:
            low_score += 1
            continue
        j["score"] = score
        j["score_reasons"] = reasons[:5]
        j["category"] = categorize(j.get("title", ""), j.get("description", ""))
        out.append(j)
    out.sort(key=lambda x: x["score"], reverse=True)
    log.info(f"  → {len(out)} Treffer · {blocked} hard-block · {low_score} unter Score {MIN_SCORE_TO_INCLUDE} · {duped} dupes")
    return out


# ============================================================
# Main
# ============================================================
def main():
    started = datetime.now()
    log.info(f"=== Crawl gestartet {started.isoformat()} ===")
    s = make_session()
    all_jobs: list[dict] = []

    # Aktive Quellen (alle ohne JS-Rendering nutzbar):
    # - Akkodis (Sitemap)
    # - arbeitnow (JSON-API, paginated)
    # - Personio (22 Subdomains)
    # - Greenhouse JSON-APIs
    # - Bundesagentur (HTML-Suche)
    # - StepStone (HTML-Suche, ~16 Queries)
    # Indeed (Cloudflare-Captcha) und Xing (JS-only) entfernt — würden Playwright brauchen
    for fn, name in [
        (crawl_akkodis, "Akkodis"),
        (crawl_arbeitnow, "arbeitnow"),
        (crawl_personio, "Personio"),
        (crawl_greenhouse, "Greenhouse"),
        (crawl_bundesagentur, "Bundesagentur"),
        (crawl_stepstone, "StepStone"),
    ]:
        try:
            all_jobs.extend(fn(s))
        except Exception as e:
            log.error(f"[{name}] Fataler Fehler: {e}")

    # Filter VOR Verifikation: spart unnötige HTTP-Calls
    filtered = apply_filter(all_jobs)
    # Verifikation nur für Top-Treffer (Performance)
    verified = parallel_verify(filtered, s, max_workers=6)

    # data.json schreiben
    payload = {
        "generated_at": started.isoformat(),
        "duration_s": (datetime.now() - started).total_seconds(),
        "stats": {
            "raw": len(all_jobs),
            "filtered": len(filtered),
            "verified": len(verified),
            "by_category": {},
        },
        "jobs": [
            {k: v for k, v in j.items() if k != "raw_text"}  # raw_text nicht ins JSON, zu groß
            for j in verified
        ],
    }
    for j in verified:
        c = j.get("category", "other")
        payload["stats"]["by_category"][c] = payload["stats"]["by_category"].get(c, 0) + 1

    DATA_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    # Zusätzlich data.js für file://-Loading des Dashboards (umgeht CORS)
    DATA_JS = BASE / "data.js"
    data_js_content = "window.JOBSUCHE_DATA = " + json.dumps(payload, ensure_ascii=False) + ";\n"
    DATA_JS.write_text(data_js_content, encoding="utf-8")

    # Standalone-HTML bauen: jobsuche_v12.html + inline data → eine Datei
    # → kopiert nach iCloud Drive, von iPhone offline aufrufbar
    HTML_SRC = BASE / "jobsuche_v12.html"
    if HTML_SRC.exists():
        html = HTML_SRC.read_text(encoding="utf-8")
        # <script src="data.js"></script> ersetzen durch inline data
        inline_script = '<script>' + data_js_content + '</script>'
        html_inline = html.replace('<script src="data.js"></script>', inline_script)
        STANDALONE = BASE / "jobsuche_standalone.html"
        STANDALONE.write_text(html_inline, encoding="utf-8")
        log.info(f"Standalone HTML: {STANDALONE} ({len(html_inline)//1024} KB)")
        # iCloud Drive Sync (falls Pfad existiert)
        ICLOUD = (Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/Jobsuche")
        if ICLOUD.parent.exists():
            ICLOUD.mkdir(exist_ok=True)
            target = ICLOUD / "jobsuche_standalone.html"
            target.write_text(html_inline, encoding="utf-8")
            log.info(f"iCloud Drive: {target}")
    log.info(f"=== Crawl fertig: {len(verified)} Jobs in {DATA_PATH} ===")
    log.info(f"Dauer: {payload['duration_s']:.1f}s · Kategorien: {payload['stats']['by_category']}")


if __name__ == "__main__":
    main()
