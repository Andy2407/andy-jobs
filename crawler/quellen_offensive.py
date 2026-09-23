# -*- coding: utf-8 -*-
"""
Quellen-Offensive + Endlink-Aufloesung, Andy 2026-09-23.

Anlass (Andy woertlich): "Ich finde auf Xing immer wieder Positionen, die zu mir gut passen,
sehe sie aber nicht im Dashboard." / "Arbeit Now: ich gehe drauf, dann kommt nochmal ein Link
'Jetzt bewerben' und dann erst die richtige Position. Ich will immer den allerletzten Link."

Diagnose 23.09.2026 (live gemessen, nicht angenommen):
  1. UMLAUT-BUG: requests rät bei Seiten ohne charset-Header ISO-8859-1. Aus "München" wird
     "MÃ¼nchen", der Standortfilter kennt das nicht und blockt. Xing: 170 von 185 Roh-Treffern
     so geblockt, im Dashboard landete 1 einzige Xing-Stelle.
  2. XING-SCOPE: nur 6 Suchbegriffe, nur München 25 km, keine bundesweite Remote-Suche,
     keine Beschreibung (Scoring nur auf den Titel).
  3. ZWISCHENLINKS: arbeitnow, remotely, adzuna, Xing, stellenanzeigen, yourfirm verlinken auf
     die eigene Portalseite. Der echte Arbeitgeber-Link steckt eine bis zwei Ebenen tiefer
     (remotely -> Xing -> Arbeitgeber).
  4. QUELLEN-BREITE: neu lesbar und angebunden: jobware.de, ingenieur.de (VDI), adzuna.de.
     Geprüft und per HTTP gesperrt (403/Bot-Schutz): Indeed, Glassdoor, Monster, meinestadt,
     jooble, jobvector, jobboerse.de, kununu. Die laufen nur über Browser/Hand.
"""
import html as _html
import re
import time
import logging
import concurrent.futures as cf
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode, urljoin, quote

log = logging.getLogger("crawler")

# ------------------------------------------------------------------ Umlaute
_MOJI = re.compile(r"[ÃÂ][\x80-\xbf\u0080-ÿ€‚ƒ„…†‡ˆ‰Š‹ŒŽ‘’“”•–—˜™š›œžŸ¡-¿]")


def fix_mojibake(s):
    """'MÃ¼nchen' -> 'München'. Nur wenn das Muster wirklich vorkommt und die Rueckwandlung
    sauber aufgeht; sonst Original zurueck (lieber unveraendert als kaputt repariert)."""
    if not s or not isinstance(s, str) or not _MOJI.search(s):
        return s
    for enc in ("latin-1", "cp1252"):
        try:
            fixed = s.encode(enc).decode("utf-8")
            if not _MOJI.search(fixed):
                return fixed
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return s


def repair_jobs(jobs):
    n = 0
    for j in jobs:
        for k in ("title", "company", "location", "description", "raw_text"):
            v = j.get(k)
            f = fix_mojibake(v)
            if f is not v and f != v:
                j[k] = f
                n += 1
    return n


def utf8(r):
    """Antworttext IMMER als UTF-8 lesen (Fallback-Rateversuch von requests ist die Bug-Quelle)."""
    try:
        return r.content.decode("utf-8")
    except UnicodeDecodeError:
        return r.content.decode(r.apparent_encoding or "utf-8", "replace")


def _clean(s):
    s = _html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()


# ------------------------------------------------------------------ Xing breit
XING_QUERIES = [
    "Projektmanager", "Projektleiter", "Teilprojektleiter", "technischer Projektleiter",
    "Technical Project Manager", "Senior Project Manager", "Program Manager",
    "Produktentwicklung", "Entwicklungsprojektleiter", "Projektingenieur",
    "Gesamtfahrzeug", "Fahrzeugentwicklung", "Automotive Projektmanager",
    "Validierung Fahrzeug", "Erprobung", "Process Excellence", "PMO",
    "KI Manager", "AI Project Manager", "Prozessmanager Entwicklung",
    "Konzeptentwicklung", "Vorentwicklung", "EE Projektleiter", "Robotik Projektleiter",
]
XING_FULL_REMOTE = "FULL_REMOTE.050e26"


def _xing_parse(txt, remote=False):
    out = []
    txt = txt.replace("\\u002F", "/")
    for m in re.finditer(r'"url":"(https://www\.xing\.com/jobs/[^"?]+)[^"]*","title":"([^"]{4,160})"', txt):
        jurl, title = m.group(1), _html.unescape(m.group(2))
        ctx = txt[max(0, m.start() - 1500):m.start() + 1500]
        cm = (re.search(r'"companyNameOverride":"([^"]{2,80})"', ctx)
              or re.search(r'"companyName":"([^"]{2,80})"', ctx))
        lm = re.search(r'"city":"([^"]{2,60})"', ctx)
        city = lm.group(1) if lm else ""
        loc = f"Remote Deutschland ({city})" if remote else (city or "München")
        out.append({"source": "xing", "url": jurl, "title": title[:200],
                    "company": _html.unescape(cm.group(1)) if cm else "",
                    "location": loc, "description": "", "raw_text": title,
                    "remote": remote})
    return out


def crawl_xing_breit(session):
    """Xing: 24 Suchbegriffe x (München 50 km + bundesweit Vollremote) x 2 Seiten, UTF-8."""
    log.info("[Xing breit] Jobs…")
    jobs, seen = [], set()
    for q in XING_QUERIES:
        for remote in (False, True):
            for page in (1, 2):
                if remote:
                    url = (f"https://www.xing.com/jobs/search/ki?keywords={quote(q)}"
                           f"&remoteOption={XING_FULL_REMOTE}&page={page}")
                else:
                    url = (f"https://www.xing.com/jobs/search/ki?keywords={quote(q)}"
                           f"&location=M%C3%BCnchen&radius=50&page={page}")
                try:
                    r = session.get(url, timeout=20)
                    if r.status_code != 200:
                        break
                    got = _xing_parse(utf8(r), remote=remote)
                    new = [j for j in got if j["url"] not in seen]
                    for j in new:
                        seen.add(j["url"])
                    jobs.extend(new)
                    if not got:
                        break
                    time.sleep(0.35)
                except Exception as e:
                    log.debug(f"[Xing breit] {q} p{page}: {e}")
    log.info(f"[Xing breit] {len(jobs)} Jobs")
    return jobs


# ------------------------------------------------------------------ jobware / ingenieur.de
# Beide laufen auf derselben Plattform (Karten-Layout identisch, /job/<slug>-<id>).
PORTAL_Q = ["Projektleiter", "Projektmanager", "Teilprojektleiter", "technischer Projektleiter",
            "Project Manager", "Entwicklungsprojektleiter", "Produktentwicklung",
            "Gesamtfahrzeug", "Fahrzeugerprobung", "KI Manager", "Program Manager",
            "Prozessmanager"]


def _slug(q):
    q = q.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return re.sub(r"[^a-z0-9]+", "-", q).strip("-")


def _jobware_engine(session, host, source, label):
    log.info(f"[{label}] Jobs…")
    jobs, seen = [], set()
    orte = [("muenchen", "München"), ("homeoffice", "Remote Deutschland")]
    for q in PORTAL_Q:
        for ort_slug, ort_label in orte:
            if ort_slug == "homeoffice":
                url = f"https://{host}/jobs--fuer-{_slug(q)}-homeoffice"
            else:
                url = f"https://{host}/jobs--fuer-{_slug(q)}--in-{ort_slug}"
            try:
                r = session.get(url, timeout=20)
                if r.status_code != 200:
                    continue
                t = utf8(r)
                for card in t.split("<article")[1:]:
                    hm = re.search(r'href="(/job/[a-z0-9-]+-\d{6,})"', card)
                    if not hm:
                        continue
                    jurl = f"https://{host}{hm.group(1)}"
                    if jurl in seen:
                        continue
                    c = re.sub(r"<!--.*?-->", "", card, flags=re.S)
                    c = re.sub(r"<style.*?</style>", "", c, flags=re.S)
                    c = c.split(">", 1)[1] if ">" in c else c   # Rest des <article ...>-Tags weg
                    hm2 = re.search(r"<h[1-4][^>]*>(.*?)</h[1-4]>", c, re.S)
                    if not hm2:
                        continue
                    title = _html.unescape(_clean(hm2.group(1)))   # &amp;amp; -> &
                    after = c[hm2.end():]
                    parts = [p.strip() for p in re.split(r"<[^>]+>", after) if p.strip()]
                    parts = [_html.unescape(p) for p in parts if not p.startswith(".") and len(p) < 300]
                    company = parts[0] if parts else ""
                    loc = ""
                    for i, p in enumerate(parts):
                        if p == "in" and i + 1 < len(parts):
                            loc = parts[i + 1]
                            break
                    home = any("home" in p.lower() or "remote" in p.lower() for p in parts[:12])
                    if ort_slug == "homeoffice" and home and not re.search(r"münchen|munich", loc.lower()):
                        loc = f"Remote Deutschland ({loc})" if loc else "Remote Deutschland"
                    task = re.search(r'job-card__task[^>]*>(.*?)</div>', card, re.S)
                    desc = _clean(task.group(1)) if task else ""
                    seen.add(jurl)
                    jobs.append({"source": source, "url": jurl, "title": title[:200],
                                 "company": company[:120], "location": loc or ort_label,
                                 "description": desc[:600], "raw_text": (title + " " + desc)[:3000],
                                 "remote": ort_slug == "homeoffice" and home})
                time.sleep(0.3)
            except Exception as e:
                log.debug(f"[{label}] {q}/{ort_slug}: {e}")
    log.info(f"[{label}] {len(jobs)} Jobs")
    return jobs


def crawl_jobware(session):
    return _jobware_engine(session, "www.jobware.de", "jobware", "jobware.de")


def crawl_ingenieur_de(session):
    return _jobware_engine(session, "jobs.ingenieur.de", "ingenieur.de", "ingenieur.de (VDI)")


# ------------------------------------------------------------------ adzuna (Meta-Suche DE)
def crawl_adzuna(session):
    log.info("[adzuna] Jobs…")
    jobs, seen = [], set()
    for q in PORTAL_Q:
        for where in ("M%C3%BCnchen", "Homeoffice"):
            for page in (1, 2):
                url = f"https://www.adzuna.de/search?q={quote(q)}&w={where}&p={page}"
                try:
                    r = session.get(url, timeout=20)
                    if r.status_code != 200:
                        break
                    t = utf8(r)
                    blocks = re.split(r'<article', t)[1:]
                    n = 0
                    for b in blocks:
                        am = re.search(r'href="(https://www\.adzuna\.de/(?:land/)?ad/(\d+)[^"]*)"', b)
                        tm = re.search(r'<h2>\s*<a[^>]*>(.*?)</a>', b, re.S)
                        if not am or not tm:
                            continue
                        aid = am.group(2)
                        if aid in seen:
                            continue
                        seen.add(aid)
                        comp = re.search(r'class="ui-company">(.*?)</div>', b, re.S)
                        loc = re.search(r'class="ui-location[^"]*">(.*?)</div>', b, re.S)
                        snip = re.search(r'class="max-snippet-height[^"]*">(.*?)</', b, re.S)
                        title = _clean(tm.group(1))
                        desc = _clean(snip.group(1)) if snip else ""
                        l = _clean(loc.group(1)).title() if loc else ""
                        if where == "Homeoffice" and not re.search(r"münchen|munich", l.lower()):
                            l = f"Remote Deutschland ({l})" if l else "Remote Deutschland"
                        jobs.append({"source": "adzuna", "url": _html.unescape(am.group(1)),
                                     "title": title[:200],
                                     "company": _clean(comp.group(1)) if comp else "",
                                     "location": l, "description": desc[:600],
                                     "raw_text": (title + " " + desc)[:3000]})
                        n += 1
                    if not n:
                        break
                    time.sleep(0.3)
                except Exception as e:
                    log.debug(f"[adzuna] {q}: {e}")
    log.info(f"[adzuna] {len(jobs)} Jobs")
    return jobs


# ------------------------------------------------------------------ Endlink-Aufloesung
TRACKING = re.compile(r"^(utm_|_pc$|ref$|jw_chl_seg$|pja_cmp$|source$|src$|se$|v$|gclid$|fbclid$)")
TRACKER_HOSTS = ("relaxx.center", "anzeigenvorschau.net", "cloudfront.net", "adj.st")
AD_RENDER_HOSTS = ("anzeigenvorschau.net", "cloudfront.net")
PORTAL_HOSTS = ("arbeitnow.com", "xing.com", "adzuna.de", "remotely.de", "stellenanzeigen.de",
                "yourfirm.de", "kimeta.de", "jobrapido.com", "talent.com", "whatjobs.com",
                "finanzstellenmarkt.de", "jobs.bnn.de")


def strip_tracking(u):
    try:
        p = urlparse(u)
        q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not TRACKING.match(k)]
        frag = "" if p.fragment.startswith("apply") else p.fragment
        return urlunparse(p._replace(query=urlencode(q), fragment=frag))
    except Exception:
        return u


def _is_portal(u):
    h = (urlparse(u).hostname or "").lower()
    return any(h.endswith(p) for p in PORTAL_HOSTS)


def _next_hop(url, session):
    """Ein Sprung Richtung Arbeitgeber. Gibt (naechste_url | None, notiz) zurueck."""
    h = (urlparse(url).hostname or "").lower()
    if h.endswith("arbeitnow.com") and "/jobs/" in url:
        r = session.get(url.rstrip("/") + "/apply", timeout=15, allow_redirects=True)
        # Hostname pruefen, nicht den String: der Endlink traegt "utm_source=arbeitnow.com"
        return (None if _is_portal(r.url) else r.url), "arbeitnow/apply"
    r = session.get(url, timeout=15, allow_redirects=True)
    if r.url != url and not _is_portal(r.url):
        return r.url, "redirect"
    t = utf8(r).replace("\\u002F", "/").replace('\\"', '"')
    if h.endswith("xing.com"):
        # FIX 23.09.2026: Die Seite enthaelt auch die Bewerbungslinks der "aehnlichen Jobs".
        # Der erste Treffer gehoerte bei WeMatch zu "Global Side GmbH" = falsche Firma.
        # Deshalb NUR den application-Block nehmen, dessen naechstvorheriges "id" die
        # Stellen-ID dieser URL ist.
        jid = re.search(r"-(\d{6,})(?:$|[/?#])", url)
        if not jid:
            return None, "xing-ohne-id"
        jid = jid.group(1)
        for m in re.finditer(r'"application":\{"__typename":"(\w+)"(?:,"applyUrl":"([^"]+)")?', t):
            before = t[:m.start()]
            k = before.rfind('"id":"')
            owner = re.match(r'"id":"(\d+)', before[k:k + 30]) if k >= 0 else None
            if owner and owner.group(1) == jid:
                if m.group(1) == "UrlApplication" and m.group(2):
                    return _html.unescape(m.group(2)), "xing/applyUrl"
                return None, "xing-direktbewerbung"   # Bewerbung laeuft ueber Xing = Endlink
        return None, "xing-application-nicht-gefunden"
    if h.endswith("remotely.de"):
        # Bewerben-Anker traegt data-job-click-surface="job_detail" + plausible job_apply_clicked
        m = (re.search(r'job_apply_clicked[^>]*?href="(https?://[^"]+)"', t)
             or re.search(r'applyUrl\\*":\\*"(https?://[^"\\]+)', utf8(r)))
        return (_html.unescape(m.group(1)) if m else None), "remotely/apply"
    if h.endswith("adzuna.de"):
        if not _is_portal(r.url):
            return r.url, "adzuna/redirect"
        m = re.search(r'(?:http-equiv="refresh"[^>]*url=|window\.location(?:\.href)?\s*=\s*["\'])([^"\'>]+)', t, re.I)
        return (_html.unescape(m.group(1)) if m else None), "adzuna/meta"
    m = re.search(r'<a[^>]+href="([^"]+)"[^>]*id="apply_now_button"', t) or \
        re.search(r'<a[^>]+id="apply_now_button"[^>]*href="([^"]+)"', t)
    if m:
        return _html.unescape(m.group(1)), "apply_now_button"
    # generisch: Anker, der "Jetzt bewerben"/"Zur Stellenanzeige" traegt und extern zeigt
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(?:(?!</a>).){0,400}?(Jetzt bewerben|Zur Stellenanzeige|Zum Stellenangebot|Zur Anzeige|Online bewerben)', t, re.S | re.I):
        cand = urljoin(url, _html.unescape(m.group(1)))
        if not _is_portal(cand) and cand.startswith("http"):
            return cand, "anker"
    return None, "kein-endlink"


def resolve_final(url, session, max_hops=3):
    chain, cur, note = [url], url, ""
    for _ in range(max_hops):
        if not _is_portal(cur):
            break
        try:
            nxt, note = _next_hop(cur, session)
        except Exception as e:
            note = f"err:{type(e).__name__}"
            break
        if not nxt or nxt in chain:
            break
        chain.append(nxt)
        cur = nxt
    # Tracking-Weiterleiter (relaxx, Adjust u. a.) bis zum Ziel verfolgen
    if any(h in (urlparse(cur).hostname or "") for h in TRACKER_HOSTS):
        try:
            rr = session.get(cur, timeout=15, allow_redirects=True)
            if rr.url and rr.url != cur:
                chain.append(rr.url)
                cur = rr.url
            if any(h in (urlparse(cur).hostname or "") for h in AD_RENDER_HOSTS):
                nxt, _n = _next_hop(cur, session)
                if nxt:
                    chain.append(nxt); cur = nxt
        except Exception:
            pass
    final = strip_tracking(cur)
    ok = (not _is_portal(final)) or note == "xing-direktbewerbung"
    if note == "xing-direktbewerbung":
        final = strip_tracking(url)
    return final, ok, chain, note


def resolve_final_links(jobs, session, max_workers=10):
    """Setzt j['url'] auf den Arbeitgeber-Endlink, j['portal_url'] auf den Fundort.
    j['final_link'] = True nur, wenn wirklich beim Arbeitgeber/ATS gelandet (oder Xing-
    Direktbewerbung). Sonst bleibt der Portal-Link stehen und ist ehrlich als solcher markiert."""
    todo = [j for j in jobs if j.get("url") and _is_portal(j["url"])]
    for j in jobs:
        if j not in todo:
            j.setdefault("final_link", True)

    def work(j):
        return j, resolve_final(j["url"], session)

    ok_n = 0
    with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
        for j, (final, ok, chain, note) in ex.map(work, todo):
            j["portal_url"] = j["url"]
            j["link_chain"] = chain
            j["final_link"] = bool(ok)
            j["final_link_note"] = note
            if ok:
                j["url"] = final
                ok_n += 1
    # gleiche Endstelle ueber mehrere Portale -> eine Karte, Rest als alt_sources
    by_url, out = {}, []
    for j in jobs:
        u = j.get("url")
        if u in by_url:
            p = by_url[u]
            if (j.get("score") or 0) > (p.get("score") or 0):
                j.setdefault("alt_sources", []).extend(
                    [{"source": p.get("source"), "url": p.get("portal_url") or p.get("url")}] + (p.get("alt_sources") or []))
                out[out.index(p)] = j
                by_url[u] = j
            else:
                p.setdefault("alt_sources", []).append(
                    {"source": j.get("source"), "url": j.get("portal_url") or u})
            continue
        by_url[u] = j
        out.append(j)
    log.info(f"[Endlink] {ok_n}/{len(todo)} Portal-Links auf Arbeitgeber aufgeloest, "
             f"{len(jobs) - len(out)} Mehrfachfunde zusammengelegt")
    return out


# ------------------------------------------------------------------ Xing-Beschreibungen
def enrich_xing(jobs, session, score_fn, max_n=900, max_workers=10):
    """NEU 23.09.2026 (2. Fassung nach Gegencheck):
    - Firma und Ort IMMER aus dem JSON-LD der Detailseite. Der Listen-Parser griff Firma/Ort aus
      einem Textfenster und erwischte die Nachbarstelle (LRE Medical stand als "Hensoldt,
      Fuerstenfeldbruck" drin, "IT-PMO" Coopers Zuerich als "IEK Cottbus").
    - Punkte weiter nur aus dem Titel (wie die anderen Portale mit Kurztext). Die volle
      Beschreibung dient NUR der Sperrpruefung: Wird eine Stelle erst durch die Beschreibung
      geblockt (Bau, Ruestung, Junior ...), bekommt raw_text den Volltext, damit der Filter greift.
      Grund: Mit Volltext-Punkten kam ein "Vorstandsreferent" auf 91."""
    import json as _json
    cand = [j for j in jobs if j.get("source") == "xing"
            and score_fn(j.get("title", ""), j.get("raw_text", ""), j.get("location", ""), j.get("company", ""))[0] >= 0]
    cand = cand[:max_n]

    def work(j):
        try:
            r = session.get(j["url"], timeout=15)
            t = utf8(r)
            m = re.search(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', t, re.S)
            if not m:
                return 0
            d = _json.loads(m.group(1))
            d = d[0] if isinstance(d, list) else d
            org = (d.get("hiringOrganization") or {}).get("name")
            if org:
                j["company"] = _html.unescape(org)
            locs = d.get("jobLocation") or []
            locs = locs if isinstance(locs, list) else [locs]
            city = ((locs[0] if locs else {}).get("address") or {}).get("addressLocality") or ""
            if city:
                j["location"] = f"Remote Deutschland ({city})" if j.get("remote") else city
            desc = _clean(d.get("description", ""))
            if desc:
                j["description"] = desc[:600]
                full = score_fn(j.get("title", ""), desc, j.get("location", ""), j.get("company", ""))
                if full[0] < 0:
                    j["raw_text"] = (j.get("title", "") + " " + desc)[:4000]
            return 1
        except Exception:
            return 0

    with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
        n = sum(ex.map(work, cand))
    log.info(f"[Xing] {n}/{len(cand)} Detailseiten (Firma, Ort, Sperrpruefung) nachgeladen")
    return n
