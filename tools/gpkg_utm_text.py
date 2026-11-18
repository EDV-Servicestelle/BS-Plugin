#!/usr/bin/env python3
"""
gpkg_utm_text.py - Utm_east im GeoPackage "Fundpunkte Tiere" von REAL auf TEXT

Aufruf:
    python gpkg_utm_text.py Fundpunkte.gpkg [weitere.gpkg ...]
    python gpkg_utm_text.py --pruefen Fundpunkte.gpkg     (aendert nichts)
    python gpkg_utm_text.py --ohne-sicherung Fundpunkte.gpkg
                               (im Repository: dort ist git die Sicherung)

Hintergrund: Laut Datenmodell sind beide Koordinatenfelder Text. In der
Vorlage bis Plugin 3.3.3 war Utm_east versehentlich als REAL angelegt; alle
daraus erzeugten GeoPackages haben den Fehler geerbt.

Was passiert:
  - Sicherungskopie <datei>.vor_utm_text (nur wenn noch keine da ist)
  - Spaltentyp von Fund.Utm_east und Fund.Utm_north wird TEXT; die Reihenfolge
    der Spalten bleibt (die Layerstile verweisen auf Spaltennummern)
  - vorhandene Zahlenwerte werden zu Text, unveraendert in den Nachkommastellen

Wiederholbar: Dateien, die schon stimmen, bleiben unberuehrt.
Die Datei darf waehrenddessen nicht in QGIS oder QField geoeffnet sein.
Braucht nur Python 3, keine weiteren Pakete.
"""
import re
import shutil
import sqlite3
import sys

TABELLE = "Fund"
SPALTEN = ("Utm_east", "Utm_north")


def spaltentypen(con):
    return {r[1]: (r[2] or "").upper() for r in con.execute(f'PRAGMA table_info("{TABELLE}")')}


def bearbeiten(pfad, nur_pruefen, sichern=True):
    con = sqlite3.connect(pfad)
    try:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                           (TABELLE,)).fetchone():
            print(f"{pfad}: keine Tabelle {TABELLE} - uebersprungen")
            return True
        typen = spaltentypen(con)
        falsch = [s for s in SPALTEN if s in typen and typen[s] != "TEXT"]
        werte = {s: con.execute(
                     f'SELECT count(*) FROM "{TABELLE}" WHERE typeof("{s}") NOT IN (\'text\',\'null\')'
                 ).fetchone()[0] for s in SPALTEN if s in typen}
        print(f"{pfad}: " + ", ".join(f"{s} {typen.get(s, 'fehlt')}" for s in SPALTEN)
              + f" | Zeilen mit Zahl statt Text: {werte}")
        if not falsch and not any(werte.values()):
            print("  in Ordnung")
            return True
        if nur_pruefen:
            print("  muss angepasst werden")
            return True
    finally:
        con.close()

    if sichern:
        sicherung = pfad + ".vor_utm_text"
        try:
            open(sicherung, "rb").close()
        except FileNotFoundError:
            shutil.copy2(pfad, sicherung)
            print(f"  Sicherung: {sicherung}")

    con = sqlite3.connect(pfad, isolation_level=None)
    try:
        sql = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                          (TABELLE,)).fetchone()[0]
        neu = sql
        for s in falsch:
            # "Utm_east" REAL  ->  "Utm_east" TEXT   (nur der Typ dieser einen Spalte)
            muster = re.compile(r'(["`\[]?%s["`\]]?\s+)[A-Za-z]+(\s*\([^)]*\))?' % re.escape(s))
            neu, n = muster.subn(r"\1TEXT", neu, count=1)
            if n != 1:
                print(f"  Spalte {s} in der Tabellendefinition nicht gefunden - abgebrochen")
                return False
        con.execute("BEGIN IMMEDIATE")
        if neu != sql:
            version = con.execute("PRAGMA schema_version").fetchone()[0]
            con.execute("PRAGMA writable_schema = ON")
            con.execute("UPDATE sqlite_master SET sql = ? WHERE type='table' AND name=?",
                        (neu, TABELLE))
            con.execute("PRAGMA writable_schema = OFF")
            con.execute(f"PRAGMA schema_version = {version + 1}")
        con.execute("COMMIT")
        con.close()

        # Neu oeffnen, damit die geaenderte Definition gilt, dann die Werte umstellen.
        # Die Trigger des Raumindex rufen Funktionen auf, die es nur in GDAL/QGIS
        # gibt; sie werden fuer die Umstellung herausgenommen und danach
        # unveraendert wieder angelegt (die Geometrie wird nicht angefasst).
        con = sqlite3.connect(pfad, isolation_level=None)
        con.execute("BEGIN IMMEDIATE")
        trigger = con.execute("SELECT name, sql FROM sqlite_master "
                              "WHERE type='trigger' AND tbl_name=?", (TABELLE,)).fetchall()
        for name, _ in trigger:
            con.execute(f'DROP TRIGGER "{name}"')
        for s in SPALTEN:
            if s in spaltentypen(con):
                con.execute(f'UPDATE "{TABELLE}" SET "{s}" = CAST("{s}" AS TEXT) '
                            f'WHERE typeof("{s}") NOT IN (\'text\',\'null\')')
        for _, tsql in trigger:
            con.execute(tsql)
        con.execute("COMMIT")
        pruefung = con.execute("PRAGMA integrity_check").fetchone()[0]
        typen = spaltentypen(con)
        rest = sum(con.execute(
                       f'SELECT count(*) FROM "{TABELLE}" WHERE typeof("{s}") NOT IN (\'text\',\'null\')'
                   ).fetchone()[0] for s in SPALTEN if s in typen)
        ok = pruefung == "ok" and rest == 0 and all(typen.get(s, "TEXT") == "TEXT" for s in SPALTEN)
        print("  angepasst" if ok else f"  FEHLER: Pruefung {pruefung}, Rest {rest} - Sicherung zurueckspielen")
        return ok
    except sqlite3.Error as e:
        print(f"  FEHLER: {e} - Datei unveraendert oder Sicherung zurueckspielen")
        return False
    finally:
        con.close()


def main():
    schalter = {"--pruefen", "--ohne-sicherung"}
    args = [a for a in sys.argv[1:] if a not in schalter]
    if not args:
        print(__doc__)
        return 1
    alles_gut = True
    for pfad in args:
        alles_gut &= bearbeiten(pfad, "--pruefen" in sys.argv,
                                sichern="--ohne-sicherung" not in sys.argv)
    return 0 if alles_gut else 1


if __name__ == "__main__":
    sys.exit(main())
