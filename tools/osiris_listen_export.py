#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Referenzlisten aus der OSIRIS-Datenbank (v_osiris*.mdb) als CSV herausziehen.

Hintergrund: Der GISPAD-Export enthaelt nur Schluessel ("CA4", "NEC0", "str").
Der Klartext steht in OSIRIS, Tabelle `Atom` (ShortName = Schluessel,
LongName = Bezeichnung), gruppiert ueber `BaseList_ID`.

Die .mdb ist 68 MB gross und ein Access-Format - beides ungeeignet, um es im
Plugin mitzufuehren. Deshalb werden die benoetigten Listen einmalig als CSV
abgelegt; der Import liest dann nur noch diese Dateien.

Aufruf (mdbtools erforderlich: apt-get install mdbtools):
    python3 tools/osiris_listen_export.py \\
        --mdb v_osiris54_2025a.mdb --out reflists/osiris
"""

import argparse
import csv
import os
import subprocess
import sys

#: BaseList_ID -> Dateiname. Namen laut Tabelle `Baselist` der OSIRIS-Datenbank.
#: BaseList_ID -> (Dateiname, Bezeichnung, beidseitig)
#
#: `beidseitig` deckt den Sonderfall der Massnahmenliste ab. In den uebrigen
#: Listen steht der Schluessel im ShortName und der Klartext im LongName
#: ("CA4" -> "Flutrasen"). In Liste 15 ist es umgekehrt und ausserdem
#: uneinheitlich: bei rund 40 Prozent der Eintraege steht die MAKO-Nummer im
#: LongName ("Seilzug einsetzen (Wald)" -> "1.20"), beim Rest wiederholt der
#: LongName nur den Text. Welche Form in MASSN.MASSN landet, liess sich
#: mangels Daten nicht pruefen - deshalb werden beide Formen als Schluessel
#: aufgenommen, die auf denselben Klartext zeigen. Eine Richtung zu raten
#: waere schlechter als beide zu bedienen.
LISTEN = {
    # Liste 2 traegt die EU-Codes der Beeintraechtigungen aus dem
    # Natura-2000-Standarddatenbogen (230 = Jagd, 720 = Trittbelastung).
    # GISPAD legt sie in GEFAEHRD.Gef_Code ab.
    "2":  ("beeintraechtigungen.csv", "Natura2000",  False),
    "13": ("biotoptypen.csv",     "13_Biotoptypen",  False),
    "14": ("zusatzcodes.csv",     "14_Zusatzcodes",  False),
    "15": ("massnahmen.csv",      "Massnahmen_MAKO", True),
    "19": ("lebensraumtypen.csv", "Lebensraumtypen", False),
}


def plugin_listen_ordner(start):
    """<plugin>/data/osiris - der Ordner, aus dem das Plugin liest."""
    wurzel = os.path.dirname(os.path.dirname(os.path.abspath(start)))
    for name in sorted(os.listdir(wurzel)):
        pfad = os.path.join(wurzel, name)
        if (os.path.isdir(pfad)
                and os.path.isfile(os.path.join(pfad, "metadata.txt"))
                and os.path.isdir(os.path.join(pfad, "data"))):
            return os.path.join(pfad, "data", "osiris")
    return None


def mdb_export(mdb, tabelle):
    """Eine Tabelle der .mdb als Liste von dicts (ueber mdbtools)."""
    try:
        roh = subprocess.run(["mdb-export", mdb, tabelle],
                             capture_output=True, text=True, timeout=300)
    except FileNotFoundError:
        sys.exit("mdbtools fehlt. Installieren mit:  apt-get install mdbtools\n"
                 "(unter Windows: die Listen auf einem Linux-Rechner erzeugen "
                 "oder aus Access als CSV exportieren)")
    if roh.returncode != 0:
        sys.exit(f"mdb-export fehlgeschlagen: {roh.stderr[:200]}")
    return list(csv.DictReader(roh.stdout.splitlines()))


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mdb", required=True, help="OSIRIS-Datenbank (*.mdb)")
    ap.add_argument("--out", default=None,
                    help="Zielordner (Vorgabe: data/osiris im Plugin)")
    args = ap.parse_args()

    if not os.path.isfile(args.mdb):
        sys.exit(f"Nicht gefunden: {args.mdb}")

    # Die Listen gehoeren ins Plugin: dort findet der Dialog sie ohne
    # Zutun der Anwenderinnen und Anwender. Zwei Ablagen waeren eine
    # Fehlerquelle - eine davon liefe irgendwann hinterher.
    if not args.out:
        args.out = plugin_listen_ordner(__file__)
        if not args.out:
            sys.exit("Plugin-Ordner nicht gefunden - bitte --out angeben.")

    print(f"OSIRIS: {os.path.basename(args.mdb)}")
    atome = mdb_export(args.mdb, "Atom")
    print(f"  Atom-Tabelle: {len(atome)} Zeilen")

    os.makedirs(args.out, exist_ok=True)
    for bl, (datei, bezeichnung, beidseitig) in sorted(LISTEN.items()):
        zeilen = [a for a in atome if a.get("BaseList_ID") == bl]
        # Nach Schluessel sortieren: stabile Reihenfolge, damit eine neue
        # OSIRIS-Fassung einen lesbaren Diff erzeugt statt einer Umwaelzung.
        zeilen.sort(key=lambda a: ((a.get("ShortName") or "").strip(),
                                   (a.get("Atom_ID") or "")))
        # Mehrfach belegte Schluessel sammeln. Zwei Faelle, die man nicht
        # gleich behandeln darf:
        #   - gleiche Bezeichnung, zwei Atom-IDs -> dieselbe Sache, zusammen-
        #     fassen (z. B. "Streuobstwiese" unter zHK2).
        #   - verschiedene Bezeichnungen -> echte Mehrdeutigkeit (z. B. AV1 =
        #     "Ausbreitungskorridor" ODER "Waldmantel"). Hier darf nicht still
        #     der erste Treffer gewinnen; die Zeile wird markiert.
        je_schluessel = {}
        for a in zeilen:
            sn = (a.get("ShortName") or "").strip()
            ln = (a.get("LongName") or "").strip()
            aid = a.get("Atom_ID") or ""
            if not sn:
                continue
            if beidseitig:
                # Hier traegt der ShortName den Klartext. Als Schluessel
                # dienen die MAKO-Nummer (sofern vorhanden) UND der Text.
                text = sn
                schluessel = {sn}
                if ln and ln != sn:
                    schluessel.add(ln)
                for k in schluessel:
                    je_schluessel.setdefault(k, []).append((text, aid))
            else:
                je_schluessel.setdefault(sn, []).append((ln, aid))

        pfad = os.path.join(args.out, datei)
        zusammengefasst = mehrdeutig = ohne_text = 0
        with open(pfad, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, delimiter=";", lineterminator="\n")
            w.writerow(["schluessel", "bezeichnung", "atom_id", "mehrdeutig"])
            for sn in sorted(je_schluessel):
                eintraege = je_schluessel[sn]
                texte = {t for t, _ in eintraege if t}
                if not texte:
                    # Gruppenueberschriften der Liste: Schluesselfeld traegt
                    # den Klartext, Bezeichnung ist leer. Kein Code.
                    ohne_text += 1
                    continue
                if len(eintraege) > 1:
                    if len(texte) == 1:
                        zusammengefasst += 1
                    else:
                        mehrdeutig += 1
                ist_mehrdeutig = 1 if len(texte) > 1 else 0
                # Bei Mehrdeutigkeit alle Lesarten behalten, damit beim Import
                # sichtbar wird, dass eine Entscheidung noetig ist.
                text = (" | ".join(sorted(texte)) if ist_mehrdeutig
                        else sorted(texte)[0])
                w.writerow([sn, text, eintraege[0][1], ist_mehrdeutig])
        teile = [f"{len(je_schluessel) - ohne_text} Eintraege"]
        if zusammengefasst:
            teile.append(f"{zusammengefasst} Dubletten zusammengefasst")
        if mehrdeutig:
            teile.append(f"{mehrdeutig} MEHRDEUTIG")
        if ohne_text:
            teile.append(f"{ohne_text} Gruppenkoepfe uebersprungen")
        print(f"  {bezeichnung:20} -> {pfad}")
        print(f"       {', '.join(teile)}")
        if mehrdeutig:
            for sn in sorted(je_schluessel):
                texte = {t for t, _ in je_schluessel[sn] if t}
                if len(texte) > 1:
                    print(f"       ! {sn}: {' | '.join(sorted(texte))[:90]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
