#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
synonyme.json und die Tabelle Arten_Synonyme im Referenz-GeoPackage
abgleichen - und die Sicht Arten_Suche anlegen.

Warum dieses Werkzeug umgebaut wurde
------------------------------------
Die erste Fassung hat die Tabelle jedes Mal neu gebaut: DROP TABLE, dann
alles aus synonyme.json hineinschreiben. Das ist falsch, seit es
`synonyme_dialog.py` gibt. Die Stationen tragen dort eigene Synonyme ein,
mit Bearbeiter und Datum in `erfasst_von` / `erfasst_am`, und im
GeoPackage stehen ausserdem sieben Zeilen aus der Nachtragsrunde, die
synonyme.json nie gekannt hat. Ein Neuaufbau haette all das stillschweigend
geloescht.

Dieses Werkzeug loescht darum nichts von sich aus. Es meldet, und es
ergaenzt - und zwar nur Zeilen, die es selbst angelegt haben koennte.

Was "selbst angelegt" heisst
----------------------------
Eine Zeile gilt als maschinell gepflegt, wenn ihre Spalte `quelle` mit
"synonyme.json" beginnt. Nur solche Zeilen darf --abgleichen aendern.
Alles andere - Dialogeingaben, "Nachtrag offene Suchterme", Importe der
Station - bleibt unberuehrt und wird nur berichtet.

Wege
----
  --pruefen      (Vorgabe) Nur Bericht. Rueckgabewert 1 bei Abweichung,
                 damit die CI anschlagen kann.
  --csv DATEI    Schreibt die fehlenden Eintraege als zweispaltige CSV
                 (Suchbegriff;Zielart). Genau dieses Format liest der
                 Import-Tab von synonyme_dialog.py: mit Trockenlauf,
                 Pruefung der Zielart und Eintrag von Bearbeiter und
                 Datum. Das ist der sauberere Weg, weil der Bestand dann
                 nur ueber einen einzigen Schreibpfad waechst.
  --abgleichen   Schreibt direkt ins GeoPackage: fehlende Zeilen anlegen,
                 veraltete Ziele maschinell gepflegter Zeilen berichtigen.
                 Loescht nichts.
  --entfernen    Nur zusammen mit --abgleichen: loescht zusaetzlich die
                 maschinell gepflegten Zeilen, die synonyme.json nicht
                 mehr kennt. Fremde Zeilen bleiben auch dann stehen.
  --sicht        Legt die Sicht Arten_Suche an oder erneuert sie. Beruehrt
                 keine Tabelle.

Aufruf ohne Pfadangaben sucht den Plugin-Ordner selbst:
    python3 tools/synonyme_in_gpkg.py
    python3 tools/synonyme_in_gpkg.py --csv nachtrag.csv
    python3 tools/synonyme_in_gpkg.py --abgleichen --sicht
"""

import argparse
import csv
import datetime
import json
import os
import sqlite3
import sys

#: Tabellen- und Spaltennamen sind NICHT frei gewaehlt: Das QField-Plugin
#: "Artenname Synonym Search" (FeelGood GeoSolutions) liest genau diese
#: Namen. In seiner main.qml stehen sie als
#:     synonymLayerName: "Arten_Synonyme"
#:     synonymTermField: "synonym_term"
#:     synonymRefField:  "akzeptiert_entityid"
#: Wer sie hier aendert, nimmt der Felderfassung die Synonymsuche - ohne
#: dass es am Rechner auffaellt.
SYNONYM_TABELLE = "Arten_Synonyme"
SPALTE_SYNONYM = "synonym_term"
SPALTE_ZIEL = "akzeptiert_entityid"
SUCH_SICHT = "Arten_Suche"

#: Kennung in der Spalte `quelle`, an der maschinell gepflegte Zeilen zu
#: erkennen sind. Die vorhandenen Zeilen tragen "synonyme.json (Voegel)"
#: und teils den Zusatz "[korrigiert]"; beides faengt dieses Praefix.
QUELLE_PRAEFIX = "synonyme.json"

#: Wert der Spalte `art` in den vorhandenen Zeilen. Die Spalte bezeichnet
#: hier die Zeilenrolle, nicht die Namensart.
ART_WERT = "Synonym"

#: Versatz der fid in der Sicht. Arten hat rund 13.300 Zeilen; der Abstand
#: ist gross genug, dass sich die Bereiche nicht ueberlappen, auch wenn die
#: Artenliste waechst. Ueberlappende fid lassen QGIS zwei verschiedene
#: Zeilen fuer dieselbe halten.
FID_VERSATZ = 10000000

PFEIL = " → "


def normalisiere(s):
    """Dieselbe Normalisierung wie core/import_core.py."""
    return (s.lower().strip()
            .replace("ä", "ae").replace("ö", "oe")
            .replace("ü", "ue").replace("ß", "ss"))


def plugin_verzeichnis(start):
    """Plugin-Ordner finden (metadata.txt + data/)."""
    wurzel = os.path.dirname(os.path.dirname(os.path.abspath(start)))
    for name in sorted(os.listdir(wurzel)):
        pfad = os.path.join(wurzel, name)
        if (os.path.isdir(pfad)
                and os.path.isfile(os.path.join(pfad, "metadata.txt"))
                and os.path.isdir(os.path.join(pfad, "data"))):
            return pfad
    return None


def spalten(con, tabelle):
    return [r[1] for r in con.execute(f'PRAGMA table_info("{tabelle}")')]


def gueltige_gruppen(con):
    """
    listitemid aller Artengruppen.

    Der Artengruppen-Filter des Formulars lautet
    "parentid" = current_value('Artengruppe'), und das Feld Artengruppe
    speichert die listitemid aus Artengruppen - nicht die entityid. Nur
    Arten unter einer dieser listitemid sind im Formular ueberhaupt
    erreichbar.
    """
    return {r[0] for r in con.execute(
        "SELECT listitemid FROM Artengruppen WHERE listitemid IS NOT NULL")}


def lies_arten(con):
    """
    (entityid, parentid) je normalisiertem Namen, wissenschaftlich und
    deutsch.

    Beschraenkt auf Arten unter einer gueltigen Artengruppe. Das
    Referenzkataster fuehrt dieselbe Art mehrfach: einmal unter ihrer
    Artengruppe und einmal unter oekologischen Sammelgruppen (Bodenbrueter,
    Greife, Heidearten). Zeilen aus diesen Sammelgruppen taugen nicht als
    Ziel - das Formular zeigt sie unter keiner Artengruppe an.
    """
    gruppen = gueltige_gruppen(con)
    nach_name = {}
    for eid, term, name_de, parentid in con.execute(
            "SELECT entityid, term, Name_deutsch, parentid FROM Arten").fetchall():
        if parentid not in gruppen:
            continue
        for roh in (term, name_de):
            if not roh:
                continue
            nach_name.setdefault(normalisiere(roh), []).append(
                (int(eid), term or "", name_de or "", parentid or ""))
    return nach_name


def baue_soll(json_pfad, nach_name):
    """
    (soll, ungeloest, bekannt) aus synonyme.json.

    soll:      {(normalisierter Begriff, parentid): Satz}
    ungeloest: Eintraege, deren Ziel unter keiner Artengruppe auffindbar ist.
    bekannt:   alle Begriffe, die in synonyme.json ueberhaupt vorkommen -
               auch die, fuer die keine Zeile gebaut wird. Ohne diese Menge
               wuerde --entfernen Zeilen loeschen, deren Begriff die Datei
               noch fuehrt.

    Eine Art kann unter zwei Artengruppen stehen (Sikawild, wildernde
    Hauskatze). Dann bekommt das Synonym eine Zeile je parentid, sonst
    verschwindet es hinter dem Artengruppen-Filter des Formulars. Das
    QField-Plugin fasst solche Dubletten selbst zusammen.
    """
    with open(json_pfad, encoding="utf-8") as fh:
        kategorien = json.load(fh)["synonyme"]

    soll, ungeloest, bekannt = {}, [], set()
    for kategorie, eintraege in kategorien.items():
        for synonym, ziel in eintraege.items():
            bekannt.add(normalisiere(synonym))
            treffer = nach_name.get(normalisiere(ziel))
            if not treffer:
                ungeloest.append((kategorie, synonym, ziel))
                continue
            # Zeigt das Synonym auf sich selbst, bringt die Zeile nichts:
            # der Direkttreffer in Arten greift ohnehin vorher.
            if normalisiere(synonym) == normalisiere(ziel):
                continue
            for eid, term, name_de, parentid in treffer:
                anzeige = f"{name_de} – {term}" if name_de else term
                soll[(normalisiere(synonym), parentid)] = {
                    "term": synonym,
                    "entityid": eid,
                    "parentid": parentid,
                    "ziel": anzeige,
                    "quelle": f"{QUELLE_PRAEFIX} ({kategorie})",
                }
    return soll, ungeloest, bekannt


def lies_ist(con):
    """
    Bestand der Tabelle: {(normalisierter Begriff, parentid): [Saetze]}.

    Eine Liste je Schluessel, nicht ein Satz: "gruenfrosch" und
    "grünfrosch" stehen als zwei Zeilen in der Tabelle, werden aber zum
    selben Schluessel normalisiert. Wuerde hier eine Zeile die andere
    verdraengen, waere sie fuer Bericht und Abgleich unsichtbar - und ein
    falsches Ziel bliebe in der verdeckten Zeile stehen.

    None, wenn die Tabelle fehlt.
    """
    if not con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (SYNONYM_TABELLE,)).fetchone():
        return None
    vorhanden = spalten(con, SYNONYM_TABELLE)
    felder = ["fid", SPALTE_SYNONYM, SPALTE_ZIEL, "parentid"]
    felder += [f for f in ("quelle", "erfasst_von", "erfasst_am")
               if f in vorhanden]
    sql = ", ".join(f'"{f}"' for f in felder)
    ist = {}
    for zeile in con.execute(
            f'SELECT {sql} FROM "{SYNONYM_TABELLE}"').fetchall():
        satz = dict(zip(felder, zeile))
        satz["term"] = satz.pop(SPALTE_SYNONYM) or ""
        satz["entityid"] = satz.pop(SPALTE_ZIEL)
        ist.setdefault(
            (normalisiere(satz["term"]), satz.get("parentid") or ""),
            []).append(satz)
    return ist


def maschinell(satz):
    """Darf --abgleichen diese Zeile anfassen?"""
    return str(satz.get("quelle") or "").startswith(QUELLE_PRAEFIX)


def vergleiche(soll, ist, bekannt):
    """
    (fehlt, falsches_ziel, fremd_mit_falschem_ziel, ueberzaehlig, fremd)

    Jede Zeile wird einzeln beurteilt, auch wenn mehrere auf denselben
    Schluessel fallen. Mehrfachzeilen sind kein Fehler: das Formular zeigt
    beide Schreibweisen, und das QField-Plugin fasst sie zusammen.
    """
    fehlt, falsch, fremd_falsch, ueberzaehlig, fremd = [], [], [], [], []
    for schluessel, s in sorted(soll.items()):
        zeilen = ist.get(schluessel)
        if not zeilen:
            fehlt.append(s)
            continue
        for i in zeilen:
            if int(i["entityid"] or 0) != s["entityid"]:
                (falsch if maschinell(i) else fremd_falsch).append((s, i))
    for schluessel, zeilen in sorted(ist.items()):
        # Begriffe, die synonyme.json noch fuehrt - auch ohne eigene Zeile,
        # etwa weil das Synonym auf sich selbst zeigt - sind nicht
        # ueberzaehlig.
        if schluessel in soll or schluessel[0] in bekannt:
            continue
        for i in zeilen:
            (ueberzaehlig if maschinell(i) else fremd).append(i)
    return fehlt, falsch, fremd_falsch, ueberzaehlig, fremd


def bericht(con, soll, ist, ungeloest, bekannt):
    namen = {int(r[0]): (r[1] or "", r[2] or "") for r in con.execute(
        "SELECT entityid, term, Name_deutsch FROM Arten").fetchall()}

    def zeige(eid):
        t, d = namen.get(int(eid or 0), ("?", ""))
        return f"{d} – {t}" if d else t

    fehlt, falsch, fremd_falsch, ueberzaehlig, fremd = vergleiche(
        soll, ist, bekannt)
    anz_ist = sum(len(z) for z in ist.values())
    doppelt = {k: z for k, z in ist.items() if len(z) > 1}
    print(f"  synonyme.json: {len(soll)} Zeilen (Begriff je Artengruppe)")
    print(f"  {SYNONYM_TABELLE}: {anz_ist} Zeilen")
    if doppelt:
        print(f"\n  gleicher Begriff nach Normalisierung ({len(doppelt)}) - "
              f"nicht falsch, nur mehrfach:")
        for k, z in sorted(doppelt.items()):
            print("     " + ", ".join(repr(i["term"]) for i in z)
                  + f" -> {zeige(z[0]['entityid'])}")

    if ungeloest:
        print(f"\n  Ziel unter keiner Artengruppe auffindbar ({len(ungeloest)}):")
        for kat, syn, ziel in ungeloest:
            print(f"     [{kat}] {syn!r} -> {ziel!r}")
    if fehlt:
        print(f"\n  fehlt in der Tabelle ({len(fehlt)}):")
        for s in fehlt:
            print(f"     {s['term']!r} -> {s['ziel']}")
    if falsch:
        print(f"\n  anderes Ziel, Zeile maschinell gepflegt ({len(falsch)}):")
        for s, i in falsch:
            print(f"     {s['term']!r}: Tabelle {zeige(i['entityid'])!r}"
                  f" | JSON {s['ziel']!r}")
    if fremd_falsch:
        print(f"\n  anderes Ziel, Zeile NICHT maschinell ({len(fremd_falsch)})"
              f" - bleibt unberuehrt:")
        for s, i in fremd_falsch:
            print(f"     {s['term']!r}: Tabelle {zeige(i['entityid'])!r}"
                  f" [{i.get('quelle')}] | JSON {s['ziel']!r}")
    if ueberzaehlig:
        print(f"\n  nur in der Tabelle, maschinell gepflegt "
              f"({len(ueberzaehlig)}):")
        for i in ueberzaehlig:
            print(f"     {i['term']!r} -> {zeige(i['entityid'])}")
    if fremd:
        print(f"\n  nur in der Tabelle, eigener Bestand ({len(fremd)}) - "
              f"bleibt in jedem Fall:")
        for i in fremd:
            print(f"     {i['term']!r} -> {zeige(i['entityid'])}"
                  f"  [{i.get('quelle')}]")
    return fehlt, falsch, fremd_falsch, ueberzaehlig, fremd


def schreibe_csv(pfad, fehlt):
    """
    Zweispaltige CSV im Format des Import-Tabs von synonyme_dialog.py.

    Als Zielart steht die entityid: sie ist eindeutig, waehrend ein Name
    auf mehrere Arten passen kann - resolve_exact() meldet das dann als
    "nicht eindeutig" und der Eintrag bleibt liegen.
    """
    with open(pfad, "w", newline="", encoding="utf-8-sig") as fh:
        schreiber = csv.writer(fh, delimiter=";")
        schreiber.writerow(["synonym_term", "Zielart"])
        for s in fehlt:
            schreiber.writerow([s["term"], s["entityid"]])
    return len(fehlt)


def abgleichen(con, fehlt, falsch, ueberzaehlig, entfernen):
    """Ergaenzen und berichtigen. Loeschen nur auf ausdrueckliche Ansage."""
    vorhanden = spalten(con, SYNONYM_TABELLE)
    heute = datetime.date.today().strftime("%Y-%m-%d")

    felder = [SPALTE_SYNONYM, SPALTE_ZIEL, "parentid"]
    werte_fest = {}
    if "art" in vorhanden:
        felder.append("art")
        werte_fest["art"] = ART_WERT
    for f, v in (("quelle", None), ("erfasst_von", "synonyme_in_gpkg"),
                 ("erfasst_am", heute)):
        if f in vorhanden:
            felder.append(f)
            werte_fest[f] = v

    def reihe(s):
        aus = []
        for f in felder:
            if f == SPALTE_SYNONYM:
                aus.append(s["term"])
            elif f == SPALTE_ZIEL:
                aus.append(s["entityid"])
            elif f == "parentid":
                aus.append(s["parentid"])
            elif f == "quelle":
                aus.append(s["quelle"])
            else:
                aus.append(werte_fest[f])
        return aus

    if fehlt:
        sql = (f'INSERT INTO "{SYNONYM_TABELLE}" ('
               + ", ".join(f'"{f}"' for f in felder) + ") VALUES ("
               + ", ".join("?" * len(felder)) + ")")
        con.executemany(sql, [reihe(s) for s in fehlt])

    for s, i in falsch:
        setzen = [f'"{SPALTE_ZIEL}" = ?']
        args = [s["entityid"]]
        if "quelle" in vorhanden:
            setzen.append('"quelle" = ?')
            args.append(s["quelle"])
        if "erfasst_am" in vorhanden:
            setzen.append('"erfasst_am" = ?')
            args.append(heute)
        args.append(i["fid"])
        con.execute(f'UPDATE "{SYNONYM_TABELLE}" SET '
                    + ", ".join(setzen) + " WHERE fid = ?", args)

    geloescht = 0
    if entfernen and ueberzaehlig:
        con.executemany(f'DELETE FROM "{SYNONYM_TABELLE}" WHERE fid = ?',
                        [(i["fid"],) for i in ueberzaehlig])
        geloescht = len(ueberzaehlig)
    con.commit()
    return len(fehlt), len(falsch), geloescht


def lege_sicht_an(con):
    """
    Sicht Arten_Suche: Arten zusammen mit den Synonymen, gleiche Spalten.

    Der Anzeigetext der Synonymzeile wird hier berechnet, nicht in der
    Tabelle gespeichert: Die Tabelle fuehrt keine Spalte dafuer, und ein
    gespeicherter Text waere das zweite Mal dieselbe Angabe - er ginge
    schief, sobald jemand in Arten einen Namen berichtigt.

    OGR liest eine Sicht als Layer, wenn sie eine eindeutige fid fuehrt und
    in gpkg_contents steht. Beides ist hier erfuellt.
    """
    # CREATE VIEW nimmt keine gebundenen Parameter: die listitemid muessen
    # als Literale in den Text. Sie stammen aus dem eigenen GeoPackage und
    # sind Zahlen in Textform; das Verdoppeln des Apostrophs ist trotzdem
    # drin, damit hier kein Einfallstor entsteht, falls die Liste einmal
    # andere Werte fuehrt.
    gruppen = sorted(gueltige_gruppen(con))
    if not gruppen:
        raise RuntimeError("Artengruppen fuehrt keine listitemid - ohne die "
                           "laesst sich die Sicht nicht filtern.")
    liste = ", ".join("'" + str(g).replace("'", "''") + "'" for g in gruppen)
    con.execute(f'DROP VIEW IF EXISTS "{SUCH_SICHT}"')
    con.execute(f"""
        CREATE VIEW "{SUCH_SICHT}" AS
            SELECT a.fid          AS fid,
                   a.entityid     AS entityid,
                   a.parentid     AS parentid,
                   a.anzeigename  AS anzeigename,
                   a.term         AS term,
                   a.Name_deutsch AS Name_deutsch,
                   'Art'          AS eintragsart
              FROM Arten a
             WHERE a.parentid IN ({liste})
            UNION ALL
            SELECT {FID_VERSATZ} + s.fid,
                   s."{SPALTE_ZIEL}",
                   s.parentid,
                   s."{SPALTE_SYNONYM}" || '{PFEIL}' || COALESCE(
                       NULLIF(a.anzeigename, ''), a.term, '?'),
                   a.term,
                   a.Name_deutsch,
                   'Synonym'
              FROM "{SYNONYM_TABELLE}" s
              LEFT JOIN Arten a
                     ON a.entityid = s."{SPALTE_ZIEL}"
                    AND a.parentid = s.parentid
    """)
    con.execute(
        "INSERT OR REPLACE INTO gpkg_contents "
        "(table_name, data_type, identifier, description) "
        "VALUES (?, 'attributes', ?, ?)",
        (SUCH_SICHT, SUCH_SICHT,
         "Arten einschließlich Synonyme (Sicht, nur lesend)"))
    con.commit()
    return con.execute(f'SELECT count(*) FROM "{SUCH_SICHT}"').fetchone()[0]


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gpkg", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--pruefen", action="store_true",
                    help="nur berichten (Vorgabe)")
    ap.add_argument("--csv", default=None, metavar="DATEI",
                    help="fehlende Eintraege als CSV fuer den Import-Tab")
    ap.add_argument("--abgleichen", action="store_true",
                    help="ergaenzen und maschinell gepflegte Ziele berichtigen")
    ap.add_argument("--entfernen", action="store_true",
                    help="mit --abgleichen: maschinelle Zeilen loeschen, die "
                         "synonyme.json nicht mehr kennt")
    ap.add_argument("--sicht", action="store_true",
                    help="Sicht Arten_Suche anlegen oder erneuern")
    args = ap.parse_args()

    if args.entfernen and not args.abgleichen:
        sys.exit("--entfernen nur zusammen mit --abgleichen.")

    plugin = plugin_verzeichnis(__file__)
    if not plugin and not (args.gpkg and args.json):
        sys.exit("Plugin-Ordner nicht gefunden - bitte --gpkg und --json "
                 "angeben.")
    gpkg = args.gpkg or os.path.join(
        plugin, "data", "fundpunkte_tiere", "Referenzen.gpkg")
    js = args.json or os.path.join(plugin, "data", "synonyme.json")
    for pfad in (gpkg, js):
        if not os.path.isfile(pfad):
            sys.exit(f"Nicht gefunden: {pfad}")

    con = sqlite3.connect(gpkg)
    try:
        print(f"GeoPackage: {os.path.basename(gpkg)}")
        nach_name = lies_arten(con)
        print(f"  Arten unter einer Artengruppe: {len(nach_name)} Namen "
              f"(wissenschaftlich und deutsch)")
        soll, ungeloest, bekannt = baue_soll(js, nach_name)
        ist = lies_ist(con)
        if ist is None:
            sys.exit(f"Tabelle {SYNONYM_TABELLE} fehlt im GeoPackage. Dieses "
                     f"Werkzeug legt sie nicht an - sie gehoert zum "
                     f"Datenmodell (Referenzen.sql).")

        fehlt, falsch, fremd_falsch, ueberzaehlig, fremd = bericht(
            con, soll, ist, ungeloest, bekannt)

        if args.csv:
            n = schreibe_csv(args.csv, fehlt)
            print(f"\n  {n} Eintraege nach {args.csv} geschrieben.")
            print("  Weiter in QGIS: Fundpunkte – Synonyme verwalten, "
                  "Tab Import.")

        if args.abgleichen:
            n_neu, n_korr, n_weg = abgleichen(
                con, fehlt, falsch, ueberzaehlig, args.entfernen)
            print(f"\n  Abgeglichen: {n_neu} ergaenzt, {n_korr} berichtigt, "
                  f"{n_weg} geloescht.")
            if ueberzaehlig and not args.entfernen:
                print(f"  {len(ueberzaehlig)} maschinelle Zeilen stehen noch, "
                      f"die synonyme.json nicht mehr kennt (--entfernen).")
            if fremd_falsch:
                print(f"  {len(fremd_falsch)} fremde Zeilen mit anderem Ziel "
                      f"unveraendert - die entscheidet die Station.")

        if args.sicht:
            anz = lege_sicht_an(con)
            print(f"\n  Sicht {SUCH_SICHT} angelegt: {anz} Zeilen.")

        if not (args.abgleichen or args.sicht or args.csv):
            abweichung = bool(fehlt or falsch or fremd_falsch
                              or ueberzaehlig or ungeloest)
            if not abweichung:
                print("\n  Tabelle und synonyme.json stimmen ueberein.")
            return 1 if abweichung else 0
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
