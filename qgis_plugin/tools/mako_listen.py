"""Erzeugt data/mako/massnahmen_mako.csv aus mas_referenzlisten_v2020a.xlsx (LANUK)."""
import csv, sys, openpyxl
xlsx, ziel = sys.argv[1], sys.argv[2]
wb = openpyxl.load_workbook(xlsx, read_only=True)
rows = list(wb["Ref_EinzelMassnahme"].iter_rows(values_only=True))[1:]
gruppen = {}
for r in rows:
    name, lang, atom, lid, vater = (list(r) + [None] * 5)[:5]
    # Gruppenzeilen: kein Nummernfeld, Vater 0
    if name and vater in (0, None) and not any(ch.isdigit() for ch in str(lang or "")):
        gruppen[lid if lid else lang] = name
with open(ziel, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f, delimiter=";", lineterminator="\n")
    w.writerow(["name", "nr", "gruppe", "atom_id"])
    for r in rows:
        name, lang, atom, lid, vater = (list(r) + [None] * 5)[:5]
        if not name:
            continue
        if name == "keine Massnahme nötig":
            w.writerow([name, "", "keine Massnahme nötig", atom]); continue
        if vater in (0, None):
            continue
        nr = str(lang).strip() if lang is not None else ""
        w.writerow([name.strip(), nr, gruppen.get(vater, ""), atom])
print("ok", len(rows))
