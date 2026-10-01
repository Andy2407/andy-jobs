#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dashboard-Syntax-Sperre (NEU 01.10.2026).

Am 30.09.2026 19:25 ging jobsuche_v12.html mit einem Syntaxfehler live (Commit 294ddf4, eine
geloeschte Zeile). Das komplette Dashboard-Skript brach ab, Andy sah "Stand: laedt…" und nichts sonst.
Dieses Skript prueft das Haupt-Skript so, wie der Browser es liest (Ende am ersten "</script"),
mit `node --check`. Exit 1 = NICHT ausliefern.

Aufruf: python3 crawler/dashboard_syntax_gate.py [pfad/zur/jobsuche_v12.html]
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

pfad = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "jobsuche_v12.html"
html = pfad.read_text(encoding="utf-8")
fehler = 0
for m in re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>", html):
    ende = html.lower().find("</script", m.end())
    body = html[m.end():ende]
    if len(body) < 2000:                      # nur das Haupt-Skript, keine Mini-Schnipsel
        continue
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(body)
    r = subprocess.run(["node", "--check", f.name], capture_output=True, text=True)
    zeile0 = html[:m.end()].count("\n")
    if r.returncode != 0:
        fehler += 1
        z = re.search(r":(\d+)\n", r.stderr)
        print(f"SYNTAXFEHLER im Dashboard-Skript, HTML-Zeile {zeile0 + int(z.group(1)) if z else '?'}:\n{r.stderr[:500]}")
    else:
        print(f"Dashboard-Skript ok ({len(body)} Zeichen, ab HTML-Zeile {zeile0 + 1})")
    break                                       # der Browser beendet das Skript am ersten </script
sys.exit(1 if fehler else 0)
