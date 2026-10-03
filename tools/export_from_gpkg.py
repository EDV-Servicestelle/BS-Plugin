#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zieht aus den GeoPackages des Plugins die versionierbaren Textbestandteile
heraus:

  styles/<fachschale>/<gpkg>/<tabelle>.qml   Layerstile aus layer_styles
  datamodel/<fachschale>/<tabelle>.sql  CREATE-TABLE-Anweisungen (DDL)
  reflists/<fachschale>/<gpkg>/<liste>.csv   Inhalte der Referenzlisten

Hintergrund: Die Stile liegen produktiv in der Tabelle `layer_styles` INNERHALB
des GeoPackages und sind dort weder lesbar noch vergleichbar. Genau daraus sind
in der Vergangenheit Abweichungen zwischen `layer_styles` und der freien
QML-Datei entstanden (applyOnUpdate, fehlende Felder nach Schemaaenderungen).
Als Textdateien im Repository werden solche Abweichungen zu sichtbaren Diffs.

Aufruf:
    python3 tools/export_from_gpkg.py --plugin qgis_plugin --out .
    python3 tools/export_from_gpkg.py --plugin qgis_plugin --out . --pruefen

--pruefen schreibt nichts, sondern meldet nur Abweichungen zwischen den
GeoPackages und den bereits abgelegten Textdateien (fuer die CI geeignet,
Rueckgabewert 1 bei Abweichung).
"""

import argparse
import csv
import os
import sqlite3
import sys

# Tabellen, die zu keiner Referenzliste gehoeren
KEINE_REFLISTE = {"gpkg_contents", "gpkg_ogr_contents", "layer_styles",
                  "sqlite_sequence"}


def gpkgs_finden(plugin_dir):
    """Alle GeoPackages unterhalb von <plugin>/data finden."""
    basis = os.path.join(plugin_dir, "data")
    treffer = []
    for wurzel, _dirs, dateien in os.walk(basis):
        for d in dateien:
            if d.lower().endswith(".gpkg"):
                treffer.append(os.path.join(wurzel, d))
    return sorted(treffer)


def fachschale_von(pfad, plugin_dir):
    """Ordnername unterhalb von data/ als Fachschale, sonst '_allgemein'."""
    rel = os.path.relpath(pfad, os.path.join(plugin_dir, "data"))
    teile = rel.split(os.sep)
    return teile[0] if len(teile) > 1 else "_allgemein"


def tabellen(con):
    return [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'gpkg_%' AND name NOT LIKE 'sqlite_%' "
        "AND name NOT LIKE 'rtree_%' ORDER BY name")]


def stile_lesen(con):
    """{tabellenname: styleQML} aus layer_styles, falls vorhanden."""
    try:
        rows = con.execute(
            "SELECT f_table_name, styleQML FROM layer_styles "
            "ORDER BY id").fetchall()
    except sqlite3.OperationalError:
        return {}
    # bei mehreren Stilen je Tabelle gewinnt der zuletzt gespeicherte
    return {t: q for t, q in rows if q}


def ddl_lesen(con):
    """{tabellenname: CREATE-Anweisung}."""
    return {r[0]: (r[1] or "") + ";\n" for r in con.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'gpkg_%' AND name NOT LIKE 'sqlite_%' "
        "AND name NOT LIKE 'rtree_%' ORDER BY name")}


def refliste_lesen(con, tabelle):
    """Inhalt einer Referenzliste als (spalten, zeilen) - ohne fid."""
    spalten = [r[1] for r in con.execute(f'PRAGMA table_info("{tabelle}")')
               if r[1] != "fid"]
    if not spalten:
        return None, None
    quoted = ",".join(f'"{s}"' for s in spalten)
    # Ueber ALLE Spalten sortieren: eine Sortierung nur nach der ersten
    # Spalte waere bei Dubletten nicht reproduzierbar und erzeugte
    # Schein-Diffs im Repository.
    order = ",".join(str(i + 1) for i in range(len(spalten)))
    zeilen = con.execute(
        f'SELECT {quoted} FROM "{tabelle}" ORDER BY {order}').fetchall()
    return spalten, zeilen


def ist_refliste(con, tabelle):
    """Referenzlisten sind Attributtabellen ohne Geometrie."""
    if tabelle in KEINE_REFLISTE:
        return False
    spalten = {r[1].lower() for r in con.execute(f'PRAGMA table_info("{tabelle}")')}
    return "geom" not in spalten and "geometry" not in spalten


def schreiben(pfad, inhalt, pruefen, abweichungen):
    """Datei schreiben oder im Pruefmodus nur vergleichen."""
    if pruefen:
        if not os.path.exists(pfad):
            abweichungen.append(f"fehlt im Repository: {pfad}")
            return False
        with open(pfad, encoding="utf-8") as fh:
            if fh.read() != inhalt:
                abweichungen.append(f"weicht vom GeoPackage ab: {pfad}")
                return False
        return True
    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    with open(pfad, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(inhalt)
    return True


def csv_text(spalten, zeilen):
    import io
    puffer = io.StringIO()
    w = csv.writer(puffer, delimiter=";", lineterminator="\n")
    w.writerow(spalten)
    w.writerows(zeilen)
    return puffer.getvalue()


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plugin", required=True,
                    help="Verzeichnis des Plugins (enthaelt data/)")
    ap.add_argument("--out", default=".",
                    help="Wurzel fuer styles/, datamodel/, reflists/")
    ap.add_argument("--pruefen", action="store_true",
                    help="nur vergleichen, nichts schreiben (fuer die CI)")
    ap.add_argument("--max-mb", type=float, default=5.0,
                    help="GeoPackages ueber dieser Groesse ueberspringen "
                         "(Fachdaten, keine Projektvorlagen)")
    args = ap.parse_args()

    abweichungen = []
    anzahl = {"stile": 0, "ddl": 0, "listen": 0, "uebersprungen": 0}

    for gpkg in gpkgs_finden(args.plugin):
        mb = os.path.getsize(gpkg) / 1024 / 1024
        if mb > args.max_mb:
            print(f"  übersprungen ({mb:.0f} MB): {gpkg}")
            anzahl["uebersprungen"] += 1
            continue

        fach = fachschale_von(gpkg, args.plugin)
        name = os.path.splitext(os.path.basename(gpkg))[0]
        con = sqlite3.connect(gpkg)

        for tab, qml in stile_lesen(con).items():
            ziel = os.path.join(args.out, "styles", fach, name, f"{tab}.qml")
            schreiben(ziel, qml if qml.endswith("\n") else qml + "\n",
                      args.pruefen, abweichungen)
            anzahl["stile"] += 1

        ddl = ddl_lesen(con)
        if ddl:
            text = ("-- Erzeugt aus %s\n-- Nicht von Hand aendern: "
                    "tools/export_from_gpkg.py\n\n" % os.path.basename(gpkg))
            text += "\n".join(ddl[t] for t in sorted(ddl))
            ziel = os.path.join(args.out, "datamodel", fach, f"{name}.sql")
            schreiben(ziel, text, args.pruefen, abweichungen)
            anzahl["ddl"] += 1

        for tab in tabellen(con):
            if not ist_refliste(con, tab):
                continue
            spalten, zeilen = refliste_lesen(con, tab)
            if not spalten:
                continue
            ziel = os.path.join(args.out, "reflists", fach, name, f"{tab}.csv")
            schreiben(ziel, csv_text(spalten, zeilen), args.pruefen,
                      abweichungen)
            anzahl["listen"] += 1

        con.close()

    print(f"\nStile: {anzahl['stile']}   DDL: {anzahl['ddl']}   "
          f"Referenzlisten: {anzahl['listen']}   "
          f"übersprungen: {anzahl['uebersprungen']}")

    if args.pruefen:
        if abweichungen:
            print("\nAbweichungen zwischen GeoPackage und Repository:")
            for a in abweichungen:
                print("   -", a)
            print("\nBitte 'python3 tools/export_from_gpkg.py --plugin "
                  "qgis_plugin --out .' ausführen und die Änderungen "
                  "committen.")
            return 1
        print("Repository und GeoPackages stimmen überein.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
