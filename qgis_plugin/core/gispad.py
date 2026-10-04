#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gemeinsamer Unterbau fuer das Auslesen von GISPAD-Exporten (File-Geodatabase).

Enthaelt drei Dinge, die fuer jede Objektklasse (BT, BK, MAS, ...) gelten:

  1. Lesen der Geodatabase ueber GDAL/OGR (OpenFileGDB) - ohne GISPAD, ohne
     ODBC, ohne Access.
  2. Ableiten der Tabellenbeziehungen aus den Daten.
  3. Aufloesen der OSIRIS-Schluessel in Klartext.

ZUM DATENMODELL
---------------
GISPAD speichert nach dem OSIRIS-Modell: `LINFOS` ist die Haupttabelle, an
der die uebrigen Tabellen haengen, teils ueber mehrere Stufen. Im
File-Geodatabase-Export erscheint LINFOS als die Geometrie-Layer der
Objektklasse (BT_Polygon, BT_Polyline, BT_Point, entsprechend BK_*, MAS_*).

Verknuepft wird ueber PKEY/FKEY: die FKEY-Spalte der abhaengigen Tabelle
zeigt auf den PKEY ihrer direkten Eltern. So steht es in der
DV-Verfahrensbeschreibung BT (V2020a, S. 29):

    "In jeder Tabelle findet sich die 'GISPAD_ID' als Identifier eines
    Objektes. Die eigentliche Verknuepfung der Tabellen erfolgt jedoch ueber
    'Pkey = Primary-key' in der abhaengigen Tabelle mit 'dem Fkey =
    Foreign-key' der uebergeordneten Tabelle."

Zwei Fallen, die beide schon zugeschlagen haben:

  * GISPADID taugt NICHT zum Verknuepfen. Sie ist in allen Tabellen eines
    Objektes gleich; bei 1:n:n laesst sich damit nicht mehr sagen, zu welcher
    Schicht eine Pflanzenzeile gehoerte.
  * PKEY ist nur INNERHALB einer Tabelle eindeutig. Die Wertebereiche
    verschiedener Tabellen ueberlappen stark, deshalb "trifft" ein FKEY rein
    zufaellig auch in falschen Tabellen. Eine hohe Trefferquote beweist also
    nichts.

Daraus folgt das Pruefkriterium weiter unten: nicht wie viele FKEY ein Ziel
finden, sondern ob die GISPADID dabei widerspruchsfrei bleibt.

WARUM ABGELEITET UND NICHT FEST VERDRAHTET
------------------------------------------
Der Geodatabase-Export enthaelt die Beziehungen nicht; die
DV-Verfahrensbeschreibung BT sagt dazu auf S. 35 ausdruecklich, die
"relationship classes werden nicht exportiert und muessen weiterhin
nachtraeglich definiert werden". Sie aus den Daten abzuleiten hat den
Vorteil, dass auch Objektklassen funktionieren, deren Schema hier nicht
vorliegt (die BK-Beschreibung v2019a etwa fuehrt keine Tabellenspalte).
Das Verfahren wurde gegen das dokumentierte BT-Schema geprueft und hat es
vollstaendig reproduziert.
"""

import os
import sys

#: Spalten, die zum Modell gehoeren und keine Fachdaten sind.
SCHLUESSELSPALTEN = ("GISPADID", "PKEY", "SKEY", "FKEY")

#: Die OSIRIS-Referenzlisten liegen im Plugin, damit der Klartext ohne
#: Zutun der Anwenderinnen und Anwender verfuegbar ist. Erzeugt werden sie
#: mit tools/osiris_listen_export.py aus der v_osiris*.mdb.
_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LISTEN_DIR = os.path.join(_PLUGIN_DIR, "data", "osiris")


# ── GDAL ────────────────────────────────────────────────────────────────────

def ogr_modul():
    """OGR laden oder mit verstaendlicher Meldung abbrechen."""
    try:
        from osgeo import ogr
        ogr.UseExceptions()
        return ogr
    except ImportError:
        sys.exit(
            "GDAL-Python-Bindung (osgeo) fehlt.\n"
            "  In QGIS ist sie enthalten - das Werkzeug laeuft dort ohne "
            "weiteres.\n"
            "  Eigenstaendig: 'apt-get install python3-gdal' (Linux) bzw. "
            "die OSGeo4W-Shell (Windows).")


def oeffne(gdb_pfad):
    """File-Geodatabase oeffnen. Eine .gdb ist ein ORDNER, keine Datei."""
    ogr = ogr_modul()
    if not os.path.isdir(gdb_pfad):
        sys.exit(f"Kein Ordner: {gdb_pfad}\n"
                 "  Eine File-Geodatabase ist der Ordner '*.gdb' selbst.")
    ds = ogr.Open(gdb_pfad)
    if ds is None:
        sys.exit(f"Nicht lesbar als Geodatabase: {gdb_pfad}")
    return ds


def layer_namen(ds):
    return [ds.GetLayer(i).GetName() for i in range(ds.GetLayerCount())]


def lies(ds, name, mit_geometrie=False):
    """
    Eine Tabelle als (zeilen, geometrien) lesen.

    zeilen sind dicts; geometrien ist bei mit_geometrie=False leer, sonst
    deckungsgleich zu zeilen (WKB oder None).
    """
    lyr = ds.GetLayerByName(name)
    if lyr is None:
        return [], []
    defn = lyr.GetLayerDefn()
    felder = [defn.GetFieldDefn(i).GetName()
              for i in range(defn.GetFieldCount())]
    zeilen, geoms = [], []
    lyr.ResetReading()
    for feat in lyr:
        zeilen.append({f: feat.GetField(f) for f in felder})
        if mit_geometrie:
            g = feat.GetGeometryRef()
            geoms.append(g.ExportToWkb() if g else None)
    return zeilen, geoms


def feld_aliase(ds, name):
    """
    {feldname: Alias} - die Geodatabase fuehrt sprechende deutsche Namen
    ("Objektkennung" fuer KENNUNG). Fuer Oberflaechen und Berichte nuetzlich.
    """
    lyr = ds.GetLayerByName(name)
    if lyr is None:
        return {}
    defn = lyr.GetLayerDefn()
    aus = {}
    for i in range(defn.GetFieldCount()):
        fd = defn.GetFieldDefn(i)
        alias = fd.GetAlternativeName()
        if alias and alias != fd.GetName():
            aus[fd.GetName()] = alias
    return aus


def gefuellte_tabellen(ds):
    """{name: zeilenzahl} aller nicht leeren Layer/Tabellen."""
    aus = {}
    for name in layer_namen(ds):
        lyr = ds.GetLayerByName(name)
        try:
            n = lyr.GetFeatureCount()
        except Exception:
            n = 0
        if n:
            aus[name] = n
    return aus


# ── Beziehungen ableiten ────────────────────────────────────────────────────

def pruefe_elternschaft(kind_zeilen, eltern_zeilen):
    """
    Pruefen, ob kind.FKEY auf eltern.PKEY zeigt.

    Rueckgabe: (gleich, abweichend, ohne_ziel).

    Entscheidend ist `abweichend`: beide Tabellen fuehren dieselbe GISPADID
    fuer dasselbe Objekt. Passt der ueber FKEY gefundene Elternsatz zu einem
    anderen Objekt, war der Treffer Zufall. Deshalb zaehlt nicht die
    Trefferquote, sondern die Widerspruchsfreiheit.
    """
    idx = {z["PKEY"]: z.get("GISPADID")
           for z in eltern_zeilen if z.get("PKEY") is not None}
    gleich = abweichend = ohne_ziel = 0
    for z in kind_zeilen:
        fk = z.get("FKEY")
        if fk is None or fk not in idx:
            ohne_ziel += 1
        elif idx[fk] == z.get("GISPADID"):
            gleich += 1
        else:
            abweichend += 1
    return gleich, abweichend, ohne_ziel


def leite_beziehungen_ab(tabellen, toleranz=0):
    """
    Zu jeder Tabelle mit FKEY den Elternteil bestimmen.

    `tabellen` ist {name: zeilen}. `toleranz` erlaubt Zeilen ohne Ziel - das
    ist der Normalfall, wenn eine Kindtabelle sich auf mehrere
    Geometrie-Layer verteilt (BtypHtyp deckt Polygon UND Polyline ab).

    Rueckgabe: {kind: {"eltern": name|None, "kandidaten": [...],
                       "gleich":n, "ohne_ziel":n, "sicher":bool}}
    """
    ergebnis = {}
    for kind, krows in tabellen.items():
        if not krows or "FKEY" not in krows[0]:
            continue
        kandidaten = []
        for eltern, erows in tabellen.items():
            if eltern == kind or not erows or "PKEY" not in erows[0]:
                continue
            gleich, abweichend, ohne_ziel = pruefe_elternschaft(krows, erows)
            # Ein einziger Widerspruch schliesst den Kandidaten aus.
            if abweichend == 0 and gleich > 0 and ohne_ziel <= max(toleranz, 0):
                kandidaten.append((eltern, gleich, ohne_ziel))
        kandidaten.sort(key=lambda k: (-k[1], k[2]))
        ergebnis[kind] = {
            "eltern": kandidaten[0][0] if len(kandidaten) == 1 else None,
            "kandidaten": kandidaten,
            "gleich": kandidaten[0][1] if kandidaten else 0,
            "ohne_ziel": kandidaten[0][2] if kandidaten else len(krows),
            "sicher": len(kandidaten) == 1,
        }
    return ergebnis


def geometrie_gruppe(geom_layer):
    """
    Sammelname fuer die Geometrie-Layer EINER Objektklasse, z. B. 'BT_*'.

    Im Export ist die Haupttabelle LINFOS nach Geometrietyp aufgeteilt
    (BT_Polygon, BT_Polyline, BT_Point). Fachlich ist das EINE Tabelle, und
    die PKEY sind ueber alle drei hinweg eindeutig.

    Erwartet nur Layer derselben Objektklasse. Fuer einen Export mit mehreren
    Klassen gibt es geometrie_gruppen().
    """
    if not geom_layer:
        return "LINFOS"
    kurz = sorted(geom_layer)[0]
    praefix = kurz.split("_")[0] if "_" in kurz else kurz
    return f"{praefix}_*"


def geometrie_gruppen(geom_layer):
    """
    Geometrie-Layer nach Objektklasse gruppieren: {'BT_*': [...], 'BK_*': [...]}.

    Ein Stationsexport enthaelt in aller Regel mehrere Objektklassen
    nebeneinander. Wuerde man alle Geometrie-Layer zu einer Elterntabelle
    zusammenfassen, bekaeme eine Kindtabelle der einen Klasse die andere als
    Elternteil zugeschrieben - die Schluesselbereiche ueberlappen, und die
    GISPADID-Pruefung greift nicht, weil beide Klassen dieselbe Zeile gar
    nicht teilen.
    """
    gruppen = {}
    for name in geom_layer:
        praefix = name.split("_")[0] if "_" in name else name
        gruppen.setdefault(f"{praefix}_*", []).append(name)
    return gruppen


def beziehungen_mit_geometrie(ds, geom_layer, tabellen):
    """
    Wie leite_beziehungen_ab, aber mit den Geometrie-Layern als Elternteil.

    Die Geometrie-Layer werden zu EINER Elterntabelle zusammengefasst (siehe
    geometrie_gruppe). Sonst scheitert die Zuordnung an Kindtabellen, die
    Objekte mehrerer Geometrietypen bedienen: BtypHtyp etwa fuehrt die Zeilen
    zu Flaechen UND Linien, und gegen BT_Polygon allein gepruefet blieben die
    Linienzeilen ohne Ziel. Zusammengefasst braucht es dafuer keine
    Toleranz - und ohne Toleranz ist das Kriterium strenger.
    """
    alle = dict(tabellen)
    for gruppe, namen in geometrie_gruppen(geom_layer).items():
        gesammelt = []
        for name in namen:
            zeilen, _ = lies(ds, name)
            gesammelt.extend(zeilen)
        if gesammelt:
            alle[gruppe] = gesammelt
    return leite_beziehungen_ab(alle, toleranz=0)


def kette_nach_oben(beziehungen, start):
    """Pfad von `start` bis zur Wurzel, z. B. Pflanzenliste -> ... -> BT_Polygon."""
    pfad, gesehen = [start], {start}
    aktuell = start
    while True:
        eltern = (beziehungen.get(aktuell) or {}).get("eltern")
        if not eltern or eltern in gesehen:
            break
        pfad.append(eltern)
        gesehen.add(eltern)
        aktuell = eltern
    return pfad


# ── OSIRIS-Referenzlisten ───────────────────────────────────────────────────

def lies_referenzliste(pfad):
    """
    {schluessel: bezeichnung} aus einer CSV von osiris_listen_export.py.

    Mehrdeutige Schluessel tragen alle Lesarten mit ' | ' verbunden. Das soll
    auffallen und nicht stillschweigend zu einer willkuerlichen Bedeutung
    werden.
    """
    import csv
    aus = {}
    if not os.path.isfile(pfad):
        return aus
    with open(pfad, encoding="utf-8") as fh:
        for r in csv.DictReader(fh, delimiter=";"):
            k = (r.get("schluessel") or "").strip()
            if k:
                aus[k] = (r.get("bezeichnung") or "").strip()
    return aus


def loese_auf(wert, liste, trenner=", "):
    """
    Code oder Codefolge in Klartext uebersetzen.

    Unbekannte Codes bleiben stehen und werden mit '(?)' markiert, statt zu
    verschwinden: eine Luecke in der Referenzliste soll sichtbar sein.
    """
    if wert in (None, "") or not liste:
        return None
    teile = [t.strip() for t in str(wert).split(",")]
    aus = [liste.get(t) or f"{t} (?)" for t in teile if t]
    return trenner.join(aus) if aus else None


# ── kleine Helfer ───────────────────────────────────────────────────────────

def als_bool(wert):
    """
    GISPAD schreibt Wahrheitswerte als deutschen Text ('Wahr'/'Falsch').
    Unbekanntes wird None, nicht False - sonst wird aus 'nicht erhoben'
    stillschweigend 'nein'.
    """
    if wert is None:
        return None
    t = str(wert).strip().lower()
    if t in ("wahr", "true", "ja", "j", "1", "-1"):
        return True
    if t in ("falsch", "false", "nein", "n", "0"):
        return False
    return None


def gruppiere_nach_fkey(zeilen):
    """{FKEY: [zeile, ...]} in Quellreihenfolge."""
    aus = {}
    for z in zeilen:
        k = z.get("FKEY")
        if k is not None:
            aus.setdefault(k, []).append(z)
    return aus


def aggregiere(zeilen, feld, trenner=", "):
    """
    Werte eines Feldes zusammenfassen: Quellreihenfolge bleibt erhalten,
    Dubletten entfallen, leeres Ergebnis wird None (nicht '').
    """
    gesehen, aus = set(), []
    for z in zeilen:
        w = z.get(feld)
        if w is None:
            continue
        w = str(w).strip()
        if w and w not in gesehen:
            gesehen.add(w)
            aus.append(w)
    return trenner.join(aus) if aus else None
