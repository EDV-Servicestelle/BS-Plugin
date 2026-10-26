# -*- coding: utf-8 -*-
"""
Bettet den Formular-Init-Code des Layers 'Fund' in alle Stil-Kopien ein.

Quelle:   styles/fundpunkte_tiere/Fundpunkte/fund_form_init.py
Ziele:    styles/fundpunkte_tiere/Fundpunkte/Fund.qml
          qgis_plugin/data/fundpunkte_tiere/fund.qml        (PostGIS-Setup)
          qgis_plugin/data/fundpunkte_tiere/Fundpunkte.gpkg  (layer_styles,
                                                  maßgeblich für den Wizard)

Zusätzlich wird für QGIS 4.x die Einstellung „Wert merken“ je Feld
geschrieben (<reuseLastValuePolicy>): AllowedDefaultOff für alle
editierbaren Erfassungsfelder, NotAllowed für System- und abgeleitete Felder.
Der alte Block <reuseLastValue> (QGIS 3.x, alle Werte 0) entfällt; QGIS 3.44
liest dann für alle Felder „nicht wiederverwenden“ – wie bisher.

Aufruf (im Repository-Wurzelverzeichnis):
    python tools/form_init_einbetten.py            # nur prüfen, nichts ändern
    python tools/form_init_einbetten.py --schreiben
"""
import argparse
import datetime
import re
import sqlite3
import sys
from pathlib import Path

QUELLE = Path("styles/fundpunkte_tiere/Fundpunkte/fund_form_init.py")
QML_ZIELE = [Path("styles/fundpunkte_tiere/Fundpunkte/Fund.qml"),
             Path("qgis_plugin/data/fundpunkte_tiere/fund.qml")]
GPKG = Path("qgis_plugin/data/fundpunkte_tiere/Fundpunkte.gpkg")
GPKG_TABELLE = "Fund"

# muss zu PIN_AUSGESCHLOSSEN in fund_form_init.py passen
NIE_MERKEN = {"fid", "kennung", "utm_east", "utm_north", "aenderungsdatum",
              "eingabedatum", "projekt_id", "artname_deutsch", "artname_wiss"}

RE_CODE = re.compile(r"(<editforminitcode>)(.*?)(</editforminitcode>)", re.S)
RE_ALT = re.compile(r"[ \t]*<reuseLastValue>.*?</reuseLastValue>[ \t]*\n?",
                    re.S)
RE_NEU = re.compile(r"[ \t]*<reuseLastValuePolicy>.*?</reuseLastValuePolicy>"
                    r"[ \t]*\n?", re.S)
RE_ALT_FELD = re.compile(r'<field\b[^>]*\bname="([^"]+)"')
RE_EDITABLE = re.compile(r"<editable>(.*?)</editable>", re.S)
RE_EDIT_FELD = re.compile(r'<field\b(?=[^>]*\beditable="(\d)")'
                          r'(?=[^>]*\bname="([^"]+)")[^>]*/>')


def policy_block(qml, einrueckung):
    """<reuseLastValuePolicy> aus den Feldern des bisherigen Blocks."""
    alt = RE_ALT.search(qml) or RE_NEU.search(qml)
    if not alt:
        raise ValueError("kein <reuseLastValue>-Block gefunden")
    m = RE_EDITABLE.search(qml)
    editierbar = {n: e == "1" for e, n in RE_EDIT_FELD.findall(m.group(1))} \
        if m else {}
    # Felder des alten Blocks, ergänzt um alle Felder aus <editable>
    namen = list(dict.fromkeys(RE_ALT_FELD.findall(alt.group(0))
                               + list(editierbar)))
    zeilen = [einrueckung + "<reuseLastValuePolicy>"]
    erlaubt = []
    for n in namen:
        ok = n.lower() not in NIE_MERKEN and editierbar.get(n, True)
        if ok:
            erlaubt.append(n)
        zeilen.append('%s  <field name="%s" reuseLastValuePolicy="%s"/>'
                      % (einrueckung, n,
                         "AllowedDefaultOff" if ok else "NotAllowed"))
    zeilen.append(einrueckung + "</reuseLastValuePolicy>")
    return "\n".join(zeilen) + "\n", erlaubt


def umbauen(qml, code):
    if "]]>" in code:
        raise ValueError("Init-Code enthält ']]>' – nicht als CDATA einbettbar")
    if not RE_CODE.search(qml):
        raise ValueError("kein <editforminitcode> gefunden")
    neu = RE_CODE.sub(lambda m: m.group(1) + "<![CDATA[" + code + "]]>"
                      + m.group(3), qml, count=1)
    neu = re.sub(r"<editforminitcodesource>\d</editforminitcodesource>",
                 "<editforminitcodesource>2</editforminitcodesource>", neu)
    neu = re.sub(r"<editforminit>[^<]*</editforminit>",
                 "<editforminit>init</editforminit>", neu)

    alt = RE_ALT.search(neu) or RE_NEU.search(neu)
    einr = re.match(r"[ \t]*", alt.group(0)).group(0) if alt else "  "
    block, erlaubt = policy_block(neu, einr)
    neu = RE_NEU.sub("", neu)                 # vorhandenen 4.x-Block ersetzen
    if RE_ALT.search(neu):
        neu = RE_ALT.sub(lambda m: block, neu, count=1)
    else:                                      # nur 4.x-Block war da
        neu = neu.replace("<dataDefinedFieldProperties",
                          block.lstrip() + einr + "<dataDefinedFieldProperties",
                          1)
    return neu, erlaubt


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--schreiben", action="store_true",
                    help="Änderungen speichern (sonst nur prüfen)")
    args = ap.parse_args()

    if not QUELLE.exists():
        sys.exit("Quelle fehlt: %s (im Repository-Wurzelverzeichnis starten)"
                 % QUELLE)
    code = QUELLE.read_text(encoding="utf-8")
    compile(code, str(QUELLE), "exec")        # Syntax prüfen
    if not code.endswith("\n"):
        code += "\n"

    fehler = 0
    for pfad in QML_ZIELE:
        try:
            qml = pfad.read_text(encoding="utf-8")
            neu, erlaubt = umbauen(qml, code)
        except Exception as e:
            print("FEHLER %s: %s" % (pfad, e))
            fehler += 1
            continue
        status = "unverändert" if neu == qml else "wird aktualisiert"
        print("%-52s %s (%d Felder merkbar)" % (pfad, status, len(erlaubt)))
        if args.schreiben and neu != qml:
            pfad.write_text(neu, encoding="utf-8", newline="")

    con = sqlite3.connect(str(GPKG))
    try:
        zeilen = con.execute(
            "SELECT id, stylename, styleQML FROM layer_styles "
            "WHERE f_table_name = ?", (GPKG_TABELLE,)).fetchall()
        if not zeilen:
            print("FEHLER %s: kein Stil für '%s' in layer_styles"
                  % (GPKG, GPKG_TABELLE))
            fehler += 1
        for sid, name, qml in zeilen:
            try:
                neu, erlaubt = umbauen(qml, code)
            except Exception as e:
                print("FEHLER %s / Stil %s: %s" % (GPKG, name, e))
                fehler += 1
                continue
            status = "unverändert" if neu == qml else "wird aktualisiert"
            print("%-52s %s (%d Felder merkbar)"
                  % ("%s [layer_styles: %s]" % (GPKG.name, name), status,
                     len(erlaubt)))
            if args.schreiben and neu != qml:
                jetzt = datetime.datetime.now(datetime.timezone.utc)
                con.execute(
                    "UPDATE layer_styles SET styleQML = ?, update_time = ? "
                    "WHERE id = ?",
                    (neu, jetzt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
                     sid))
        if args.schreiben:
            con.commit()
    finally:
        con.close()

    if fehler:
        sys.exit("%d Fehler – nichts als erledigt ansehen." % fehler)
    print("Fertig." if args.schreiben
          else "Nur geprüft. Mit --schreiben übernehmen.")


if __name__ == "__main__":
    main()
