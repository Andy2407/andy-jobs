"""Andy's Profil + Filterregeln — Single Source of Truth.
Wird von crawler.py importiert. Beim Anpassen der Regeln NUR hier ändern.
"""
import re
import html

# ===== HARD EXCLUDES (Title-Substring → Job verworfen) =====
TITLE_BLOCK = [
    # ---------- Coding / SW-Engineering ----------
    "software engineer", "software developer", "software architect", "softwareentwickler",
    "software-entwickler", "softwareentwicklung", "software-entwicklung",
    "ai engineer", "ml engineer", "data engineer", "devops engineer", "site reliability",
    "backend developer", "backend engineer", "backend-entwickler",
    "frontend developer", "frontend engineer", "frontend-entwickler",
    "full-stack", "fullstack", "full stack",
    "embedded software", "firmware engineer", "firmware-entwickler",
    "hardware engineer", "hw engineer",
    "ic design", "asic", "fpga", "vlsi",
    "release manager software", "releasemanager software", "release-manager software",
    "releasemanager automotive‑software", "releasemanager automotive-software",
    "software releasemanager", "software-releasemanager", "software-release-manager",
    "software - releasemanager", "software - release",
    "requirements engineer",
    "business manager", "key account manager",
    "plc programmier", "sps programmier", "plc-programmier",
    "projekt manager softwareentwicklung", "projektmanager softwareentwicklung",
    "system engineer", "systems engineer", "systemingenieur", "sysadmin", "systemadministrator",
    "it administrator", "it-administrator",
    "it-systemelektroniker", "it systemelektroniker",
    "stress engineer", "stress-engineer",
    "compliance engineer", "compliance-engineer", "product compliance",
    "test engineer", "testingenieur", "testingenieur:in",
    "application manager", "applikationsmanager", "applikation manager",
    "applied ai architect", "ki-architect", "ki architect", "ai architect",
    "hcm",
    "cloud engineer", "cloud architect",
    "linux system", "windows admin", "citrix",
    "datacenter", "mainframe", "rechenzentrum",
    "machine learning research scientist", "ml research", "research scientist",
    # ---------- IT-Support / Helpdesk / Junior-Tech ----------
    "support agent", "support specialist", "first level support", "1st level",
    "2nd level support", "second level support", "service desk",
    "servicetechniker", "service-techniker", "helpdesk", "help desk",
    "it techniker", "it-techniker",
    "messtechniker", "kalibriertechniker", "kalibrierungstechniker",
    # ---------- Tester / QA ----------
    "software tester", "softwaretester", "test engineer", "qa engineer",
    "qualitätssicherung software", "test manager software", "testmanager software",
    "qa manager software", "quality assurance software",
    # ---------- SAP ----------
    "sap ", "sap-",  # SAP allgemein blocken — Andy ist KEIN SAP-Mensch
    "s/4hana", "s4 hana", "s/4 hana",
    # ---------- Senior-Overshoot (zu hoch) ----------
    "head of ai", "vp ai", "chief ai", "c-level", "head of engineering",
    "lead developer", "tech lead", "engineering manager",
    "head of content",
    # ---------- Junior / Praktikum / Ausbildung ----------
    "junior ", "junior-", "werkstudent", "praktikant", "praktikum", "intern ",
    "internship", "ausbildung", "auszubildende", "duales studium", "trainee",
    "absolvent", "berufseinsteiger",
    # NEU 2026-06-01: Studienarbeiten + Azubi-/Werker-Berufe (kamen über BMW/Bertrandt-Sitemaps rein)
    "bachelorarbeit", "masterarbeit", "studienarbeit", "abschlussarbeit", "diplomarbeit",
    "kfz mechatroniker", "kfz-mechatroniker", "produktionsmitarbeiter", "maschinenbediener",
    "industriemechaniker", "fachkraft lager", "fachkraft für lager", "anlagenführer",
    # NEU 2026-06-02: Promotions-/Werkstudenten-Vorstufen (BMW-Sitemap: 47 Treffer, ~0 passend —
    # Masterand/Doktorand/Dualer Student rutschten durch, weil nur "masterarbeit" geblockt war)
    "masterand", "masterandin", "doktorand", "doktorandin", "promovend", "promovendin",
    "dualer student", "duale studentin", "dualer studentin", "dual student", "dualer master",
    "working student", "studentische aushilfe", "studentische hilfskraft", "studentenjob",
    "master thesis", "bachelor thesis", "master-thesis", "praxissemester", "diplomand",
    # NEU 2026-06-02: Off-Topic-Berufe aus OEM-Sitemaps (Recht / Verkauf / Personenschutz)
    "rechtsanwalt", "rechtsanwältin", "syndikus", "patentanwalt", "patentanwältin",
    "patentanwaltsfach", "rechtsreferendar", "referendar", "notariat",
    "automobilverkäufer", "automobilverkäuferin", "verkaufsberater", "verkäufer (",
    "personenschützer", "sicherheitsfahrer", "personenschutz", "objektschutz", "werkschutz",
    "veranstaltungssicherheit", "sicherheitsmanager", "werksfeuerwehr",
    # ---------- Bau ----------
    "bauleiter", "bauingenieur", "projektleiter bau", "projektsteuerer bau",
    "projektleiter tga", "versorgungstechnik", "hochbau", "tiefbau", "gebäudetechnik",
    "bauprojekt", "bautechnik", "hlks", "heizung-sanitär", "klempner",
    "bauwesen",  # "Senior Projektmanager:in im Bauwesen"
    "vertrags- und nachtragsmanagement", "nachtragsmanagement",
    "investitionsprojekte",  # meist Bau-/Industrie-Bau
    # ---------- Schienen / DB / ÖPNV ----------
    "deutsche bahn", "db infrago", "schienenverkehr", "schienenfahrzeug",
    "etcs", "dstw", "lst für",  # Bahn-Stellwerk/Leit- und Sicherungstechnik
    "fahrzeugabnahme schiene", "fahrzeugabnahme bahnfahrzeug",
    "manager rail", "manager:in rail", "managerin rail", " rail -",
    "rolling stock", "ros (w/", "ros(w/",
    # ---------- Defense / Rüstung / Marine ----------
    "rüstung", "defense", "verteidigung", "bundeswehr",
    "marine ", "marineschiff", "marineschiffbau",
    "schiffbau",
    "vincorion", "t60 consulting",
    # ---------- HR / Recruiting / Sales ----------
    "personaldienstleistung", "kaltakquise", "outbound sales",
    "field sales", "telesales",
    "niederlassungsleiter personaldienstleistung",
    "sales manager", "sales managerin", "sales director",
    "account executive", "account director", "account manager",
    "business development manager", "bdr",
    "performance manager", "paid social", "social media manager",
    "marketing manager", "growth manager",
    "co-founder", "founder", "vp of",
    "customer success", "cs manager",
    "bid manager", "tender manager",
    "niederlassungsleiter",
    "vertriebscontroller", "vertriebscontrolling",
    # ---------- Sonstiges Off-Topic ----------
    "interior designer", "retail designer", "ugc content", "ugc-content",
    "content creator",
    # NEU 2026-06-01: Long-Tail-Branchen, die nicht zu Andys Engineering-/PM-Profil passen
    "creative media", "werbeagentur", "mediaagentur", "media agentur",
    "arcadis", "socotec", "building solutions", "building technologies",
    "immobilien", "steuerberatung", "wirtschaftsprüfung", "tax advisory",
    "property manager", "facility manager", "objektverwalter",
    "real estate property", "real estate manager",
    "hv cable", "kabeljointing", "kabel-jointing",
    "krankenpfleger", "altenpfleger", "pflegefachkraft",
    "sicherheitsmitarbeiter", "wachschutz",
    "sanierung", "objektplanung",
    "producer", "creative director",
    # ---------- Sachbearbeitung / Verwaltung / Buchhaltung ----------
    "sachbearbeiter", "sachbearbeitung",
    "buchhalter", "buchhaltung", "weg-buchhalter",
    "verwaltungsfachwirt", "verwaltungsfachkraft", "verwaltungsangestellte",
    "drittmittel", "forderungsmanagement", "auftragsabrechnung",
    "projektassistenz", "projektassistent",
    "kaufmännische fachkraft", "kaufmännischer mitarbeiter",
    "supplier quality engineer", "lieferantenqualität",
    # ---------- Sonstige Off-Topic-Branchen ----------
    "messebauunternehmen", "messebau",
    "kfz-mechatroniker", "kfz-meister", "automechaniker",
    "fahrlehrer", "lehrer", "dozent",
    "fahrschule", "fahrschulfahrzeug", "wipersystem",
    "veterinär", "tierarzt", "physiotherapeut",
    # ---------- NEU 2026-05-28 (Andy Top-20-Audit): Mismatches die durchgerutscht sind ----------
    # IT-Projektmanager-/IT-Projektleiter — Andy ist Senior PM für Hardware/GFZ, NICHT IT
    "it projektmanager", "it-projektmanager", "it projektleiter", "it-projektleiter",
    "it project manager", "it project lead", "it-project manager", "it project leader",
    "it-projektmanagerin", "it-projektleiterin",
    "informatik-projektleiter", "informatik projektleiter",
    "projektmanager email", "projektmanager e-mail",
    "obsolescence manager", "email obsolescence",
    # Flugfunk / Funktechnik / Radio (Andy hat NIE mit Funk gearbeitet)
    "flugfunk", "flugfunkprodukt", "flugfunkanlag",
    "funktechnik", "funkkommunikation", "funkgerät",
    "radio engineer", "radio engineering", "radiocommunication",
    "wireless engineer", "rf engineer", "uhf engineer", "vhf engineer",
    "rfid engineer",
    # Automotive SPICE Spezialist (Software-QM, fordert Python/SPICE-Assessor — nicht Andys Skillset)
    "automotive spice spezialist", "automotive spice expert",
    "spice assessor", "spice-assessor", "intacs assessor",
    "kpi & softwarequalität", "kpi und softwarequalität",
    "softwarequalität automotive", "softwarequalitätssicherung",
    # ERP-Implementierung (SAP/Odoo/Salesforce-Implementation)
    "odoo", "salesforce implementation", "salesforce-implementation",
    "salesforce consultant", "salesforce administrator",
    "microsoft dynamics", "dynamics 365", "ms dynamics",
    "oracle consultant", "oracle implementation",
    "netsuite", "workday consultant", "workday implementation",
    # BESS / Energy Storage (Andy hat keine Batterie-/Storage-Erfahrung als Schwerpunkt)
    " bess ", "(bess)", "bess (", "bess project", "battery energy storage",
    "energy storage manager", "battery storage", "storage system manager",
    "manager (bess)", "project manager bess",
    # Bau / Immobilien-Beratung — auch wenn nicht in TITLE_BLOCK ist
    "drees & sommer", "drees und sommer", "drees+sommer",
    "drees sommer", "drees-sommer",
    "bernard gruppe", "bernard zt",
    "implenia", "strabag", "hochtief", "ed. züblin", "zueblin",
    "goldbeck", "max bögl", "leonhard weiss", "porr ag",
    # Software-Insurance / IT-Insurance
    "msg nexinsure", "nexinsure",
    "insurance consultant", "versicherungsberater software",
    # ÖPNV / DB-Subsidiaries verschärft (zusätzlich zu bestehender DB-Sperre)
    "db netz", "db engineering", "db cargo", "db schenker",
    "deutsche bahn ag",
    "fahrgastinformation",
    # Bau-Projektsteuerung / Baurealisierung
    "baurealisierung", "bauüberwachung", "bauleitung",
    "tga-planung", "tga planung", "tga-projektleitung",
    "hochbauprojekt", "wohnbauprojekt", "infrastrukturprojekt bau",
    "projektsteuerer hochbau", "projektsteuerer tiefbau",
    # NEU 2026-06-01: Bau-/Bahn-Begriffe die durch die Titel-Blacklist rutschten
    "bauherrenvertreter", "bauherrenvertretung", "geotechnik", "spezialtiefbau",
    "schienenbau", "verkehrsanlagen", "ingenieurbau", "schlüsselfertig",
    "bahnbau", "siedlungswasser", "kanalbau", "straßenbau", "strassenbau",
    "gleisbau", "oberleitung", "fahrleitung",
    # IT-/SW-Teilprojektleitung (Andy ist Hardware-/GFZ-PM, NICHT IT)
    "it-teilprojektleiter", "it- teilprojektleiter", "it teilprojektleiter",
    "it-teilprojektleitung", "softwareprojektleiter", "software-projektleiter",
    # Aerospace-Raumfahrt (Andy ist Aero-Engines = MTU OK, aber nicht reine Raumfahrt-PM)
    # → NICHT geblockt, MTU ist Wunschfirma. Nur Generika ausschließen.
    "satellite engineer", "satellitenentwickl", "raumfahrtingenieur",
    # Generische Software-Implementation (klares Software-Profil)
    "implementation specialist software", "software implementation",
    "softwareimplement",
    # Banking / FinTech-PM (zu IT-lastig)
    "fintech project manager", "banking project manager",
    "core banking", "kernbank",
    # ---------- NEU 2026-05-28 (Andy): Consulting komplett raus ----------
    # Andy: "Ich sehe Consultingstellen bei Automotive, egal wo. Ich will nix mit Consulting zu tun haben."
    # ABER: KI-Consultant / AI Consultant / AI Project Manager bleiben erlaubt (via TITLE_BOOST)
    # → Spezifische Consulting-Titel blocken, allgemeines "consultant" auch
    "business consultant", "strategy consultant", "management consultant",
    "process consultant", "people consultant", "transformation consultant",
    "principal consultant", "consulting director", "consulting partner",
    "consulting manager", "senior consulting",
    "manager consulting", "associate consultant", "consultant associate",
    "consulting analyst", "analyst consulting",
    "junior consultant", "consultant junior",
    # ACHTUNG: KEINE generischen "(m/w/d)"-Suffixe hier, weil KI-Berater/AI-Consultant sonst getroffen
    "unternehmensberater", "managementberater", "strategieberater",
    "prozessberater", "transformationsberater",
    "automotive consultant", "automotive berater",
    "mobility consultant", "mobility berater",
    "technical consultant", "technischer berater",
    "implementation consultant", "implementierungsberater",
    "sap consultant", "salesforce consultant", "oracle consultant",
    # ---------- NEU 2026-06-01 (Andy-Feedback #2, HART) ----------
    # Andy: "Wenn ich nochmal sowas sehe, spinne ich komplett." Kein Vertrieb, keine Software-
    # Entwicklung, kein Testing, kein QM/Qualität, KEIN Consulting (auch KI-Consultant), keine
    # Assistenz/Labor, keine Teilzeit, kein Marketing/Loyalty.
    # --- Vertrieb (Andy ist KEIN Vertriebler) ---
    "vertrieb", "vertriebsingenieur", "sales engineer", "vertriebsmanager",
    "außendienst", "aussendienst", "kundenbetreuung", "kundenberater",
    "vertriebsmitarbeiter", "inside sales", "pre-sales", "presales", "pre sales",
    # --- Software-Entwicklung (Andy ist KEIN Softwareentwickler; "developer" NICHT pauschal,
    #     sonst fliegt Produktentwickler/Product Developer mit) ---
    "softwareentwickl", "software-entwickl", "programmierer", "webentwickl",
    "app-entwickl", "app developer", "web developer", "coder",
    # --- Testing/Absicherung ---
    "pentester", "it-tester", "it tester", "testautomat", "absicherungsingenieur",
    "validierungsingenieur", "verifikationsingenieur",
    # --- Qualität/QM (Andy ist KEIN Qualitätsmanager) ---
    "qualitätsmanager", "quality manager", "quality engineer", "qualitätsingenieur",
    "softwarequalität", "qualitätssicherung", "qmb ", "qm-manager", "qs-ingenieur",
    "qualitätsplaner",
    # --- Consulting (Andy will GAR KEIN Consulting, auch KI-Consultant raus) ---
    # "consult" als Kurzform fängt consultant/consulting/bauconsult/X-Consult GmbH alle auf einmal
    "consult", "consultant", "consulting", "berater", "beraterin", "beratung", "advisory",
    "personalberatung",
    # --- Assistenz/Labor (Andy ist Senior, keine Assistenz) ---
    "assistent", "assistentin", "assistenz", "laborant", "laborassist",
    "technische assist", "technischer assist",
    # --- Teilzeit / Hilfskraft (Andy will Vollzeit) ---
    "teilzeit", "part-time", "part time", "reinigungskraft", "minijob", "geringfügig",
    "aushilfe", "hilfskraft",
    # --- Marketing/Loyalty/CRM (Andy ist kein Marketing-PM) ---
    "loyalty", "marketing services", "crm manager", "kampagnenmanage", "brand manager",
]

# ===== DESCRIPTION-LEVEL HARD BLOCK (sicherheits-net wenn Title nicht klar) =====
DESC_BLOCK_STRICT = [
    "etcs/dstw", "stellwerks", "leit- und sicherungstechnik",  # Bahn klar
    "marineschiffbau",
    "iva (intravaskuläre", "intravenös",  # medizinisch
    # NEU 2026-05-28 (Andy): Funk/Radio im Description-Block
    "flugfunkanlage", "flugfunkgerät", "vor/uhf-funk", "tactical radio",
    "voip-implementierung", "voip implementation",
    "satellitenkommunikation", "satellite communication systems",
    # Software-SPICE-Assessor-Beschreibung
    "automotive spice assessment", "spice assessment",
    # Bau-spezifische Beschreibungs-Trigger
    "leistungsphasen 1-9", "leistungsphasen 1 bis 9", "hoai-leistungsphase",
    "vob-leistung", "vob/b", "honorarordnung architekten",
]

# ===== POSITIVE BOOST (Score, höhere Werte = stärker passt zu Andy) =====
TITLE_BOOST = {
    # Top-Tier 25 (Andy IST das)
    "ki-manager": 25, "ki manager": 25, "ai project manager": 25,
    "se-teamleiter": 25, "se teamleiter": 25,
    "ee-package": 25, "ee package": 25,
    "gesamtfahrzeug": 25, "modulleiter": 25, "module leader": 25,
    "baugruppenverantwort": 25,
    "konzeptkonstrukteur": 22, "studio ingenieur": 22,
    # Hoch 18-22
    "senior projektmanager": 22, "senior project manager": 22,
    "senior projektleiter": 22, "senior project leader": 22,
    "senior programm": 20, "senior program manager": 20,
    "agile projektmanager": 20, "agile project manager": 20,
    "ai manager": 22, "ai program": 22, "automation manager": 20,
    "intelligent automation": 22, "ki-projektleiter": 22,
    "senior consultant": 14, "senior berater": 14,
    "scrum master": 12, "product owner": 12,
    # Mittel 14-18
    "projektleiter": 16, "projektmanager": 16, "project manager": 16,
    "programmleiter": 16, "programmmanager": 16,
    "modul ": 12, "komponentenverantwort": 18, "komponenten verantwort": 18,
    "technischer projektleiter": 18, "technischer projektmanager": 18,
    "technical project manager": 18, "technical project lead": 18,
    "ai consultant": 16, "ki-consultant": 16, "ki-berater": 16,
    "ai transformation": 18, "digital transformation": 14,
    # NEU 2026-06-01 (Andy-Fokus: Produktentwicklung / Konzept / Prototyp / Teilprojektleitung
    # in steuernder Rolle). Einzelbegriffe statt Kombi-Keys, damit additiv fair (keine Über-Boosts).
    "teilprojektleit": 20, "subprojektleit": 16, "teil-projektleit": 20,
    "produktentwicklung": 16, "produktentstehung": 16, "product development": 12,
    "vorentwicklung": 16, "konzeptentwicklung": 16, "konzeptingenieur": 16,
    "entwicklungsprojektleiter": 18, "projektingenieur": 10,
    "prototyp": 12, "new product introduction": 16,
    "konstruktionsleit": 18,
    "r&d projektleiter": 14, "r&d-projektleiter": 14, "f&e-projektleiter": 14,
    "serienentwicklung": 10, "industrialisierung": 8, "serienreife": 8,
    # -ung-Varianten (deutsche Stellen nutzen sowohl -leiter als auch -leitung)
    "projektleitung": 16, "se-teamleitung": 25, "se teamleitung": 25,
    "teamleitung": 10, "entwicklungsleitung": 14, "modulleitung": 16,
    # Engineering / Domain
    "fahrzeug": 10, "automotive": 12, "elektrik/elektronik": 12, "elektrik elektronik": 12,
    "after sales": 10, "pmo": 12,
    "nvh": 10, "fahrwerk": 10, "karosserie": 12, "chassis": 12, "cfk": 12,
    "klimatisierung": 10, "i-tafel": 10, "mittelkonsole": 10,
    "smart vehicle": 10, "sdv": 12, "software-defined vehicle": 12,
    "elektromobilität": 10, "ladeinfrastruktur": 8,
    # Gesamtfahrzeug-Bauteile/Fachbereiche (Andy 2026-06-01: jedes Bauteil im GFZ über ALLE
    # Gewerke, nicht nur EE-Package — Zonenarchitektur, Interieur, Exterieur, Sitze, Steuergeräte ...)
    "gesamtfahrzeugentwicklung": 25, "zonenarchitektur": 22, "zonenkonzept": 22,
    "zonenverantwort": 22, "interieur": 14, "exterieur": 14, "interior": 12, "exterior": 12,
    "sitzentwicklung": 16, "sitzsystem": 14, "steuergerät": 16, "steuergeraet": 16,
    "bordnetz": 16, "boardnetz": 16, "kabelbaum": 14, "kabelsatz": 14,
    "cockpit": 12, "instrumententafel": 12, "bauraum": 12, "geometrische integration": 14,
    "thermomanagement": 12, "adas": 12, "fahrerassistenz": 12, "türsystem": 12,
    "verdeck": 12, "karosseriebau": 14, "package engineer": 14,
    # Tools (Bonus)
    "n8n": 6, "make.com": 4,
    "catia": 6, "teamcenter": 6, "windchill": 6, "ms project": 4,
    "ipma": 6, "psm ": 4, "pspo ": 4, "scrum": 4,
    # Branchen-Quereinstieg
    "medtech": 8, "medizintechnik": 8, "pharma": 6, "biotech": 6,
    "robotik": 8, "robotics": 8,
    "energie": 4, "renewable": 4,
    "regulatory affairs": 8,
}

# ===== STANDORT-SCORING =====
LOCATION_BOOST = {
    "münchen": 25, "munich": 25, "muenchen": 25, "80805": 30,
    "ismaning": 18, "garching": 18, "unterschleißheim": 18, "starnberg": 14,
    "remote": 22, "homeoffice": 18, "home office": 18, "home-office": 18,
    "deutschlandweit": 18, "bundesweit": 18, "100 % remote": 30, "100% remote": 30,
    "hybrid": 12,
}

# ===== EXCLUDED COMPANIES =====
COMPANY_BLOCK = [
    "everlast", "evolast", "everlast consulting", "everlast media",
    "aconext",
    # IAV: nur für Initiativ verboten — reguläre Stellen OK
]

# ===== COMPANY DEMOTE (Score-Multiplikator, < 1.0 = niedriger ranken) =====
# Andy 2026-05-28: "Ferchau als Ingenieurdienstleister nicht so hoch priorisieren"
# Engineering-Dienstleister liefern viel Volumen, aber Andy will direkten OEM/Tech-Bezug vorne
COMPANY_DEMOTE = {
    "ferchau": 0.50,        # Andy 2026-06-01: "Ferchau nur Prio 2-3 bei Auto" — −50% Score
    "bertrandt": 0.80,      # auch Engineering-Dienstleister
    "akkodis": 0.85,        # Engineering-Dienstleister, aber mit Automotive-Bezug
    "alten": 0.85,          # Engineering-Dienstleister
    "expleo": 0.80,         # Engineering-Consulting
    "edag": 0.85,           # Engineering-Dienstleister
    "altran": 0.80,         # Engineering-Consulting
    "capgemini engineering": 0.80,
    # NEU 2026-05-28 (Andy: "nix mit Consulting"): reine Strategie/Mgmt-Consulting → hart depriorisieren
    # Sopra Steria / KPMG / Deloitte / Accenture lassen wir bei Default (haben echte KI-Stellen)
    "mckinsey": 0.40,       # reine Mgmt-Consulting
    "boston consulting": 0.40, "bcg": 0.40,
    "bain & company": 0.40, "bain and company": 0.40,
    "roland berger": 0.40,
    "oliver wyman": 0.50,
    "kearney": 0.50, "a.t. kearney": 0.50,
    "horváth": 0.55, "horvath": 0.55,
    "porsche consulting": 0.55,  # auch wenn Andy Porsche mag — Consulting ist Consulting
    "zeb": 0.55,
}

# ===== COMPANY BOOST (Score-Bonus für gezielt gesuchte Firmen) =====
# Andy 2026-05-28: "Firmen wie Rodenstock" — direkte OEM/MedTech/Premium-Firmen pushen
COMPANY_BOOST_FIRMS = {
    "rodenstock": 8,        # München, MedTech-nah
    "sii group": 10,        # Andy hat das selbst gefunden (2026-05-28)
    "sii deutschland": 10,
    "sii ": 8,              # Variante
    "cariad": 10,           # VW-Software-Tochter, Andys VW-Scout-Brücke
    "mtu aero engines": 8,  # München-OEM, Aerospace
    "knorr-bremse": 8,      # München-Tech, Premium
    "brainlab": 8,          # München-MedTech
    "siemens healthineers": 6,
    "linde": 6,             # München-Tech
    "infineon": 6,          # München-Halbleiter
    "rohde & schwarz": 6,   # München-Mess-/Funktechnik
    "wacker": 4,            # München-Chemie
    "osram": 4,             # München-Photonik
    "kuka": 6,              # Augsburg-Robotik
    "fendt": 4,             # Bayern-Maschinenbau
    "siltronic": 4,         # München-Halbleiter
    "p3 group": 6,          # München-Consulting (Initiativ-Anker)
    "appliedai": 8,         # München-KI
    "celonis": 6,           # München-AI
    "personio": 4,          # München-HR-Tech
}

MIN_SCORE_TO_INCLUDE = 22
# NEU 2026-06-01 (Andy): "other"-Kategorie strenger. Das Dashboard zeigt im PM-Tab pm+other
# zusammen, und "other" war zuletzt 159/283 Treffer (Rauschen). Eine Stelle ohne klaren
# Rollen-Match braucht jetzt deutlich mehr Punkte, sonst fliegt sie raus. Echte München-/Remote-
# PM-/Produktentwicklungs-Stellen landen ohnehin in "pm"/"auto"/"ki" und sind nicht betroffen.
OTHER_MIN_SCORE = 40

# ===== NEU 2026-06-01: User-Overrides aus user_overrides.json (persistent im Repo) =====
# Der Crawler liest Andys dauerhafte Blocks/Favoriten bei JEDEM Lauf (auch der GitHub-Cloud-Crawl
# 4x taeglich). So kommt geblockter Muell NIE wieder rein, ueber ALLE Updates hinweg. Andy sagt
# "Firma X raus" oder "Firma Y Favorit" -> Eintrag in user_overrides.json, der Rest laeuft automatisch.
import json as _json
import os as _os
USER_BLOCKED_URLS = []
try:
    with open(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "user_overrides.json"),
              encoding="utf-8") as _f:
        _ov = _json.load(_f)
    for _c in _ov.get("blocked_companies", []):
        _cl = str(_c).strip().lower()
        if _cl and _cl not in COMPANY_BLOCK:
            COMPANY_BLOCK.append(_cl)
    for _t in _ov.get("blocked_title_substrings", []):
        _tl = str(_t).strip().lower()
        if _tl and _tl not in TITLE_BLOCK:
            TITLE_BLOCK.append(_tl)
    USER_BLOCKED_URLS = [str(_u).strip().lower() for _u in _ov.get("blocked_url_substrings", [])
                         if str(_u).strip()]
    for _c in _ov.get("favorite_companies", []):
        _cl = str(_c).strip().lower()
        if _cl:
            COMPANY_BOOST_FIRMS.setdefault(_cl, 10)
except Exception:
    pass


OTHER_CITIES = ["karlsruhe", "stuttgart", "berlin", "hamburg", "köln", "koeln",
                "frankfurt", "düsseldorf", "duesseldorf", "leipzig", "hannover",
                "nürnberg", "nuernberg", "dresden", "essen", "bremen", "ulm",
                "böblingen", "boeblingen", "sindelfingen", "wolfsburg", "ingolstadt",
                "regensburg", "augsburg", "münster", "muenster", "neutraubling",
                "chemnitz", "mannheim", "neubrandenburg", "jena", "erfurt", "rostock",
                "kiel", "lübeck", "luebeck", "saarbrücken", "heilbronn",
                "duisburg", "dortmund", "bochum", "bonn", "wuppertal",
                "potsdam", "magdeburg", "halle", "freiburg", "darmstadt",
                "wiesbaden", "kassel", "aachen", "braunschweig",
                "bielefeld", "münster", "neuss", "leverkusen",
                "mönchengladbach", "moenchengladbach", "gelsenkirchen",
                "salzgitter", "paderborn", "siegen", "trier", "koblenz", "mainz",
                "offenbach", "fulda", "passau", "lindau", "rosenheim"]


def location_passes(location_text: str) -> bool:
    """STRIKT NUR München + 25 km ODER 100 % Remote ortsunabhängig.
    Jede andere DE-Stadt im Standort → RAUS (auch mit Hybrid-Hinweis).
    User-Anweisung 05.05.2026: 'Konzentrier dich auf München, nur auf München.
    25 Kilometer plus maximal. Alles andere 100% remote, ortsunabhängig.'"""
    if not location_text:
        return True  # ohne Standort drin lassen
    loc = location_text.lower()

    # Andere DE-Stadt im Standort → IMMER raus (auch mit Hybrid)
    if any(c in loc for c in OTHER_CITIES):
        return False

    # München-Kern
    munich_ok = any(k in loc for k in ["münchen", "muenchen", "munich", "ismaning", "garching",
                                        "unterschleiß", "starnberg", "fürstenfeldbruck", "80805",
                                        "haar", "putzbrunn", "neubiberg", "gräfelfing",
                                        # NEU 2026-06-01: weitere München-Umland-Orte im 25-km-Radius
                                        "taufkirchen", "parsdorf", "ottobrunn", "unterhaching",
                                        "planegg", "dachau", "feldkirchen", "aschheim", "kirchheim",
                                        "grasbrunn", "vaterstetten", "oberschleiß", "höhenkirchen",
                                        "martinsried", "germering", "gilching", "stockdorf"])
    if munich_ok:
        return True

    # Bayern allgemein OK (Pendler-Kandidat) — aber nur wenn keine andere Stadt drin (geprüft oben)
    if "bayern" in loc:
        return True

    # 100 % ortsunabhängig: nur wenn KEINE Stadt drin steht (geprüft oben)
    if any(k in loc for k in ["100 % remote", "100% remote", "fully remote",
                               "deutschlandweit", "bundesweit", "remote (de)",
                               "remote germany", "remote deutschland",
                               "europe remote", "remote eu"]):
        return True

    # Reines "Remote" / "Homeoffice" / "Hybrid" ohne andere Stadt → OK
    cleaned = re.sub(r"[^\w\s]", " ", loc).strip()
    if cleaned in ("remote", "remote work", "home office", "homeoffice", "hybrid",
                   "telearbeit", "mobiles arbeiten", "remote first", "remote-first"):
        return True

    return False  # Default: lieber raus als Müll


def categorize(title: str, description: str = "", company: str = "") -> str:
    """Ordne Stelle einer Dashboard-Kategorie zu: ki / pm / auto / pharma(=MedTech) / other.

    Andy-Semantik (2026-06-01, Dashboard-Tabs):
      - ki:     KI-/Automatisierungs-Themen passend zu Andys Profil (KI-Manager TÜV, CASA 2035,
                n8n, künstliche Intelligenz allgemein). Breit, nicht nur exakt "KI-Manager".
      - auto:   Automotive / Fahrzeug.
      - pharma: ANZEIGE-LABEL "MedTech". Medizintechnik-Quereinstieg, GROSSZÜGIG: PM/Entwicklungs-
                ingenieur/Konstruktion/Konstruktionsleitung bei Medizintechnik-Firmen. Reines
                Pharma/Chemie/Tabletten gehört NICHT hier rein (kein Andy-Profil). Interner Key
                bleibt "pharma", damit das Frontend-Filter unverändert funktioniert (nur Label
                im Dashboard heißt MedTech).
      - pm:     SAMMELKATEGORIE (Andy nennt es auch "Allgemein"). Alles andere profil-passende,
                was nicht auto/medtech/ki ist: Halbleiter/Chip-PM, Industrie, Maschinenbau,
                Robotik (bis es einen eigenen Tab gibt), IT-/Software-PROJEKTLEITUNG als Steuerung.
                Reines Coding ist bereits über TITLE_BLOCK in score_job hart geblockt.
      - other:  Rest. Wird im Crawler mit OTHER_MIN_SCORE strenger gefiltert.

    company wird mitbewertet, damit MedTech-Gerätehersteller auch erkannt werden, wenn der
    Firmenname nicht im Titel steht.
    """
    text = (title + " " + description + " " + company).lower()

    # 1. KI / Automatisierung (Andys Schwerpunkt-Tab — breit, aber profil-nah; reines
    #    Coding/ML-Engineering ist schon über TITLE_BLOCK draußen)
    if any(k in text for k in ["ki-manager", "ki manager", "ai manager", "ai project",
                                 "ai program", "intelligent automation", "ai consultant",
                                 "ki-consultant", "ki-berater", "künstliche intelligenz",
                                 "artificial intelligence", "genai", "generative ai",
                                 "ai transformation", "ki-transformation", "ki-projektleiter",
                                 "ki-projektmanager", "ki-projekt", "smart vehicle", "sdv",
                                 "automation manager", "prozessautomatisierung",
                                 "workflow-automation", "ki-einführung", "ki-strategie"]):
        return "ki"

    # 2. MedTech (Anzeige "MedTech", Key "pharma"): Medizintechnik-Quereinstieg, großzügig.
    #    Echte Medizintechnik-Gerätehersteller + Device-Begriffe. Reines Pharma/Chemie NICHT.
    if any(k in text for k in ["medtech", "medizintechnik", "medical device", "medizinprodukt",
                                 "medical technology", "medizingerät", "in-vitro", "in vitro diagnost",
                                 "klinische entwicklung", "clinical engineering", "implantat",
                                 "prothes", "dental", "healthcare technology",
                                 # Medizintechnik-Gerätehersteller (auch nur im company-Feld)
                                 "brainlab", "siemens healthineers", "stryker", "rodenstock",
                                 "zeiss meditec", "carl zeiss meditec", "medi-globe", "medi globe",
                                 "biotronik", "ottobock", "b. braun", "b.braun", "aesculap",
                                 "drägerwerk", "draegerwerk", "fresenius medical", "sartorius",
                                 "qiagen", "geuder", "medtronic", "boston scientific", "getinge",
                                 "raumedic", "wl gore", "ziehm imaging"]):
        return "pharma"

    # 3. Automotive / Fahrzeug
    if any(k in text for k in ["automotive", "fahrzeug", "automobil", "ee-package",
                                 "ee package", "gesamtfahrzeug", "se-teamleiter", "se-teamleitung",
                                 "modulleiter", "modulleitung", "baugruppe", "chassis", "karosserie",
                                 "zonenarchitektur", "zonenkonzept", "zonenverantwort", "interieur",
                                 "exterieur", "sitzentwicklung", "sitzsystem", "steuergerät", "bordnetz",
                                 "kabelbaum", "cockpit", "instrumententafel", "thermomanagement",
                                 "fahrerassistenz", "türsystem", "verdeck", "karosseriebau",
                                 "bmw", "audi", "mercedes", "porsche", " vw ", "rolls",
                                 "cariad", "magna", "edag", "bertrandt", "ferchau",
                                 "akkodis", "cognizant mobility", "ce.optimum",
                                 "elektromobilität", "ladeinfrastruktur", "nvh",
                                 "fahrwerk", "antrieb"]):
        return "auto"

    # 4. PM = Sammelkategorie ("Allgemein"): alles andere profil-passende (Halbleiter, Industrie,
    #    Maschinenbau, Robotik, IT-/SW-Projektleitung als Steuerung)
    if any(k in text for k in ["projektmanager", "project manager", "projektleiter",
                                 "programmleiter", "programmmanager", "scrum master",
                                 "product owner", "agile pm", "pmo", "consultant",
                                 "berater", "program manager",
                                 "projektleitung", "teamleitung", "entwicklungsleitung",
                                 "teilprojektleit", "subprojektleit", "produktentwicklung",
                                 "produktentstehung", "vorentwicklung", "konzeptentwicklung",
                                 "konzeptingenieur", "entwicklungsprojektleiter",
                                 "new product introduction", "konstruktionsleit",
                                 "projektingenieur"]):
        return "pm"
    return "other"


def score_job(title: str, description: str, location: str, company: str) -> tuple:
    """Gibt (Match-Score 0-100, list[reasons]) zurück. -1 = hard-block.

    Reason-Strings sind UI-tauglich:
      "✅ Standort München (+25)" / "🎯 Projektmanager (+16)" / "🏢 Rodenstock (+8)"
      "⚠️ Engineering-Dienstleister Ferchau (×0.65)"
    """
    title_lower = html.unescape(title or "").lower()
    company_lower = html.unescape(company or "").lower()
    # NEU 2026-06-01: Branchen-/Firmen-Blacklist greift auf Titel UND Firma. Sonst rutschen
    # Deutsche Bahn / Drees & Sommer / Strabag / Hochtief etc. durch, deren Name nur im
    # company-Feld steht (nicht im Titel). text bekommt company mit (für Boost + DESC-Block).
    title_co = title_lower + " " + company_lower
    text = (title + " " + description + " " + (company or "")).lower()

    # Hard Block — Title + Firma
    for block in TITLE_BLOCK:
        if block in title_co:
            return (-1, [f"🚫 BLOCK_T:{block}"])

    # Hard Block — Description (strict only)
    for block in DESC_BLOCK_STRICT:
        if block in text:
            return (-1, [f"🚫 BLOCK_D:{block}"])

    # Hard Block — Firma
    for block in COMPANY_BLOCK:
        if block in company_lower:
            return (-1, [f"🚫 BLOCK_CO:{block}"])

    # Standort-Filter
    if not location_passes(location):
        return (-1, [f"🚫 BLOCK_LOC:{location[:60]}"])

    # NEU 2026-05-28 (Andy): Consultant/Berater nur OK wenn KI/AI-Bezug im Titel
    # Verhindert "Senior Consultant Automotive", "Berater (m/w/d) Digital" etc.
    has_consultant_word = any(w in title_lower for w in [
        "consultant", "consulting", "berater", "beraterin", "berater:in",
        "beratung", "consultancy",
    ])
    # Regex-basiert: \bai\b / \bki\b matched auch am Titel-Anfang/Ende, plus weitere KI-Signale
    has_ki_signal = bool(re.search(
        r"\b(ai|ki|ml)\b|ai-|ki-|ai/|ki/|"
        r"künstliche?\s*intelligen|intelligent\s*autom|automation\s*manager|"
        r"machine\s*learning|data\s*scien|genai|gen\s*ai|generative\s*ai|"
        r"deep\s*learning|llm|nlp|nlp\s*spec",
        title_lower
    ))
    # Erlaubte Ausnahmen: technical project / senior project manager mit consultant-Bezug
    # (z.B. "AI Technical Project Manager (m/w/d) Consultant") — wenn explizit KI/AI
    if has_consultant_word and not has_ki_signal:
        return (-1, [f"🚫 BLOCK_CONSULTING: Consultant/Berater ohne KI/AI-Bezug"])

    # NEU 2026-06-02: AI/ML-Engineering-Rollen blocken — Andy ist KI-MANAGER/PM, KEIN AI-Coder.
    # BMW lieferte "Senior AI ADAS Engineer", "MLOps Engineer", "Embedded AI Developer",
    # "Principal AI Vehicle Architect", "Entwickler für KI-Prozessautomatisierung" etc.
    # Der Substring "ai engineer" griff nicht, weil Zwischenwörter ("AI ADAS Engineer") ihn brechen.
    # Regel: AI/ML-Signal UND Engineering-Wort (Engineer/Developer/Architect/Scientist/Designer)
    # ABER kein PM-/Manager-/Lead-Wort → reiner Coder → block.
    ai_sig = re.search(r"\b(ai|ki|ml|genai|llm|nlp)\b|künstliche|machine\s*learning|"
                       r"deep\s*learning|mlops|agentic|generative", title_lower)
    eng_sig = re.search(r"\b(engineer|engineering|developer|entwickler|architect|architekt|"
                        r"scientist|designer|researcher|programmer|programmierer)\b", title_lower)
    pm_sig = re.search(r"\b(manager|management|project|projekt|program|programm|portfolio|"
                       r"product\s*owner|lead|leiter|leitung|head|transformation|strateg|"
                       r"consultant|berater|coach|trainer|referent|koordinat)\b", title_lower)
    if ai_sig and eng_sig and not pm_sig:
        return (-1, [f"🚫 BLOCK_AI_ENG: AI/ML-Engineering-Rolle ohne PM-Bezug"])

    # Positiv-Score (Title + Beschreibung)
    score = 0
    reasons = []
    for kw, pts in TITLE_BOOST.items():
        if kw in text:
            score += pts
            # Symbol-Wahl: 🎯 für Top-Match, 🔧 für Tools, 🚗 für Auto, 🤖 für KI
            sym = "🎯"
            if kw in ("n8n", "make.com", "catia", "teamcenter", "windchill", "ms project",
                      "ipma", "psm ", "pspo ", "scrum", "jira", "confluence"):
                sym = "🔧"
            elif kw in ("ki-manager", "ki manager", "ai project manager", "ai manager",
                        "ai program", "intelligent automation", "ai consultant"):
                sym = "🤖"
            elif kw in ("automotive", "fahrzeug", "elektrik/elektronik", "ee-package",
                        "gesamtfahrzeug", "se-teamleiter"):
                sym = "🚗"
            reasons.append(f"{sym} {kw} (+{pts})")

    # Standort-Bonus (nur 1×, größter Hit)
    loc = (location or "").lower()
    best_loc_pts = 0
    best_loc_kw = None
    for kw, pts in LOCATION_BOOST.items():
        if kw in loc and pts > best_loc_pts:
            best_loc_pts = pts
            best_loc_kw = kw
    if best_loc_kw:
        score += best_loc_pts
        reasons.append(f"📍 {best_loc_kw} (+{best_loc_pts})")

    # Company-Boost (Andys gezielte Wunschfirmen) — Firma in Titel ODER Firmenfeld
    for fkw, pts in COMPANY_BOOST_FIRMS.items():
        if fkw in title_co:
            score += pts
            reasons.append(f"🏢 Wunschfirma {fkw.strip().title()} (+{pts})")
            break  # nur eine Firma matched

    # Company-Demote (Eng-Dienstleister) — NEU 2026-06-01: Firma in Titel ODER Firmenfeld.
    # StepStone packt den Firmennamen oft in den Titel (company-Feld leer) → sonst Ferchau-Bug.
    for dkw, mult in COMPANY_DEMOTE.items():
        if dkw in title_co:
            old_score = score
            score = int(score * mult)
            delta = old_score - score
            reasons.append(f"⚠️ Eng-Dienstleister {dkw.title()} (×{mult}, −{delta})")
            break  # nur einer matched

    return (min(score, 100), reasons)


# ===== Helper: BA-Title-Bereinigung =====
def clean_title(title: str) -> str:
    """Entfernt BA-Listenpräfixe wie '1. Ergebnis: '."""
    if not title:
        return ""
    t = re.sub(r"^\d+\.\s*Ergebnis:\s*", "", title.strip())
    t = re.sub(r"^Ergebnis:\s*", "", t)
    return t.strip()
