# -*- coding: utf-8 -*-
"""
Andy-Fit — zweite Bewertungsstufe fuer das Jobsuche-Dashboard (NEU 27.09.2026).

WARUM ES DAS GIBT
    Der alte Score (profile.score_job) bewertet fast nur Stichwoerter im TITEL. Jede
    "Senior Projektmanager (m/w/d) Muenchen"-Anzeige bekam dadurch 63 Punkte, egal ob
    ERP-Einfuehrung, Windpark, Verwaltungs-IT oder Elektro-Bauleitung. Stand 26.09.:
    die Plaetze 2-40 waren zu gut einem Drittel fachfremd, waehrend Bertrandt
    (Gesamtfahrzeugerprobung) mit 80 unterging. Der SessionStart-Hook meldete deshalb
    "]init[ Verwaltungsprojekte" und "Studyflix KI-Manager" als Top-Luecken.

WAS ES TUT
    Liest den VOLLTEXT der Anzeige (faellt bei der Live-Pruefung im Crawler ohnehin an,
    kein Zusatzabruf) und bewertet ihn gegen Andys echtes Profil:
      Rolle   (0-30)  fachlicher Arbeitskern: technisches PM, Teilprojektleitung,
                      Entwicklungsprojekte, Gesamtfahrzeug, Integration, Konzept
      Domaene (0-35)  Automotive, E/E, Steuergeraete, Karosserie, Robotik, Mechatronik,
                      MedTech-Geraete, Konstruktion, Prototyp, Serie, Validierung
      Standort(0-15)  Muenchen/Umland oder >=80 % Remote
      Zugang  (0-10)  Techniker/vergleichbare Qualifikation ausdruecklich geoeffnet
    minus Fremddomaene (IT/ERP, Verwaltung, Energie-Netz, Bau/TGA, Pharma, Finanzen ...)
    minus K.o.-Signale (Studium zwingend, Englisch C1, Vertrieb, disziplinarische Fuehrung)

    Ergebnis je Job: fit (0-100), fit_reasons (Liste), fit_ko (Liste harter Warnungen),
    fit_basis ("volltext" | "titel"). Der alte score bleibt unveraendert erhalten.

WAS ES NICHT IST
    Keine Bewerbungsentscheidung. Die faellt erst in der Werkstatt mit Anforderungs-Matrix
    (CLAUDE.md §25) und Gremium. Der Fit sortiert nur vor, damit das Richtige oben steht.

Deterministisch, ohne Netz, ohne API-Kosten. Selbsttest: python3 crawler/fit_engine.py --selftest
"""
import html as _html
import json
import re
import sys

# ------------------------------------------------------------------ Textaufbereitung

def _fix_mojibake(s):
    """requests liest Seiten ohne charset als ISO-8859-1 -> 'MÃ¼nchen' (CLAUDE.md §28.3)."""
    if s and ("Ã" in s or "â€" in s):
        try:
            return s.encode("latin-1").decode("utf-8")
        except Exception:
            return s.replace("Ã¼", "ü").replace("Ã¶", "ö").replace("Ã¤", "ä").replace("ÃŸ", "ß")
    return s


def _clean(s):
    s = _fix_mojibake(_html.unescape(s or ""))
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.replace(" ", " ").replace("​", "")
    return re.sub(r"\s+", " ", s).strip()


def extract_jd_text(html_doc, max_chars=20000):
    """Stellentext aus einer Anzeigen-Seite. 1) JSON-LD JobPosting.description, 2) sichtbarer Text."""
    if not html_doc or len(html_doc) < 50:
        return ""
    for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html_doc, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for it in items:
            if isinstance(it, dict) and "@graph" in it and isinstance(it["@graph"], list):
                items.extend(x for x in it["@graph"] if isinstance(x, dict))
        for it in items:
            if not isinstance(it, dict):
                continue
            typ = it.get("@type")
            typ = " ".join(typ) if isinstance(typ, list) else str(typ or "")
            if "JobPosting" in typ:
                parts = [it.get("title") or "", it.get("description") or "",
                         it.get("qualifications") or "", it.get("responsibilities") or ""]
                txt = _clean(" ".join(str(p) for p in parts))
                if len(txt) > 200:
                    return txt[:max_chars]
    body = re.sub(r"<(script|style|noscript|svg|header|footer|nav)[^>]*>.*?</\1>", " ", html_doc, flags=re.S | re.I)
    return _clean(body)[:max_chars]


def _low(s):
    s = (s or "").lower()
    s = re.sub(r"\(\s*(?:[mwdfxa][\s/\\.\-*]*){1,5}\)", " ", s)     # (m/w/d) raus
    s = re.sub(r"\b(?:all\s*genders?|divers)\b", " ", s)
    return re.sub(r"\s+", " ", s)

# ------------------------------------------------------------------ Andys Profil

# Rolle: Titel zaehlt stark, Volltext nur als Bestaetigung
ROLLE_KERN = [  # (regex, punkte, label)
    (r"teil-?projektleit", 30, "Teilprojektleitung"),
    (r"technische[rn]? projekt(manager|leit)|technical (project|program) manag", 30, "Technisches PM"),
    (r"engineering (project|program) manag|project manag\w* (r&d|engineering|development)|projekt(manager|leiter)\S*\s+(entwicklung|r&d|f&e)", 30, "PM Entwicklung/R&D"),
    (r"projektingenieur|project engineer", 26, "Projektingenieur"),
    (r"entwicklungsprojekt|produktentwicklung|product development", 24, "Produktentwicklung"),
    (r"gesamtfahrzeug|fahrzeugintegration|vehicle integration|fahrzeugfunktion", 30, "Gesamtfahrzeug"),
    (r"systemintegration|system integration|integrationsmanag", 24, "Systemintegration"),
    (r"validierung|erprobung|absicherung|validation", 22, "Validierung/Erprobung"),
    (r"package ?(lead|verantw|manag)|bauteilverantw|modulverantw|komponentenverantw", 28, "Bauteil-/Packageverantwortung"),
    (r"konzept(ingenieur|entwickl|konstrukt)|concept engineer", 26, "Konzeptentwicklung"),
    (r"konstruktionsleit|leiter konstruktion|head of mechanical design", 24, "Konstruktionsleitung"),
    (r"process excellence|prozessoptimierung entwicklung|pmo\b|project management office", 22, "PMO/Process Excellence"),
    (r"se-?teamleit|systems? engineering", 20, "Systems Engineering"),
    # NEU 2026-09-30: Serienmanagement/-betreuung (Andy: SE-Teamleiter in der Serienbetreuung
    # LIN-Stromverteiler/ENS, CFK-Serienfertigung BMW i3/i8). Silver Atena "Serienmanager" lag bei Fit 56.
    (r"serien ?(manag|betreu|verantw|koordin)|series manag|anlauf ?manag|launch manag", 26, "Serienmanagement"),
]
ROLLE_MITTEL = [
    (r"projekt ?manager|projektmanag|project manag", 18, "Projektmanagement"),
    (r"projekt ?leit|project lead", 18, "Projektleitung"),
    (r"program(m)? ?manag", 16, "Programmsteuerung"),
    (r"product owner", 12, "Product Owner"),
    (r"entwicklungsingenieur|development engineer|konstrukteur|design engineer", 16, "Entwicklung/Konstruktion"),
    (r"projektkoordinat|project coordinat", 12, "Projektkoordination"),
]

# Rollen, die Andy nicht will oder nicht kann -> K.o. (Titel)
ROLLE_KO = [
    (r"\b(vertrieb|sales|account (manager|executive)|key account|business development|pre-?sales|sdr)\b", "Vertrieb/Sales"),
    (r"customer success|implementation (manager|consultant|specialist)|onboarding manag", "Kunden-Rollout (Implementation-Falle)"),
    (r"\b(werkstudent|praktikant|praktikum|internship|intern\b|trainee|auszubildend|ausbildung|junior)", "Einstiegsrolle"),
    (r"software[- ]?(entwickler|developer|engineer|architekt)|\bdevops\b|full-?stack|backend|frontend|data scientist|data engineer", "Softwareentwicklung"),
    (r"\b(coach|trainer|dozent|lehrkraft|enablement)\b", "Coach/Trainer"),
    (r"bauleit|bauingenieur|\btga\b|elektroinstallat|haustechnik|gebaeudetechnik|gebäudetechnik|versorgungstechnik"
     r"|\bhls\b|heizung|lüftung|lueftung|sanitär|sanitaer|klimatechnik|kältetechnik|\belt\b|planer\b.*elektro"
     r"|elektrotechnik/datentechnik|elektroplan", "Bau/TGA"),
    (r"einkauf|procurement|buyer\b|beschaffung|controlling|buchhalt|steuerberat|recruit|personalreferent|hr business", "Einkauf/Finanzen/HR"),
    (r"\b(sap|erp|crm|salesforce)\b.*(berater|consultant|projekt|manager)|(berater|consultant)\b.*\b(sap|erp|crm)\b", "SAP/ERP-Beratung"),
    (r"head of|director|abteilungsleit|bereichsleit|vp\b|vice president", "Leitungsrolle (disziplinarisch pruefen)"),
]

# Domaene: Volltext, jede Gruppe zaehlt einmal
DOMAENE = [
    (r"automotive|automobil|fahrzeug|vehicle|\boem\b|tier ?1", 6, "Automotive/Fahrzeug"),
    (r"karosserie|interieur|interior|sitzsystem|\bsitz(e|entwicklung)?\b|cockpit|verdeck", 5, "Karosserie/Interieur"),
    (r"\be/e\b|e/e-|elektrik/elektronik|bordnetz|kabelbaum|wiring harness", 6, "E/E-Architektur"),
    (r"steuerger|\becu\b|\bsensor|kamera|camera|adas|fahrerassistenz|lidar|radar", 5, "Steuergeraete/Sensorik"),
    (r"mechatron|robot|cobot|humanoid|aktor|antrieb|actuator", 6, "Robotik/Mechatronik"),
    (r"medizintechnik|medical device|medtech|chirurg|surgical|instrument|mdr\b|iso 13485", 5, "MedTech-Geraete"),
    (r"konstruktion|catia|\bcad\b|siemens nx|\bnx\b|creo|solidworks|3d-modell", 6, "Konstruktion/CAD"),
    (r"prototyp|prototype|musterbau|versuchsfahrzeug|erprobungsträger", 5, "Prototypen"),
    (r"serienanlauf|serienreife|serienentwicklung|\bsop\b|industrialisierung|serienfertigung|serienproduktion|serienbetreuung|lieferfähigkeit|lieferfaehigkeit", 5, "Serie/Industrialisierung"),
    (r"gesamtfahrzeug|baukasten|package|bauraum|geometrie", 5, "Gesamtfahrzeug/Package"),
    (r"änderungsmanagement|aenderungsmanagement|change request|change management prozess|freigabe", 4, "Aenderungs-/Freigabemanagement"),
    (r"lastenheft|pflichtenheft|anforderungsmanagement|requirements? (engineering|management)", 4, "Anforderungen"),
    (r"hardware|elektronikentwicklung|leiterplatte|pcb", 3, "Hardware"),
    (r"maschinenbau|mechanical engineering|mechanik", 4, "Maschinenbau"),
    (r"e-mobil|elektromobil|batterie|hochvolt|high voltage|ladetechnik", 4, "E-Mobilitaet"),
    (r"fmea|apqp|ppap|iso 26262|aspice|v-modell|produktentstehung", 4, "Entwicklungsprozesse"),
    (r"messtechnik|präzision|praezision|nanopositio|optik|photonik|laser|halbleiter|semiconductor|kryo|cryogenic", 4, "Präzisions-/Messtechnik"),
    (r"mechanical|manufactur|design verification|verification test|product development|hardware development|engineering change|technical documentation", 4, "Engineering (EN)"),
    (r"lieferant|supplier|zulieferer", 3, "Lieferantensteuerung"),
    (r"\bki\b|künstliche intelligenz|kuenstliche intelligenz|\bai\b|automatisierung|n8n|workflow", 2, "KI/Automatisierung"),
]

# Fremddomaene: Volltext
FREMD = [
    (r"\berp\b|\bsap\b|s/4hana|\bcrm\b|salesforce|servicenow", "ERP/SAP/CRM"),
    (r"it-infrastruktur|it infrastructure|rechenzentrum|netzwerktechnik|cloud-migration|it-projekt|it project|atlassian|m365|microsoft 365", "IT-Infrastruktur"),
    (r"öffentliche[n]? (verwaltung|hand|auftraggeber)|behörde|kommune|verwaltungsdigital|e-government|onlinezugangsgesetz", "Verwaltung/Behoerden"),
    (r"energiewirtschaft|stromnetz|netzanschluss|umspannwerk|windpark|windenergie|photovoltaik|solarpark|\bpv-|fernwärme|stadtwerke|energieversorger", "Energiewirtschaft/Netze"),
    (r"hochbau|tiefbau|baustelle|bauherr|bauprojekt|gebäudetechnik|gebaeudetechnik|\btga\b|facility management|immobilie|elektroinstallation|\bhls\b|heizung, lüftung|sanitärtechnik", "Bau/TGA/Immobilien"),
    (r"pharma|arzneimittel|\bgmp\b|klinische studie|clinical trial|wirkstoff|biotech", "Pharma/Klinik"),
    (r"\bbank\b|versicherung|finanzdienst|asset management|fonds|wertpapier", "Finanzen/Versicherung"),
    (r"marketing|kampagne|e-commerce|onlineshop|retail|social media", "Marketing/Handel"),
    (r"\bsaas\b|softwareprodukt|software development|softwareentwicklung|app-entwicklung|web-entwicklung", "Softwarebranche"),
    (r"telekommunikation|glasfaser|mobilfunk|breitband", "Telekommunikation"),
] 

# Defense: ein "Defence" in der Branchenliste im Seitenfuss ist KEIN Defense-Job (Bertrandt/EDAG/Akkodis).
# Hart nur bei Titel/Firma oder eindeutigen Begriffen im Stellentext.
DEFENSE_HART = r"bundeswehr|rüstung|ruestung|wehrtechnik|verschlusssache|sicherheitsüberprüfung|sicherheitsueberpruefung|militär|militaer|military|waffensystem"
DEFENSE_WEICH = r"verteidigung|defence|defense"

MUC = ("münchen", "muenchen", "munich", "garching", "unterschleißheim", "unterschleissheim", "ismaning",
       "ottobrunn", "taufkirchen", "oberpfaffenhofen", "wessling", "weßling", "gilching", "germering", "dachau",
       "freising", "erding", "haar", "aschheim", "feldkirchen", "unterföhring", "unterfoehring", "grasbrunn",
       "pullach", "planegg", "martinsried", "gräfelfing", "graefelfing", "starnberg", "oberschleißheim",
       "karlsfeld", "puchheim", "neubiberg", "putzbrunn", "hallbergmoos", "eching", "neufahrn", "kirchheim",
       "unterhaching", "oberhaching", "sauerlach", "fürstenfeldbruck", "olching", "maisach", "poing",
       "vaterstetten", "feldmoching", "schwabing", "riem", "moosach", "freimann", "stockdorf", "gauting",
       "krailling", "augsburg")
REMOTE = r"(100\s?%|vollständig|vollstaendig|komplett|full(y)?)[ -]?remote|remote[- ]first|deutschlandweit remote|remote \(deutschland\)|homeoffice möglich zu 100|mobiles arbeiten zu 100"

STUDIUM_PFLICHT = (r"(abgeschlossene[sn]? |erfolgreich abgeschlossene[sn]? )(hochschul|universitäts|fachhochschul|ingenieur|technische[sn]? |wirtschafts\S* )?studium"
                   r"|abgeschlossene[sn]? ingenieurstudium|master(abschluss| degree)|bachelor('?s)?( degree)?|university degree"
                   r"|degree (from|in)|higher education|diplom-?ingenieur|dipl\.-ing|\bm\.sc|\bb\.sc")
STUDIUM_OFFEN = (r"techniker|meister(ausbildung|prüfung| oder)|vergleichbare (qualifikation|ausbildung)|gleichwertige (qualifikation|berufserfahrung|erfahrung|ausbildung)"
                 r"|oder vergleichbar|oder eine vergleichbare|or equivalent|or comparable|equivalent (professional |practical |work )?experience|berufserfahrung statt"
                 r"|alternativ.{0,40}(ausbildung|berufserfahrung)|technische ausbildung mit")
PHD = r"promotion|\bphd\b|doktor(and|arbeit|titel)"
# Nur Englisch zaehlt: "Deutschkenntnisse (mind. C2)" darf nicht triggern (BG-Phoenics-Fehlalarm 27.09.)
ENGLISCH_C1 = (r"verhandlungssicher\w* (englisch|english)|(englisch|english)\w*[^.;]{0,40}verhandlungssicher"
               r"|(englisch|english)\w*[^.;]{0,45}\b(c1|c2)\b|\b(c1|c2)\b[^.;]{0,20}(englisch|english)"
               r"|fluent (in )?english|english[^.;]{0,20}fluent|business fluent|fließend\w* (englisch|english)"
               r"|(englisch|english)[^.;]{0,25}fließend|native (english|speaker)|muttersprach\w* englisch")
DISZIPLINARISCH = r"disziplinarisch|personalverantwortung für|führung von (\d+|mehreren) mitarbeit|leitung eines teams von \d+|people management|line management"


def _hits(patterns, text):
    return [(p, w, lab) for (p, w, lab) in patterns if re.search(p, text)]


def bewerte(job):
    """Setzt fit, fit_reasons, fit_ko, fit_basis auf dem Job-Dict und gibt es zurueck."""
    titel = _low(job.get("title"))
    firma = _low(job.get("clean_company") or job.get("company"))
    ort = _low(" ".join(str(job.get(k) or "") for k in ("location", "address_city", "remote", "homeoffice")))
    voll = job.get("jd_text") or job.get("raw_text") or ""
    desc = job.get("description") or ""
    seite_passt = True
    if len(voll) >= 400:
        tok = [w for w in re.findall(r"[a-zäöüß&]{4,}", titel) if w not in ("senior", "junior", "gmbh", "all", "genders")]
        kopf = _low(voll[:6000])
        if len(tok) >= 2 and sum(1 for w in tok if w in kopf) / len(tok) < 0.34:
            seite_passt = False
            voll = ""
    basis = "volltext" if len(voll) >= 400 else ("beschreibung" if len(desc) >= 300 else "titel")
    text = _low(" ".join([job.get("title") or "", voll if len(voll) >= len(desc) else desc]))

    reasons, ko = [], []
    if not seite_passt:
        ko.append("Anzeigenseite zeigt andere Inhalte (evtl. offline, vor Bewerbung öffnen)")

    # --- Rolle (Titel entscheidet, Volltext bestaetigt) ---
    t_kern = _hits(ROLLE_KERN, titel)
    t_mit = _hits(ROLLE_MITTEL, titel)
    if t_kern:
        best = max(t_kern, key=lambda h: h[1])
        rolle = best[1]
        reasons.append(f"🎯 Rolle: {best[2]} (+{rolle})")
    elif t_mit:
        best = max(t_mit, key=lambda h: h[1])
        rolle = best[1]
        # Kern-Rolle erst im Volltext -> halber Aufschlag
        v_kern = _hits(ROLLE_KERN, text)
        if v_kern and basis != "titel":
            extra = 6
            rolle += extra
            reasons.append(f"🎯 Rolle: {best[2]}, Inhalt {v_kern[0][2]} (+{rolle})")
        else:
            reasons.append(f"🎯 Rolle: {best[2]} (+{rolle})")
    else:
        rolle = 4
        reasons.append("🎯 Rolle: kein PM-/Entwicklungskern im Titel (+4)")

    for p, lab in ROLLE_KO:
        if re.search(p, titel):
            ko.append(f"Rolle: {lab}")

    # --- Domaene ---
    d_hits = _hits(DOMAENE, text)
    t_dom = {lab for (_, _, lab) in _hits(DOMAENE, titel)}
    dom = 0
    for p, w, lab in d_hits:
        dom += w * (2 if lab in t_dom else 1)
    dom = min(dom, 35)
    if d_hits:
        reasons.append(f"🔧 Fachgebiet: {', '.join(l for _, _, l in d_hits[:5])} (+{dom})")
    else:
        reasons.append("🔧 Fachgebiet: keine Automotive-/Hardware-/Robotik-Signale (+0)")

    # --- Fremddomaene ---
    # Einmalige Erwaehnung = meist Branchenliste/Boilerplate -> zaehlt nicht (attocube-Fehlalarm 27.09.)
    f_hits = [lab for (p, lab) in FREMD if len(re.findall(p, text)) >= 2 or re.search(p, titel + " " + firma)]
    f_titel = [lab for (p, lab) in FREMD if re.search(p, titel + " " + firma)]
    malus = 0
    if f_hits:
        stark = len(set(f_hits)) + len(set(f_titel))
        if dom < 12:
            malus = min(10 * stark, 40)
        elif stark >= 2 and dom < 20:
            malus = min(5 * stark, 20)
        elif f_titel:
            malus = 10
        if malus:
            reasons.append(f"⛔ Fremdgebiet: {', '.join(dict.fromkeys(f_hits))} (−{malus})")
        if f_titel and dom < 12:
            ko.append("Branche passt nicht: " + ", ".join(dict.fromkeys(f_titel)))

    # --- Defense ---
    if re.search(DEFENSE_HART + "|" + DEFENSE_WEICH, titel + " " + firma) or len(re.findall(DEFENSE_HART, text)) >= 1:
        ko.append("Defense: nur ab 100.000 € (Regel 28.07.)")
    elif len(re.findall(DEFENSE_WEICH, text)) >= 3:
        reasons.append("ℹ️ Defense-Bezug im Text, prüfen (nur ab 100.000 €)")

    # --- Standort ---
    if any(m in ort for m in MUC) or any(m in firma for m in ("münchen", "munich")):
        st = 15
        reasons.append("📍 München/Umland (+15)")
    elif re.search(REMOTE, text) or re.search(REMOTE, ort) or "remote" in ort:
        st = 12
        reasons.append("📍 Remote (+12, Anteil prüfen)")
    else:
        st = 0
        ko.append("Standort: weder München noch ≥80 % Remote belegt")

    # --- Zugang ---
    zug = 0
    offen = bool(re.search(STUDIUM_OFFEN, text))
    if offen:
        zug += 10
        reasons.append("🚪 Techniker/vergleichbare Qualifikation zugelassen (+10)")
    elif basis != "titel" and re.search(STUDIUM_PFLICHT, text):
        zug -= 8
        ko.append("Studium gefordert, nicht geöffnet")
    if basis != "titel" and re.search(PHD, text) and not offen:
        zug -= 10
        ko.append("Promotion gefordert")
    if basis != "titel" and re.search(ENGLISCH_C1, text):
        zug -= 6
        ko.append("Englisch C1/verhandlungssicher gefordert (Andy B2)")
    if basis != "titel" and re.search(DISZIPLINARISCH, text):
        zug -= 6
        ko.append("Disziplinarische Führung (Andy will fachlich steuern)")

    # --- Synergie: Kernrolle UND echtes Fachgebiet ---
    syn = 10 if (rolle >= 22 and dom >= 18) else 0
    if syn:
        reasons.append("✅ Kernrolle + Fachgebiet passen zusammen (+10)")

    fit = rolle + dom + st + zug + syn - malus
    if job.get("manual"):
        fit += 5
        reasons.append("✋ Von Andy/Lead manuell geprüft (+5)")
    if basis == "titel":
        fit = min(fit, 55)
        reasons.append("ℹ️ Nur Titel lesbar, Volltext fehlt (max. 55)")

    harte = [k for k in ko if k.startswith(("Rolle:", "Branche", "Defense", "Standort"))]
    if harte:
        fit = min(fit, 30)
    fit = max(0, min(100, int(round(fit))))

    job["fit"] = fit
    job["fit_reasons"] = reasons[:8]
    job["fit_ko"] = ko
    job["fit_basis"] = basis
    return job


def bewerte_alle(jobs):
    n = 0
    for j in jobs:
        try:
            bewerte(j)
            n += 1
        except Exception as e:  # nie den Crawl killen
            j["fit"] = None
            j["fit_reasons"] = [f"Fit-Fehler: {type(e).__name__}"]
            j["fit_ko"] = []
            j["fit_basis"] = "fehler"
    return n


# ------------------------------------------------------------------ Selbsttest

_TESTS = [
    # (titel, volltext, ort, erwartung: "hoch" >=70 | "mittel" 40-69 | "niedrig" <40)
    ("Projektmanager Gesamtfahrzeugerprobung & Validierungssteuerung (m/w/d)",
     "Sie steuern Erprobungsprogramme im Gesamtfahrzeug für einen Premium-OEM, koordinieren Prototypen, "
     "Absicherung und Freigaben mit Fachbereichen und Lieferanten. Abgeschlossenes Studium oder Techniker mit "
     "mehrjähriger Erfahrung in der Fahrzeugentwicklung. Gute Englischkenntnisse." * 2, "München", "hoch"),
    ("(Senior) Project Engineer Instruments – Development Projects",
     "Drive development projects for surgical instruments from concept to certified medical device, "
     "coordinate suppliers, prototypes, design verification. Degree in mechanical engineering or equivalent "
     "practical experience. CAD knowledge." * 2, "München", "hoch"),
    ("Senior Project Manager für digitale Verwaltungsprojekte",
     "Sie leiten Digitalisierungsprojekte für öffentliche Auftraggeber und Behörden, Onlinezugangsgesetz, "
     "IT-Projekte mit Kommunen. Abgeschlossenes Studium der Informatik." * 2, "München", "niedrig"),
    ("Senior Projektleiter Elektrotechnik (m/w/d)",
     "Projektleitung Elektroinstallation in Gebäudetechnik, TGA, Baustelle, Bauherr, Abnahmen." * 3,
     "München", "niedrig"),
    ("Senior Projektmanager (m/w/d) für Onshore Windparkprojekte",
     "Planung und Umsetzung von Windpark-Projekten, Netzanschluss, Genehmigungen, Energiewirtschaft." * 3,
     "München", "niedrig"),
    ("Senior Account Manager Automotive (m/w/d)", "Vertrieb an OEM und Tier 1, Neukundengewinnung." * 5,
     "München", "niedrig"),
    ("Technischer Projektleiter Robotik (m/w/d)",
     "Entwicklungsprojekte für mechatronische Robotersysteme, Prototypen bis Serienanlauf, Lieferanten, "
     "CAD-Konstruktion, Änderungsmanagement. Studium oder Techniker mit Berufserfahrung. Englisch B2." * 3,
     "Garching", "hoch"),
    ("Senior Projektmanager (m/w/d)", "", "München", "mittel_oder_niedrig"),
    ("Project Manager R&D (all genders)",
     "8.000+ Wissenschaftler Jobs in Deutschland. Senior COA Scientist IQVIA Berlin. Cookie-Richtlinie. " * 8,
     "Haar", "mittel_oder_niedrig"),
]


def _selftest():
    ok = True
    for titel, voll, ort, erw in _TESTS:
        # echte Anzeigenseiten enthalten den Titel (h1 bzw. JSON-LD title)
        seite = voll if "Wissenschaftler Jobs" in voll else ((titel + ". " + voll) if voll else "")
        j = bewerte({"title": titel, "jd_text": seite, "location": ort})
        f = j["fit"]
        good = {"hoch": f >= 70, "mittel": 40 <= f < 70, "niedrig": f < 40,
                "mittel_oder_niedrig": f < 70}[erw]
        ok &= good
        print(f"{'OK ' if good else 'XX '} {f:3d}  {erw:20s} {titel[:60]}")
        if not good:
            print("     ", j["fit_reasons"], j["fit_ko"])
    print("SELBSTTEST", "GRÜN" if ok else "ROT")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    if len(sys.argv) > 1:
        d = json.load(open(sys.argv[1], encoding="utf-8"))
        bewerte_alle(d["jobs"])
        for j in sorted(d["jobs"], key=lambda x: -(x.get("fit") or 0))[:40]:
            print(f"{j['fit']:3d} {j.get('score',0):3d} {j.get('fit_basis','')[:5]:5s} "
                  f"{(j.get('title') or '')[:55]:55s} | {(j.get('clean_company') or j.get('company') or '')[:25]}"
                  f" | {'; '.join(j['fit_ko'])[:60]}")
