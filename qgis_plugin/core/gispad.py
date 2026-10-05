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
import shutil
import sys
import tempfile
import zipfile

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


def ist_geodatabase(pfad):
    """
    Laesst sich der Ordner als Geodatabase oeffnen? (True/False)

    Geprueft wird durch OEFFNEN, nicht am Namen: wo im Verzeichnisbaum der
    Export liegt und wie der Ordner darueber heisst, ist damit gleichgueltig.

    Eine Einschraenkung bleibt, und sie kommt vom Treiber, nicht von hier:
    OpenFileGDB oeffnet nur Ordner, deren Name auf .gdb endet. Ein
    umbenannter Export laesst sich also nicht lesen. `hat_gdb_tabellen`
    erkennt diesen Fall, damit man es sagen kann.
    """
    if not pfad or not os.path.isdir(pfad):
        return False
    try:
        ogr = ogr_modul()
        ds = ogr.Open(pfad)
    except Exception:
        return False
    if ds is None:
        return False
    # Der TREIBER entscheidet, nicht die blosse Lesbarkeit: OGR oeffnet auch
    # ein Verzeichnis voller Shapefiles und meldet Layer. Ohne diese Pruefung
    # haelt die Suche jeden Shapefile-Ordner fuer eine Geodatabase.
    try:
        treiber = ds.GetDriver().GetName()
    except Exception:
        treiber = ""
    treffer = (treiber in ("OpenFileGDB", "FileGDB")
               and ds.GetLayerCount() > 0)
    ds = None
    return treffer


def finde_geodatabases(pfad, tiefe=1):
    """
    Geodatabases in `pfad` und darunter suchen.

    Gesucht wird in drei Richtungen, weil Leute an unterschiedlichen Stellen
    landen: der Ordner selbst, ein .gdb-Ordner im Pfad DARUEBER (man ist
    hineinnavigiert) und Unterordner bis `tiefe`. Zurueck kommt eine Liste
    ohne Dubletten in der Reihenfolge der Wahrscheinlichkeit.
    """
    gefunden = []

    def merke(k):
        k = os.path.normpath(k)
        if k not in gefunden and ist_geodatabase(k):
            gefunden.append(k)

    merke(pfad)
    # im Pfad aufwaerts: wurde in die Geodatabase hineinnavigiert?
    teile = (pfad or "").replace("\\", "/").split("/")
    for i, t in enumerate(teile):
        if t.lower().endswith(".gdb"):
            merke(pfad[:len("/".join(teile[:i + 1]))])
    # und ein, zwei Ebenen darunter
    if os.path.isdir(pfad) and tiefe > 0:
        try:
            for name in sorted(os.listdir(pfad)):
                unter = os.path.join(pfad, name)
                if os.path.isdir(unter):
                    gefunden.extend(x for x in finde_geodatabases(unter,
                                                                  tiefe - 1)
                                    if x not in gefunden)
        except OSError:
            pass
    return gefunden


# ── Gepackte Exporte ────────────────────────────────────────────────────────
#
# Eine File-Geodatabase ist ein Ordner mit hunderten Dateien. Wer sie
# weitergibt, packt sie - und beim Verschicken bleibt es oft dabei: auf der
# Platte liegt dann ein ZIP-Archiv, nicht der Ordner. Erschwerend kommt
# hinzu, dass der Windows-Explorer bekannte Endungen ausblendet: aus
# "Export.gdb.zip" wird in der Anzeige "Export.gdb", und es sieht aus wie
# der Ordner, den man sucht. Nur die Spalte "Typ" verraet das Archiv.
#
# Deshalb werden Archive hier mitbehandelt - erkannt am INHALT, nicht an der
# Endung, denn die taeuscht ja gerade.

def ist_archiv(pfad):
    """Ist das eine ZIP-Datei? (Am Inhalt geprueft, nicht am Namen.)"""
    try:
        return os.path.isfile(pfad) and zipfile.is_zipfile(pfad)
    except OSError:
        return False


#: Dateiendungen, an denen eine File-Geodatabase zu erkennen ist.
GDB_DATEIEN = (".gdbtable", ".gdbtablx")


def hat_gdb_tabellen(ordner):
    """
    Liegen in dem Ordner die Tabellendateien einer Geodatabase?

    Gebraucht wird das fuer die Diagnose: der OpenFileGDB-Treiber oeffnet
    ausschliesslich Ordner, deren NAME auf .gdb endet. Ein ausgepackter,
    aber umbenannter Export laesst sich deshalb nicht lesen - mit dieser
    Pruefung kann man das sagen, statt "keine Geodatabase gefunden" zu
    melden, obwohl sie direkt vor einem liegt.
    """
    if not ordner or not os.path.isdir(ordner):
        return False
    try:
        return any(n.lower().endswith(GDB_DATEIEN)
                   for n in os.listdir(ordner))
    except OSError:
        return False


def archiv_befund(pfad):
    """
    Was steckt in dem Archiv? -> (hat_geodatabase, tabellen_in_der_wurzel)

    Gelesen wird nur das Inhaltsverzeichnis - das geht auch bei grossen
    Dateien sofort. Ohne diese Vorpruefung wuerde die Suche jedes beliebige
    Archiv auspacken, nur um festzustellen, dass Fotos darin sind.

    Der zweite Wert unterscheidet zwei Packweisen: entweder wurde der
    Ordner "Export.gdb" gepackt (dann steht er im Archiv), oder es wurde
    aus dem Ordner HERAUS gepackt (dann liegen die Tabellendateien
    unmittelbar in der Archivwurzel). Im zweiten Fall muss der Zielordner
    beim Auspacken auf .gdb endet, sonst liest der Treiber ihn nicht.
    """
    try:
        with zipfile.ZipFile(pfad) as zf:
            namen = zf.namelist()
    except (OSError, zipfile.BadZipFile):
        return False, False
    hat = wurzel = False
    for name in namen:
        if not name.lower().endswith(GDB_DATEIEN):
            continue
        hat = True
        if "/" not in name.replace("\\", "/").strip("/"):
            wurzel = True
    return hat, wurzel


def archiv_hat_geodatabase(pfad):
    """Steckt in dem Archiv eine Geodatabase? (True/False)"""
    return archiv_befund(pfad)[0]


def finde_archive(pfad, tiefe=1):
    """
    Archive mit Geodatabase-Inhalt in `pfad` und darunter.

    Gesucht wird so weit wie bei den ausgepackten Exporten, damit es nicht
    davon abhaengt, ob der Export gepackt ist oder nicht.
    """
    if ist_archiv(pfad) and archiv_hat_geodatabase(pfad):
        return [pfad]
    if not pfad or not os.path.isdir(pfad):
        return []
    treffer = []
    try:
        namen = sorted(os.listdir(pfad))
    except OSError:
        return []
    for name in namen:
        eintrag = os.path.join(pfad, name)
        if os.path.isdir(eintrag):
            if tiefe > 0:
                treffer.extend(x for x in finde_archive(eintrag, tiefe - 1)
                               if x not in treffer)
        elif ist_archiv(eintrag) and archiv_hat_geodatabase(eintrag):
            treffer.append(eintrag)
    return treffer


def entpacke_archiv(pfad, ziel=None, melde=None):
    """
    Archiv auspacken und den Zielordner zurueckgeben.

    Ohne `ziel` wird ein temporaerer Ordner angelegt; ihn wieder zu
    entfernen ist Sache der Aufrufenden (`raeume_auf`). Bewusst nicht in den
    Ordner des Archivs: der liegt oft auf einem Netzlaufwerk oder ist
    schreibgeschuetzt, und ein halb ausgepacktes Archiv neben dem Original
    waere eine Falle fuer den naechsten Durchgang.
    """
    if ziel is None:
        ziel = tempfile.mkdtemp(prefix="gispad_")
    else:
        os.makedirs(ziel, exist_ok=True)
    with zipfile.ZipFile(pfad) as zf:
        glieder = zf.namelist()
        # Eintraege, die aus dem Zielordner herausfuehren, werden
        # uebergangen. Python entschaerft solche Namen beim Auspacken
        # inzwischen selbst; hier steht es ausdruecklich, damit es auch bei
        # einer anderen Python-Fassung gilt.
        sauber = []
        for name in glieder:
            n = name.replace("\\", "/")
            if n.startswith("/") or ".." in n.split("/"):
                continue
            sauber.append(name)
        if melde:
            melde(-1, f"Entpacke {len(sauber)} Dateien aus "
                      f"{os.path.basename(pfad)} …")
        zf.extractall(ziel, members=sauber)
    return ziel


def raeume_auf(ordner):
    """Einen von `entpacke_archiv` angelegten Ordner wieder entfernen."""
    if ordner and os.path.isdir(ordner):
        shutil.rmtree(ordner, ignore_errors=True)


def erschliesse(pfad, melde=None):
    """
    Aus einer Nutzerangabe die Liste der Geodatabases machen.

    `pfad` darf ein Geodatabase-Ordner, ein Ordner darueber oder darunter,
    ein Archiv oder ein Ordner mit Archiven sein. Zurueck kommt
    (geodatabases, temporaerer_ordner). Der zweite Wert ist None, wenn
    nichts ausgepackt wurde, sonst nach dem Lesen an `raeume_auf` zu
    uebergeben.

    Reihenfolge: zuerst wird nach ausgepackten Geodatabases gesucht. Liegt
    beides vor - Ordner und Archiv -, ist der Ordner der naehere Treffer;
    auspacken kostet Zeit und Platz.
    """
    treffer = finde_geodatabases(pfad)
    if treffer:
        return treffer, None

    archive = finde_archive(pfad)
    if not archive:
        return [], None

    temp = tempfile.mkdtemp(prefix="gispad_")
    gefunden = []
    for archiv in archive:
        hat, wurzel = archiv_befund(archiv)
        if not hat:
            continue
        name = os.path.basename(archiv)
        while True:                      # "Export.gdb.zip" -> "Export"
            name, endung = os.path.splitext(name)
            if not endung:
                break
        # Liegen die Tabellendateien in der Archivwurzel, muss der
        # Zielordner die Endung tragen - der Treiber verlangt sie am Namen.
        anhang = ".gdb" if wurzel else ""
        basis = os.path.join(temp, name)
        unter = basis + anhang
        # Jedes Archiv in ein eigenes Unterverzeichnis: zwei Exporte
        # gleichen Namens wuerden einander sonst ueberschreiben.
        nr = 1
        while os.path.exists(unter):
            unter = f"{basis}_{nr}{anhang}"
            nr += 1
        entpacke_archiv(archiv, ziel=unter, melde=melde)
        gefunden.extend(x for x in finde_geodatabases(unter, tiefe=2)
                        if x not in gefunden)
    if not gefunden:
        raeume_auf(temp)
        return [], None
    return gefunden, temp


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
    # Ueber den INDEX lesen, nicht ueber den Namen: GetField(name) sucht den
    # Feldnamen bei jedem einzelnen Wert linear in der Felddefinition. Bei
    # Tabellen mit vielen Spalten (MASSN hat 43) und zehntausenden Zeilen
    # macht das den Unterschied zwischen Sekunden und einer Minute.
    nummern = list(enumerate(felder))
    zeilen, geoms = [], []
    lyr.ResetReading()
    for feat in lyr:
        zeilen.append({f: feat.GetField(i) for i, f in nummern})
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

def pkey_index(zeilen):
    """{PKEY: GISPADID} einer Tabelle."""
    return {z["PKEY"]: z.get("GISPADID")
            for z in zeilen if z.get("PKEY") is not None}


def pruefe_elternschaft(kind_zeilen, eltern_zeilen, idx=None):
    """
    Pruefen, ob kind.FKEY auf eltern.PKEY zeigt.

    Rueckgabe: (gleich, abweichend, ohne_ziel).

    Entscheidend ist `abweichend`: beide Tabellen fuehren dieselbe GISPADID
    fuer dasselbe Objekt. Passt der ueber FKEY gefundene Elternsatz zu einem
    anderen Objekt, war der Treffer Zufall. Deshalb zaehlt nicht die
    Trefferquote, sondern die Widerspruchsfreiheit.

    `idx` nimmt einen vorberechneten Schluesselindex entgegen. Ohne ihn
    wuerde er bei jeder Paarprueffung neu aufgebaut - bei einem Dutzend
    Tabellen sind das hunderte Durchlaeufe ueber dieselben Zeilen.
    """
    if idx is None:
        idx = pkey_index(eltern_zeilen)
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


def leite_beziehungen_ab(tabellen, toleranz=None):
    """
    Zu jeder Tabelle mit FKEY den Elternteil bestimmen.

    `tabellen` ist {name: zeilen}. Ausgeschlossen wird ein Kandidat allein
    durch WIDERSPRUECHE - also dadurch, dass der ueber FKEY gefundene
    Elternsatz zu einem anderen Objekt gehoert (abweichende GISPADID).

    Zeilen OHNE Ziel schliessen einen Kandidaten dagegen nicht aus. Das ist
    der Normalfall, sobald ein Export mehrere Objektklassen enthaelt: eine
    Sachtabelle wie BtypHtyp bedient dann BT- UND FFH-Objekte, und beim
    Pruefen gegen die BT-Geometrie bleiben die FFH-Zeilen ohne Ziel. Eine
    fruehere Fassung verlangte hier Null und verwarf deshalb den richtigen
    Elternteil - die Fachspalten blieben stumm leer.

    Gereiht wird nach wenigen offenen Zeilen, dann nach vielen Treffern;
    `sicher` ist gesetzt, wenn der beste Kandidat den zweitbesten dabei
    eindeutig schlaegt.

    `toleranz` wird nur noch der Rueckwaertskompatibilitaet halber
    entgegengenommen und nicht mehr ausgewertet.
    """
    # Schluesselindex je Tabelle einmal aufbauen statt je Paarprueffung.
    indizes = {name: pkey_index(zeilen) for name, zeilen in tabellen.items()
               if zeilen and "PKEY" in zeilen[0]}

    ergebnis = {}
    for kind, krows in tabellen.items():
        if not krows or "FKEY" not in krows[0]:
            continue
        kandidaten = []
        for eltern, erows in tabellen.items():
            if eltern == kind or not erows or "PKEY" not in erows[0]:
                continue
            gleich, abweichend, ohne_ziel = pruefe_elternschaft(
                krows, erows, indizes[eltern])
            # Ein einziger Widerspruch schliesst den Kandidaten aus.
            if abweichend == 0 and gleich > 0:
                kandidaten.append((eltern, gleich, ohne_ziel))
        kandidaten.sort(key=lambda k: (k[2], -k[1]))
        ergebnis[kind] = {"kandidaten": kandidaten}

    # Gleichstand nach Tiefe aufloesen. Innerhalb EINES Objektes ist die
    # GISPADID auf allen Ebenen gleich, deshalb bleibt eine hoehere Ebene
    # widerspruchsfrei, obwohl sie nicht der direkte Elternteil ist: die
    # Tierliste haengt an der Schichtung, passt rechnerisch aber auch zum
    # Vegetationstyp darueber. Richtig ist die TIEFERE Ebene - die
    # speziellere Zuordnung. Gemessen wird sie am vorlaeufigen Graphen.
    vorlaeufig = {k: (v["kandidaten"][0][0] if v["kandidaten"] else None)
                  for k, v in ergebnis.items()}

    def tiefe(name, gesehen=None):
        gesehen = gesehen or set()
        if name in gesehen or name not in vorlaeufig or not vorlaeufig[name]:
            return 0
        return 1 + tiefe(vorlaeufig[name], gesehen | {name})

    for kind, eintrag in ergebnis.items():
        kandidaten = eintrag["kandidaten"]
        if kandidaten:
            kandidaten.sort(key=lambda k: (k[2], -tiefe(k[0]), -k[1]))
        schluessel = [(k[2], -tiefe(k[0]), -k[1]) for k in kandidaten]
        sicher = bool(kandidaten) and (
            len(kandidaten) == 1 or schluessel[0] < schluessel[1])
        krows = tabellen[kind]
        eintrag.update({
            "eltern": kandidaten[0][0] if sicher else None,
            "gleich": kandidaten[0][1] if kandidaten else 0,
            "ohne_ziel": kandidaten[0][2] if kandidaten else len(krows),
            "sicher": sicher,
        })
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
    return leite_beziehungen_ab(alle)


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
