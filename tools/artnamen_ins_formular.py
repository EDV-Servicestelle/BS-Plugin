"""
artnamen_ins_formular.py - Artname_deutsch/Artname_wiss ins Formular "Fund"

Problem (Testrueckmeldung Nov. 2026): Die Felder Artname_deutsch und
Artname_wiss bleiben leer. Ihre Standardwerte (fachschalen_config.py,
"Bei Aktualisierung anwenden") sind korrekt gesetzt, aber die Felder stehen
nicht im Drag-and-Drop-Formular. QGIS rechnet Standardwerte mit
"Bei Aktualisierung anwenden" nur fuer Felder neu, die im Formular stehen,
und bei neu angelegten Punkten nicht mehr beim Speichern.

Loesung: Beide Felder schreibgeschuetzt in den Reiter "Systemdaten" der
Formularkonfiguration in layer_styles aufnehmen (direkt nach "Kennung").

Aufruf im Repository-Wurzelordner:

    python tools/artnamen_ins_formular.py            # Probelauf
    python tools/artnamen_ins_formular.py --schreiben

Danach styles/ wie gewohnt mit tools/export_from_gpkg.py nachziehen.
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

GPKG = Path("qgis_plugin/data/fundpunkte_tiere/Fundpunkte.gpkg")
TABELLE = "Fund"
FELDER = ["Artname_deutsch", "Artname_wiss"]
NACH = "Kennung"


def feld_index(con):
    spalten = [r[1] for r in con.execute(f'PRAGMA table_info("{TABELLE}")')]
    geom = {r[0] for r in con.execute(
        "SELECT column_name FROM gpkg_geometry_columns WHERE table_name=?",
        (TABELLE,))}
    return {n: i for i, n in enumerate(c for c in spalten if c not in geom)}


def element(name, index, vorlage):
    """attributeEditorField im Stil der vorhandenen Eintraege."""
    neu = re.sub(r'name="[^"]*"', f'name="{name}"', vorlage, count=1)
    return re.sub(r'index="\d+"', f'index="{index}"', neu, count=1)


def bearbeiten(qml, idx):
    m = re.search(r'<attributeEditorContainer[^>]*name="Systemdaten".*?'
                  r'</attributeEditorContainer>', qml, re.S)
    if not m:
        raise SystemExit("FEHLER: Reiter 'Systemdaten' nicht gefunden")
    block = m.group(0)
    felder = list(re.finditer(
        r'<attributeEditorField [^>]*name="(\w+)"[^>]*>.*?</attributeEditorField>',
        block, re.S))
    vorhanden = {f.group(1) for f in felder}
    fehlen = [f for f in FELDER if f not in vorhanden]
    anker = next((f for f in felder if f.group(1) == NACH), felder[-1])
    zusatz = "".join("\n      " + element(n, idx[n], anker.group(0))
                     for n in fehlen)
    block_neu = block[:anker.end()] + zusatz + block[anker.end():]
    qml = qml[:m.start()] + block_neu + qml[m.end():]

    # schreibgeschuetzt (Systemfelder, Werte kommen aus der Artenliste)
    for n in FELDER:
        muster = rf'<field editable="\d" name="{n}"/>'
        if re.search(muster, qml):
            qml = re.sub(muster, f'<field editable="0" name="{n}"/>', qml)
        else:
            qml = qml.replace("<editable>",
                              f'<editable>\n    <field editable="0" name="{n}"/>', 1)
    return qml, fehlen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gpkg", type=Path, default=GPKG)
    ap.add_argument("--schreiben", action="store_true")
    a = ap.parse_args()
    if not a.gpkg.is_file():
        sys.exit(f"FEHLER: {a.gpkg} nicht gefunden (im Repo-Wurzelordner starten)")
    con = sqlite3.connect(a.gpkg)
    idx = feld_index(con)
    for f in FELDER:
        if f not in idx:
            sys.exit(f"FEHLER: Feld {f} fehlt in Tabelle {TABELLE}")
    zeilen = con.execute("SELECT id, styleName, styleQML FROM layer_styles "
                         "WHERE f_table_name=?", (TABELLE,)).fetchall()
    if not zeilen:
        sys.exit("FEHLER: kein Stil für Fund in layer_styles")
    for sid, sname, qml in zeilen:
        neu, fehlen = bearbeiten(qml, idx)
        if not fehlen and neu == qml:
            print(f"Stil {sid} '{sname}': schon in Ordnung")
            continue
        print(f"Stil {sid} '{sname}': ergänze {fehlen or '-'}, "
              f"setze {', '.join(FELDER)} schreibgeschützt")
        if a.schreiben:
            con.execute("UPDATE layer_styles SET styleQML=? WHERE id=?",
                        (neu, sid))
    if a.schreiben:
        con.commit()
        print("Gespeichert. Danach: python tools/export_from_gpkg.py")
    else:
        print("Probelauf - nichts geändert. Mit --schreiben ausführen.")
    con.close()


if __name__ == "__main__":
    main()
