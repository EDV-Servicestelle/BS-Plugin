#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GISPAD-Export (File-Geodatabase) nach GeoPackage - Kommandozeile.

Fuer den Regelfall gibt es den Menuepunkt im Plugin ("GISPAD-Export
uebernehmen ..."). Diese Fassung ist fuer den Stapelbetrieb gedacht, etwa
wenn eine Station mehrere Projektordner auf einmal sichert.

Die Logik liegt NICHT hier, sondern im Plugin (core/gispad.py und
core/gispad_klassen.py). Dieses Skript ist nur die Kommandozeile davor -
sonst gaebe es zwei Fassungen, die auseinanderlaufen koennen.

Drei Betriebsarten:

  --modus beziehungen   Nur berichten: welche Tabellen sind gefuellt, wie
                        haengen sie zusammen. Schreibt nichts. Erster
                        Schritt bei einem unbekannten Export.
  --modus alles         Jede gefuellte Tabelle vollstaendig (Sicherung).
  --modus fachlich      Die fachliche Auswahl einer Objektklasse.

Aufruf:
    python3 tools/gispad_export.py --gdb Export.gdb --modus beziehungen
    python3 tools/gispad_export.py --gdb Export.gdb --modus alles \\
        --out Sicherung.gpkg
    python3 tools/gispad_export.py --gdb Export.gdb --modus fachlich \\
        --klasse BT --out BT.gpkg

Benoetigt GDAL mit OpenFileGDB-Treiber (in QGIS enthalten). Weder GISPAD
noch ODBC noch Access werden gebraucht.
"""

import argparse
import csv
import os
import sys


def plugin_verzeichnis(start):
    """
    Plugin-Ordner finden (enthaelt metadata.txt und core/gispad.py).

    Bewusst nicht auf einen festen Namen festgelegt: der Ordner hiess frueher
    qgis_new_project_plugin_v277 und kann sich wieder aendern.
    """
    wurzel = os.path.dirname(os.path.dirname(os.path.abspath(start)))
    for name in sorted(os.listdir(wurzel)):
        pfad = os.path.join(wurzel, name)
        if (os.path.isdir(pfad)
                and os.path.isfile(os.path.join(pfad, "metadata.txt"))
                and os.path.isfile(os.path.join(pfad, "core", "gispad.py"))):
            return pfad
    return None


def lade_logik():
    """core/gispad_klassen.py des Plugins laden, ohne QGIS."""
    import importlib.util
    plugin = plugin_verzeichnis(__file__)
    if not plugin:
        sys.exit("Plugin-Ordner nicht gefunden (gesucht wird ein Ordner mit "
                 "metadata.txt und core/gispad.py neben 'tools').")
    core = os.path.join(plugin, "core")

    def hole(name):
        spec = importlib.util.spec_from_file_location(
            name, os.path.join(core, f"{name}.py"))
        modul = importlib.util.module_from_spec(spec)
        sys.modules[name] = modul
        spec.loader.exec_module(modul)
        return modul

    hole("gispad")
    return hole("gispad_klassen")


def modus_beziehungen(gk, gdb, bericht=None):
    erg = gk.analysiere(gdb)
    print(f"Gefuellte Layer/Tabellen: {len(erg['gefuellt'])}")
    for name, n in sorted(erg["gefuellt"].items(), key=lambda x: -x[1]):
        kennz = "  (Geometrie)" if name in erg["geometrie"] else ""
        print(f"    {name:24} {n:7}{kennz}")

    if erg["klassen"]:
        print("\nObjektklassen:")
        for k, info in sorted(erg["klassen"].items()):
            print(f"    {k:5} {info['name']:22} {info['objekte']:7} Objekte "
                  f"({', '.join(info['layer'])})")
    else:
        print("\nKeine der bekannten Objektklassen (BT, BK, MAS) gefunden.")
    if erg["unbekannt"]:
        print(f"    ohne Fachprofil: {', '.join(erg['unbekannt'])}")

    print("\nBeziehungen (FKEY -> PKEY, GISPADID-geprueft):")
    zeilen = []
    for kind in sorted(erg["beziehungen"]):
        info = erg["beziehungen"][kind]
        if info["sicher"]:
            print(f"    {kind:24} -> {info['eltern']:20} "
                  f"({info['gleich']} Zeilen)")
            zeilen.append([kind, info["eltern"], info["gleich"], "eindeutig"])
        elif info["kandidaten"]:
            namen = ", ".join(k for k, _g, _o in info["kandidaten"][:6])
            print(f"    {kind:24} -> MEHRDEUTIG: {namen}")
            zeilen.append([kind, "", 0, f"mehrdeutig: {namen}"])
        else:
            print(f"    {kind:24} -> kein Elternteil gefunden")
            zeilen.append([kind, "", 0, "kein Treffer"])

    unklar = sum(1 for z in zeilen if z[3] != "eindeutig")
    if unklar:
        print(f"\n{unklar} Tabelle(n) nicht eindeutig. Das sind in aller "
              f"Regel sehr kleine\nTabellen - bei wenigen Zeilen reichen die "
              f"Daten nicht aus, um zwischen\nKandidaten zu unterscheiden. "
              f"Fuer '--modus alles' ist das ohne Belang.")

    if bericht:
        with open(bericht, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, delimiter=";", lineterminator="\n")
            w.writerow(["tabelle", "eltern", "zeilen", "befund"])
            w.writerows(zeilen)
        print(f"\nBericht: {bericht}")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gdb", required=True, help="Ordner der *.gdb")
    ap.add_argument("--modus", default="fachlich",
                    choices=("beziehungen", "fachlich", "alles"))
    ap.add_argument("--klasse", default="BT",
                    help="Objektklasse fuer --modus fachlich (BT, BK, MAS)")
    ap.add_argument("--out", default=None, help="Ziel-GeoPackage")
    ap.add_argument("--bericht", default=None, help="CSV mit den Befunden")
    ap.add_argument("--ueberschreiben", action="store_true")
    args = ap.parse_args()

    gk = lade_logik()
    if args.modus == "fachlich" and args.klasse not in gk.OBJEKTKLASSEN:
        sys.exit(f"Unbekannte Objektklasse: {args.klasse}  "
                 f"(moeglich: {', '.join(sorted(gk.OBJEKTKLASSEN))})")

    print(f"Geodatabase: {os.path.basename(args.gdb.rstrip('/'))}\n")

    if args.modus == "beziehungen":
        modus_beziehungen(gk, args.gdb, args.bericht)
        return 0

    if not args.out:
        sys.exit("--out fehlt (Ziel-GeoPackage).")
    if os.path.exists(args.out) and not args.ueberschreiben:
        sys.exit(f"Zieldatei existiert schon: {args.out}\n"
                 "  Mit --ueberschreiben neu erzeugen.")

    def melde(p, t):
        print(f"  [{p:3}%] {t}")

    if args.modus == "alles":
        geschrieben = gk.exportiere_alles(args.gdb, args.out, melde)
        befunde = []
    else:
        geschrieben, befunde = gk.exportiere_fachlich(
            args.gdb, args.klasse, args.out, melde=melde)

    print(f"\nGeoPackage: {args.out}")
    for name, n in geschrieben.items():
        print(f"    {name:24} {n:7}")
    print(f"    {'gesamt':24} {sum(geschrieben.values()):7} Datensaetze")
    if befunde:
        print("\nHinweise:")
        for b in befunde:
            print(f"    - {b}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
