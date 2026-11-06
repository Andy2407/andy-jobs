"""Volltext je Stelle aus der Schnittstelle des Bewerbungssystems (NEU 2026-11-02).

Warum: Bis heute kam der Stellentext ausschliesslich aus der Anzeigenseite (parallel_verify ->
fit_engine.extract_jd_text). Bei Workday (Single-Page-App, Link ohne /External/ -> 404),
Allianz und teils Greenhouse/SuccessFactors bekam der Andy-Fit dadurch Menue-Text oder gar nichts.
Die ATS-Schnittstellen liefern den reinen Anzeigentext, live getestet am 02.11.2026:

  Arbeitsagentur  GET  rest.arbeitsagentur.de/.../pc/v4/jobdetails/<base64(refnr)>  (X-API-Key)
                       -> stellenangebotsBeschreibung + externeURL (weiterfuehrender Link)
  Workday         GET  <tenant>.wd<n>.myworkdayjobs.com/wday/cxs/<tenant>/<site><externalPath>
                       -> jobPostingInfo.jobDescription + externalUrl (der korrekte oeffentliche Link)
  Greenhouse      GET  boards-api.greenhouse.io/v1/boards/<board>/jobs/<id>      -> content
  Personio        GET  <sub>.jobs.personio.de/xml                                 -> jobDescriptions
  Ashby           GET  api.ashbyhq.com/posting-api/job-board/<org>                -> descriptionPlain
  SmartRecruiters GET  api.smartrecruiters.com/v1/companies/<co>/postings/<id>   -> jobAd.sections
  Lever           GET  api.lever.co/v0/postings/<co>/<id>                         -> descriptionPlain + lists

Trockenlauf 02.11. gegen das Dashboard: 92 von 97 Stellen dieser Quellen mit reinem Anzeigentext.

Der Volltext bleibt aus data.json heraus (oeffentlich, schlank). Er liegt lokal in
volltext/volltexte.json (gitignored, ueberlebt den reset --hard der Jobmaschine) und ist per
`python3 crawler/volltext.py zeige <Suchwort>` lesbar. data.json bekommt nur jd_len und jd_quelle.
Der Cache haelt ausserdem die StepStone-Details (Firma, Orte, Adresse), damit parallel_verify
dieselbe Anzeige nicht bei jedem Lauf neu abruft (StepStone drosselt sonst, siehe crawl_stepstone).
"""
import base64
import html as _html
import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
CACHE_PATH = BASE / "volltext" / "volltexte.json"
CACHE_TAGE = 3            # API-Texte nicht oefter als alle 3 Tage neu holen
MIN_ZEICHEN = 400         # ab hier gilt ein Text als Volltext (gleiche Grenze wie fit_engine)
STEPSTONE_DETAILS = ("clean_company", "address_city", "address_street", "kennziffer", "recruiter")


def _clean(s):
    s = _html.unescape(_html.unescape(s or ""))
    s = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


# ------------------------------------------------------------------ je Quelle

def _ba(job, s, memo):
    ref = job["url"].rstrip("/").rsplit("/", 1)[-1]
    enc = base64.b64encode(ref.encode()).decode()
    r = s.get("https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobdetails/" + enc,
              headers={"X-API-Key": "jobboerse-jobsuche"}, timeout=20)
    if r.status_code != 200:
        return None
    js = r.json()
    out = {"text": _clean(js.get("stellenangebotsBeschreibung")), "quelle": "api:arbeitsagentur"}
    ext = (js.get("externeURL") or "").strip()
    if ext.startswith("http"):
        # oft eine weitere Boerse (persy, heyjobs, finest-jobs, jobware), nicht immer der Arbeitgeber
        out["endlink"] = ext
    return out


def _workday(job, s, memo):
    m = re.match(r"https://([^.]+)\.wd(\d+)\.myworkdayjobs\.com(?:/[a-z]{2}-[A-Z]{2})?(/[^/]+)?(/job/.+)$", job["url"])
    if not m:
        return None
    ten, wd, site, path = m.groups()
    sites = [site.strip("/")] if site else []
    sites += [x for x in (job.get("workday_site"), "External") if x and x not in sites]
    for st in sites:
        r = s.get(f"https://{ten}.wd{wd}.myworkdayjobs.com/wday/cxs/{ten}/{st}{path}",
                  headers={"Accept": "application/json"}, timeout=20)
        if r.status_code == 200:
            info = r.json().get("jobPostingInfo") or {}
            out = {"text": _clean(info.get("jobDescription")), "quelle": "api:workday"}
            if info.get("externalUrl"):
                out["korrekte_url"] = info["externalUrl"]
            return out
    return None


def _greenhouse(job, s, memo):
    board = job["source"].split(":", 1)[1]
    gid = re.search(r"(?:jobs/|gh_jid=)(\d{5,})", job["url"] or "")
    if not gid:
        return None
    r = s.get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{gid.group(1)}", timeout=20)
    if r.status_code != 200:
        return None
    return {"text": _clean(r.json().get("content")), "quelle": "api:greenhouse"}


def _personio(job, s, memo):
    sub = job["source"].split(":", 1)[1]
    pid = re.search(r"/job/(\d+)", job["url"] or "")
    if not pid:
        return None
    key = "personio:" + sub
    if key not in memo:
        r = s.get(f"https://{sub}.jobs.personio.de/xml?language=de", timeout=20)
        memo[key] = {}
        if r.status_code == 200:
            tx = r.content.decode("utf-8", "replace")
            for pm in re.finditer(r"<position>.*?</position>", tx, re.S):
                i = re.search(r"<id>(\d+)</id>", pm.group(0))
                teile = re.findall(r"<name>(.*?)</name>\s*<value>(.*?)</value>", pm.group(0), re.S)
                if i:
                    memo[key][i.group(1)] = "\n".join(f"{_clean(n)}\n{_clean(v)}" for n, v in teile)
    t = memo[key].get(pid.group(1))
    return {"text": t, "quelle": "api:personio"} if t else None


def _ashby(job, s, memo):
    org = job["source"].split(":", 1)[1]
    key = "ashby:" + org
    if key not in memo:
        r = s.get(f"https://api.ashbyhq.com/posting-api/job-board/{org}", timeout=20)
        memo[key] = r.json().get("jobs", []) if r.status_code == 200 else []
    for x in memo[key]:
        if job["url"] in (x.get("jobUrl"), x.get("applyUrl")):
            return {"text": _clean(x.get("descriptionPlain") or x.get("descriptionHtml")), "quelle": "api:ashby"}
    return None


def _smartrecruiters(job, s, memo):
    co = job["source"].split(":", 1)[1]
    pid = re.search(r"/(\d{6,})", job["url"] or "")
    if not pid:
        return None
    r = s.get(f"https://api.smartrecruiters.com/v1/companies/{co}/postings/{pid.group(1)}", timeout=20)
    if r.status_code != 200:
        return None
    sec = (r.json().get("jobAd") or {}).get("sections") or {}
    text = "\n".join(_clean((v or {}).get("text")) for v in sec.values())
    return {"text": text, "quelle": "api:smartrecruiters"}


def _lever(job, s, memo):
    co = job["source"].split(":", 1)[1]
    lid = re.search(r"lever\.co/[^/]+/([0-9a-f-]{20,})", job["url"] or "")
    if not lid:
        return None
    r = s.get(f"https://api.lever.co/v0/postings/{co}/{lid.group(1)}?mode=json", timeout=20)
    if r.status_code != 200:
        return None
    js = r.json()
    teile = [js.get("descriptionPlain") or ""]
    for li in js.get("lists", []):
        teile += [li.get("text", ""), _clean(li.get("content"))]
    teile.append(js.get("additionalPlain") or "")
    return {"text": "\n".join(t for t in teile if t), "quelle": "api:lever"}


ABRUF = {
    "bundesagentur": _ba, "workday": _workday, "greenhouse": _greenhouse, "personio": _personio,
    "ashby": _ashby, "smartrecruiters": _smartrecruiters, "lever": _lever,
}


# ------------------------------------------------------------------ Cache

def lade_cache():
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def speichere_cache(cache, aktuelle_urls):
    """Nur Stellen behalten, die im aktuellen Lauf noch vorkommen oder <14 Tage alt sind."""
    grenze = (datetime.now() - timedelta(days=14)).isoformat()
    behalten = {u: v for u, v in cache.items() if u in aktuelle_urls or v.get("abgerufen", "") >= grenze}
    CACHE_PATH.parent.mkdir(exist_ok=True)
    tmp = CACHE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(behalten, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CACHE_PATH)
    return len(behalten)


def frisch(eintrag, tage=CACHE_TAGE):
    return bool(eintrag) and eintrag.get("abgerufen", "") >= (datetime.now() - timedelta(days=tage)).isoformat()


def stepstone_details(j):
    """Was parallel_verify aus einer StepStone-Detailseite gewonnen hat, fuer den Cache."""
    d = {k: j.get(k) for k in STEPSTONE_DETAILS if j.get(k)}
    d["orte"] = [o.strip() for o in (j.get("location") or "").split(",") if o.strip()]
    note = j.get("final_link_note") or ""
    d["direct_apply"] = True if note == "stepstone-direktbewerbung" else (False if note.startswith("stepstone-") else None)
    return d


# ------------------------------------------------------------------ Hauptfunktion

def anreichern(jobs, session, log=None, pause=0.15):
    """Fuer jede Stelle: API-Text (wenn Quelle unterstuetzt) > Seiten-JSON-LD > Seitentext.
    Setzt jd_text (intern), jd_len, jd_quelle; bei Workday die korrekte URL, bei der Arbeitsagentur
    den weiterfuehrenden Link (arbeitgeber_link). Gibt eine Statistik je Quelle zurueck."""
    cache = lade_cache()
    memo = {}
    stat = {}
    jetzt = datetime.now().isoformat()
    for j in jobs:
        src = (j.get("source") or "?").split(":")[0]
        st = stat.setdefault(src, {"n": 0, "api": 0, "seite": 0, "ohne": 0})
        st["n"] += 1
        fn = ABRUF.get(src)
        res = None
        c = cache.get(j.get("url"))
        aus_cache = False
        if fn and frisch(c) and c.get("quelle", "").startswith("api:"):
            res, aus_cache = c, True
        elif fn:
            try:
                res = fn(j, session, memo)
                time.sleep(pause)
            except Exception as e:
                if log:
                    log.debug(f"[volltext] {src} {j.get('url', '')[:70]}: {e}")
        if res and len(res.get("text") or "") >= MIN_ZEICHEN:
            # Titel voranstellen wie fit_engine.extract_jd_text (JSON-LD: title + description). Ohne ihn
            # verwirft die Fit-Engine den Text als "Seite zeigt andere Inhalte" (Titelwort-Abgleich).
            titel = (j.get("title") or "").strip()
            text = res["text"]
            j["jd_text"] = text if not titel or text.startswith(titel) else f"{titel}\n{text}"
            j["jd_quelle"] = res["quelle"]
            if res.get("korrekte_url") and res["korrekte_url"] != j.get("url"):
                j["url_alt"] = j["url"]
                j["url"] = res["korrekte_url"]
            if res.get("endlink"):
                j["arbeitgeber_link"] = res["endlink"]
            st["api"] += 1
        else:
            res, aus_cache = None, False
            if len(j.get("jd_text") or "") >= MIN_ZEICHEN:
                j["jd_quelle"] = j.get("jd_quelle") or "seite"
                st["seite"] += 1
            else:
                st["ohne"] += 1
        j["jd_len"] = len(j.get("jd_text") or "")
        if not j.get("jd_text"):
            continue
        # Abrufzeit nur erneuern, wenn wirklich neu abgerufen wurde (sonst altert der Cache nie)
        alt = (c or {}).get("abgerufen")
        neu_geholt = not aus_cache and j.get("verify_status") != "ok-suche+cache"
        eintrag = {"text": j["jd_text"], "quelle": j.get("jd_quelle", "seite"),
                   "titel": j.get("title", ""), "firma": j.get("clean_company") or j.get("company") or "",
                   "abgerufen": jetzt if (neu_geholt or not alt) else alt}
        for k in ("korrekte_url", "endlink"):
            if res and res.get(k):
                eintrag[k] = res[k]
        if src == "stepstone":
            eintrag["details"] = stepstone_details(j)
        cache[j["url"]] = eintrag
    n_cache = speichere_cache(cache, {j.get("url") for j in jobs})
    if log:
        for q, v in sorted(stat.items(), key=lambda x: -x[1]["n"]):
            log.info(f"[volltext] {q:18} {v['n']:4} Stellen · API {v['api']:3} · Seite {v['seite']:3} · ohne {v['ohne']:3}")
        log.info(f"[volltext] Cache: {n_cache} Texte in {CACHE_PATH}")
    return stat


def zeige(suchwort):
    """CLI: python3 crawler/volltext.py zeige <Teil von Titel/Firma/URL>"""
    sw = suchwort.lower()
    n = 0
    for u, v in lade_cache().items():
        if sw in (u + " " + v.get("titel", "") + " " + v.get("firma", "")).lower():
            n += 1
            print(f"=== {v.get('titel')} | {v.get('firma')} | {v.get('quelle')} | {v.get('abgerufen', '')[:16]}\n{u}\n")
            print(v["text"])
            print()
    if not n:
        print(f"Kein Volltext zu '{suchwort}' in {CACHE_PATH}")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "zeige":
        zeige(" ".join(sys.argv[2:]))
    else:
        print(__doc__)
