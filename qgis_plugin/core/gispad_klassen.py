#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Objektklassen und Ausfuehrung der GISPAD-Uebernahme.

Hier stehen die drei Arbeitsgaenge als aufrufbare Funktionen - ohne
Oberflaeche und ohne Kommandozeile, damit Dialog und Skript dieselbe Logik
benutzen und nicht auseinanderlaufen:

    analysiere(gdb)                 Was steckt im Export, wie haengt es zusammen
    exportiere_alles(gdb, ziel)     Vollsicherung, verlustfrei
    exportiere_fachlich(gdb, ...)   Fachliche Auswahl je Objektklasse

Jede Funktion nimmt ein `melde(prozent, text)` entgegen, damit der Dialog
Fortschritt zeigen kann.
"""

import os

# Drei Wege, je nachdem wie das Modul geladen wird: als installiertes
# QGIS-Plugin, als Teil des Pakets, oder eigenstaendig aus tools/ heraus
# (dort wird core/gispad.py vorher unter dem Namen "gispad" geladen).
_NAMEN = ("oeffne", "lies", "gefuellte_tabellen",
          "beziehungen_mit_geometrie", "geometrie_gruppe",
          "kette_nach_oben", "lies_referenzliste", "loese_auf", "als_bool",
          "gruppiere_nach_fkey", "aggregiere", "ogr_modul", "LISTEN_DIR",
          "stil_datei", "setze_vorgabestil")

_gispad = None
for _versuch in ("qgis_new_project_plugin.core.gispad", ".gispad", "gispad"):
    try:
        if _versuch.startswith("."):
            from . import gispad as _gispad
        else:
            import importlib
            _gispad = importlib.import_module(_versuch)
        break
    except ImportError:
        _gispad = None
if _gispad is None:
    raise ImportError("core/gispad.py nicht ladbar")

(oeffne, lies, gefuellte_tabellen, beziehungen_mit_geometrie,
 geometrie_gruppe, kette_nach_oben, lies_referenzliste, loese_auf,
 als_bool, gruppiere_nach_fkey, aggregiere, ogr_modul,
 LISTEN_DIR, stil_datei,
 setze_vorgabestil) = (getattr(_gispad, _n) for _n in _NAMEN)


# ── Objektklassen ───────────────────────────────────────────────────────────
#
# "kopf"      Einzelwerte: (Zielfeld, Quelltabelle, Quellfeld, Typ).
#             Quelltabelle "geom" = Geometrie-Layer selbst (Tabelle LINFOS).
# "sammeln"   1:n-Tabellen, je Objekt zu einer Textspalte zusammengefasst.
# "klartext"  Zielspalte -> (Codespalte, CSV der OSIRIS-Liste).
#
# Die Zuordnung Feld -> Tabelle stammt aus den DV-Verfahrensbeschreibungen des
# LANUV. Fuer BT ist sie dort vollstaendig belegt (V2020a). Die BK-Fassung
# (v2019a) und die MAKO/MAS-Fassung (v2016a) fuehren keine bzw. nur teilweise
# eine Tabellenspalte - deren Eintraege sind als Erwartung zu lesen und
# werden zur Laufzeit gegen den Export geprueft. Fehlt eine Tabelle, bleiben
# die zugehoerigen Spalten leer und es gibt einen Befund, statt eines
# Abbruchs.

OBJEKTKLASSEN = {
    "BT": {
        "name": "Biotoptypen",
        "geometrie": ("BT_Polygon", "BT_Polyline", "BT_Point"),
        # Die ersten vier Felder tragen BEWUSST die Namen, die der
        # LANUK-Konverter vergibt (KENNUNG, BT_CODE, FL_HA, GISPADID).
        # Damit laesst sich das mitgelieferte QML "BIOTOP_v2020_polygon.qml"
        # ohne jede Aenderung auf das Ergebnis legen - es kategorisiert ueber
        # BT_CODE. Gegen die Ausgabe des offiziellen Konverters geprueft:
        # KENNUNG, BT_CODE und FL_HA stimmten bei allen 681 Objekten eines
        # Testdatensatzes ueberein.
        "kopf": [
            ("KENNUNG",   "geom",     "KENNUNG",     "str"),
            ("BT_CODE",   "BtypHtyp", "Biotoptyp",   "str"),
            ("FL_HA",     "geom",     "FLAECHE",     "real"),
            ("GISPADID",  "geom",     "GISPADID",    "int"),
            ("Objektbez", "geom",     "OBJBEZ",      "str"),
            # LR-Typ steht in OEKOTYP, nicht in den FFH_*-Feldern
            # (DV-Verfahrensbeschreibung BT V2020a, S. 4).
            ("LR_Typ",    "BtypHtyp", "Oekotyp",     "str"),
            ("P62",       "BtypHtyp", "ist_P62_typ", "bool"),
            ("P62_Typ",   "BtypHtyp", "P62_Typ",     "str"),
            ("FFH_LRT",   "BtypHtyp", "ist_FFHLRT",  "bool"),
        ],
        "sammeln": [
            ("Zusatzcodes",      "Zusatzcodes", "Zusatzcode", ", "),
            ("Zusatz_Bemerkung", "Zusatzcodes", "Bemerkung",  "; "),
            # Beeintraechtigung der EINZELFLAECHE. Die Tabelle GEFAEHRD
            # bedient zwei Ebenen, unterschieden nur dadurch, woran sie
            # haengt: am Gebietsobjekt die Gefaehrdung des ganzen Gebiets
            # (Feld Gef_Code, EU-Codes des Natura-2000-Standarddatenbogens),
            # an der Biotopflaeche deren Beeintraechtigung (Feld GEFAEHRD,
            # Referenzlisten-Klartext). In einem Testdatensatz war die
            # Trennung vollstaendig: 27 Zeilen am Gebiet trugen nur
            # Gef_Code, 2 Zeilen an Flaechen nur GEFAEHRD.
            # Hier zaehlt deshalb GEFAEHRD - Gef_Code gehoert ins
            # Gebietsprofil, nicht hierher.
            ("Beeintraechtigung", "GEFAEHRD", "GEFAEHRD", "; "),
        ],
        "klartext": {
            "BT_TEXT":          ("BT_CODE",     "biotoptypen.csv"),
            "LR_Typ_Text":      ("LR_Typ",      "lebensraumtypen.csv"),
            "Zusatzcodes_Text": ("Zusatzcodes", "zusatzcodes.csv"),
        },
        "abgeleitet": {"LR_Art": "lr_art"},
        # Layerstil, der nach der Uebernahme als Vorgabe im GeoPackage
        # hinterlegt wird: Zielayer -> QML in data/gispad.
        #
        # Es ist das Original des LANUK ("BIOTOP_v2020_polygon.qml"),
        # unveraendert: Es kategorisiert ueber BT_CODE und beschriftet aus
        # KENNUNG und BT_CODE - alles Felder, die oben genau so heissen.
        # Nur der Polygonlayer bekommt ihn; auf Linien oder Punkte gelegt
        # waere ein Flaechenstil wirkungslos.
        "stil": {"BT_Polygon": "BIOTOP_v2020_polygon.qml"},
    },
    "BK": {
        "name": "Biotopkataster",
        "geometrie": ("BK_Polygon", "BK_Polyline", "BK_Point"),
        "kopf": [
            ("Kennung",      "geom", "KENNUNG",    "str"),
            ("Gispad_ID",    "geom", "GISPADID",   "int"),
            ("Objektbez",    "geom", "OBJBEZ",     "str"),
            ("Objektbeschr", "geom", "OBJBESCHR",  "str"),
            ("Schutzziel",   "geom", "SCHUTZZIEL", "str"),
        ],
        "sammeln": [],
        "klartext": {},
        "abgeleitet": {},
    },
    "FFH": {
        "name": "FFH-Gebiete",
        # Der LANUK-Konverter schreibt je Gebiet einen eigenen Layer
        # (FFH_DE-4305-301) mit KENNUNG, OBJBEZ und GISPADID. Diese drei
        # Namen werden uebernommen; die uebrigen Felder kommen hinzu.
        "geometrie": ("FFH",),
        "kopf": [
            ("KENNUNG",     "geom", "KENNUNG",          "str"),
            ("OBJBEZ",      "geom", "OBJBEZ",           "str"),
            ("GISPADID",    "geom", "GISPADID",         "int"),
            ("FL_HA",       "geom", "FLAECHE",          "real"),
            ("Objektbeschr", "geom", "OBJBESCHR",       "str"),
            ("Schutzziel",  "geom", "SCHUTZZIEL",       "str"),
            ("Entwicklungsziel", "geom", "ENTWICKLUNGSZIEL", "str"),
        ],
        # Gefaehrdung des GANZEN Gebiets - im Gegensatz zur
        # Beeintraechtigung der Einzelflaeche im BT-Profil. Dieselbe Tabelle
        # GEFAEHRD, aber das andere Feld: hier der EU-Code aus dem
        # Natura-2000-Standarddatenbogen, dort der Referenzlisten-Klartext.
        "sammeln": [
            ("Gefaehrdung",      "GEFAEHRD", "Gef_Code",   ", "),
            ("Gef_Intensitaet",  "GEFAEHRD", "Gef_Intens", ", "),
        ],
        "klartext": {
            "Gefaehrdung_Text": ("Gefaehrdung", "beeintraechtigungen.csv"),
        },
        "abgeleitet": {},
    },
    "MAS": {
        "name": "Maßnahmen (MAKO)",
        "geometrie": ("MAS_Polygon", "MAS_Polyline", "MAS_Point",
                      "MAS2_Polygon", "MAS2_Polyline", "MAS2_Point"),
        "kopf": [
            ("Kennung",   "geom", "KENNUNG",  "str"),
            ("Gispad_ID", "geom", "GISPADID", "int"),
            ("Objektbez", "geom", "OBJBEZ",   "str"),
        ],
        "sammeln": [
            ("Massnahmen",   "MASSN",      "MASSN",       ", "),
            ("Ziel_Pflanze", "MassnArten", "Pflanzenart", ", "),
            ("Ziel_Tier",    "MassnArten", "Tierart",     ", "),
        ],
        "klartext": {},
        "abgeleitet": {},
    },
}


def lr_art(satz):
    """
    FFH-LRT oder N-LRT aus dem LR-Typ.

    FFH-Lebensraumtypen tragen den vierstelligen FFH-Code (3150, 7120, auch
    91D0 - Buchstaben kommen vor), die uebrigen beginnen mit "N" (NDC0). Die
    Regel "beginnt nicht mit N" deckte sich in einem Testexport mit dem Flag
    ist_FFHLRT fuer alle 1322 Zeilen.
    """
    t = (satz.get("LR_Typ") or "").strip().upper()
    if not t:
        return None
    return "N-LRT" if t.startswith("N") else "FFH-LRT"


ABGELEITET = {"lr_art": lr_art}


def _nichts(_p=0, _t=""):
    pass


#: Feldnamen, die erfahrungsgemaess personenbezogene Angaben tragen.
#: Die DV-Verfahrensbeschreibung BT (V2020a, S. 27) haelt ausdruecklich fest,
#: dass solche Angaben nicht an die Landesdatenbank gehen duerfen. Die
#: Vollsicherung nimmt sie bewusst MIT - sie soll nichts verlieren - meldet
#: aber, wo sie stehen, damit die Datei nicht unbesehen weitergereicht wird.
PERSONENBEZOGEN = ("ansprechpartner", "email", "e_mail", "anschrift",
                   "betreuer", "adresse", "telefon", "bearbeiter", "name")


def pruefe_personenbezug(tabelle, spalten, zeilen):
    """Namen der Felder, die belegt sind und nach Personenbezug aussehen."""
    treffer = []
    for feld, _typ in spalten:
        if feld.lower() not in PERSONENBEZOGEN:
            continue
        if any(z.get(feld) not in (None, "") for _i, z in zeilen):
            treffer.append(feld)
    return treffer


# ── Analyse ─────────────────────────────────────────────────────────────────

def analysiere(gdb, melde=_nichts):
    """
    Export sichten.

    Rueckgabe: {
      "gefuellt":  {name: zeilen},
      "geometrie": [name, ...],
      "klassen":   {"BT": {"name":..., "layer":[...], "objekte":n}, ...},
      "beziehungen": {kind: {...}},
      "unbekannt": [name, ...]       Geometrie-Layer ohne bekannte Objektklasse
    }
    """
    melde(5, "Öffne Geodatabase …")
    ds = oeffne(gdb)
    melde(15, "Suche gefüllte Tabellen …")
    gefuellt = gefuellte_tabellen(ds)

    geo, sach = [], {}
    for name in gefuellt:
        if ds.GetLayerByName(name).GetGeomType() != 100:
            geo.append(name)
    melde(35, f"{len(gefuellt)} gefüllte Tabellen – lese Sachdaten …")
    for name in gefuellt:
        if name in geo:
            continue
        zeilen, _ = lies(ds, name)
        if zeilen:
            sach[name] = zeilen

    melde(70, "Leite Beziehungen ab …")
    bez = beziehungen_mit_geometrie(ds, geo, sach)

    klassen = {}
    erkannt = set()
    for kuerzel, profil in OBJEKTKLASSEN.items():
        layer = [g for g in profil["geometrie"] if g in gefuellt]
        if layer:
            klassen[kuerzel] = {
                "name": profil["name"],
                "layer": layer,
                "objekte": sum(gefuellt[n] for n in layer),
            }
            erkannt.update(layer)

    melde(100, "Analyse fertig.")
    return {
        "gefuellt": gefuellt,
        "geometrie": geo,
        "klassen": klassen,
        "beziehungen": bez,
        "unbekannt": sorted(set(geo) - erkannt),
    }


# ── Hierarchie aufloesen ────────────────────────────────────────────────────

def _pfad_von_oben(beziehungen, ziel, wurzel, gesehen=None):
    """
    Weg von `wurzel` hinab zu `ziel`, oder None.

    Gesucht wird ueber ALLE widerspruchsfreien Kandidaten, nicht nur ueber
    den bestbewerteten Elternteil. Eine Sachtabelle kann naemlich an
    mehreren Objektklassen zugleich haengen: GEFAEHRD traegt am Gebiet die
    Gefaehrdung des ganzen Gebiets und an der Einzelflaeche deren
    Beeintraechtigung. Wuerde nur der haeufigste Elternteil zaehlen, fiele
    die seltenere Ebene stumm weg - in einem Testdatensatz waeren das 2 von
    29 Zeilen gewesen.
    """
    gesehen = gesehen or set()
    if ziel in gesehen:
        return None
    eintrag = beziehungen.get(ziel) or {}
    kandidaten = [k for k, _g, _o in eintrag.get("kandidaten", [])]
    # Den bestbewerteten Elternteil zuerst pruefen, damit das Ergebnis bei
    # mehreren moeglichen Wegen stabil bleibt.
    bester = eintrag.get("eltern")
    if bester in kandidaten:
        kandidaten = [bester] + [k for k in kandidaten if k != bester]
    for kandidat in kandidaten:
        if kandidat == wurzel:
            return [ziel]
        oben = _pfad_von_oben(beziehungen, kandidat, wurzel,
                              gesehen | {ziel})
        if oben is not None:
            return oben + [ziel]
    return None


def _zeilen_zu_objekt(pfad, index, start_pkey):
    """
    Zeilen der letzten Tabelle des Pfades, die zu `start_pkey` gehoeren.

    Stufe fuer Stufe absteigen, wie das Modell es vorsieht. Ein Direktsprung
    ueber GISPADID wuerde die Zwischenebenen verlieren.
    """
    aktuell = {start_pkey}
    zeilen = []
    for tabelle in pfad:
        kinder = []
        nach_fkey = index[tabelle]
        for pk in aktuell:
            kinder.extend(nach_fkey.get(pk, []))
        zeilen = kinder
        aktuell = {z["PKEY"] for z in kinder if z.get("PKEY") is not None}
        if not aktuell and tabelle != pfad[-1]:
            return []
    return zeilen


# ── Fachlicher Export ───────────────────────────────────────────────────────

def exportiere_fachlich(gdb, klasse, ziel, listen_dir=None, melde=_nichts):
    """Fachliche Auswahl einer Objektklasse. Rueckgabe: (geschrieben, befunde)."""
    profil = OBJEKTKLASSEN[klasse]
    listen_dir = listen_dir or LISTEN_DIR

    melde(5, "Öffne Geodatabase …")
    ds = oeffne(gdb)
    vorhanden = gefuellte_tabellen(ds)
    geom_layer = [g for g in profil["geometrie"] if g in vorhanden]
    if not geom_layer:
        raise ValueError(
            f"Im Export sind keine Objekte der Klasse {klasse} "
            f"({profil['name']}) enthalten.")

    melde(15, "Lese Sachtabellen …")
    sach = {}
    for name in vorhanden:
        if name in profil["geometrie"]:
            continue
        if ds.GetLayerByName(name).GetGeomType() != 100:
            continue
        zeilen, _ = lies(ds, name)
        if zeilen:
            sach[name] = zeilen

    melde(35, "Leite Beziehungen ab …")
    bez = beziehungen_mit_geometrie(ds, geom_layer, sach)
    wurzel = geometrie_gruppe(geom_layer)
    index = {t: gruppiere_nach_fkey(z) for t, z in sach.items()}

    listen = {}
    for zielspalte, (_code, datei) in profil["klartext"].items():
        listen[zielspalte] = lies_referenzliste(
            os.path.join(listen_dir, datei))

    spalten = [(z, t) for z, _q, _f, t in profil["kopf"]]
    spalten += [(z, "str") for z in profil["abgeleitet"]]
    spalten += [(z, "str") for z, _t, _f, _s in profil["sammeln"]]
    spalten += [(z, "str") for z in profil["klartext"]]

    benoetigt = {q for _z, q, _f, _t in profil["kopf"] if q != "geom"}
    benoetigt |= {t for _z, t, _f, _s in profil["sammeln"]}
    befunde = []
    for t in sorted(benoetigt):
        if t not in sach:
            befunde.append(
                f"Tabelle \u201e{t}\u201c fehlt oder ist leer \u2013 die "
                f"daraus gespeisten Spalten bleiben leer.")

    bloecke = []
    for nr, gname in enumerate(geom_layer):
        melde(45 + int(35 * nr / max(len(geom_layer), 1)),
              f"Verarbeite {gname} …")
        gzeilen, geoms = lies(ds, gname, mit_geometrie=True)
        pfade = {}
        for t in benoetigt:
            if t in sach:
                p = _pfad_von_oben(bez, t, wurzel)
                if p is None:
                    befunde.append(
                        f"Tabelle \u201e{t}\u201c l\u00e4sst sich nicht "
                        f"mit {gname} verkn\u00fcpfen \u2013 Spalten "
                        f"bleiben leer.")
                else:
                    pfade[t] = p

        saetze = []
        for i, gz in enumerate(gzeilen):
            pk = gz.get("PKEY")
            satz = {}
            for zielspalte, quelle, feld, typ in profil["kopf"]:
                if quelle == "geom":
                    roh = gz.get(feld)
                else:
                    zs = (_zeilen_zu_objekt(pfade[quelle], index, pk)
                          if quelle in pfade else [])
                    roh = zs[0].get(feld) if zs else None
                if typ == "bool":
                    satz[zielspalte] = als_bool(roh)
                elif typ in ("int", "real"):
                    # Zahlen koennen in der Geodatabase als Text stehen
                    # (GK_RW traegt sogar ein angehaengtes Komma), deshalb
                    # wird umgewandelt statt verlassen. Laesst sich ein Wert
                    # nicht lesen, wird er NULL - nicht 0, sonst waere eine
                    # fehlende Flaechenangabe spaeter von einer Flaeche der
                    # Groesse null nicht mehr zu unterscheiden.
                    wandeln = int if typ == "int" else float
                    try:
                        satz[zielspalte] = (
                            wandeln(str(roh).strip().rstrip(",").replace(
                                ",", "."))
                            if roh not in (None, "") else None)
                    except (TypeError, ValueError):
                        satz[zielspalte] = None
                else:
                    t = None if roh is None else str(roh).strip()
                    satz[zielspalte] = t or None
            for zielspalte, tabelle, feld, trenner in profil["sammeln"]:
                zs = (_zeilen_zu_objekt(pfade[tabelle], index, pk)
                      if tabelle in pfade else [])
                satz[zielspalte] = aggregiere(zs, feld, trenner)
            for zielspalte, fn in profil["abgeleitet"].items():
                satz[zielspalte] = ABGELEITET[fn](satz)
            for zielspalte, (code, _d) in profil["klartext"].items():
                satz[zielspalte] = loese_auf(satz.get(code),
                                             listen.get(zielspalte) or {})
            saetze.append((i, satz))

        lyr = ds.GetLayerByName(gname)
        bloecke.append((gname, lyr.GetGeomType(), lyr.GetSpatialRef(),
                        spalten, saetze, geoms))

    melde(85, "Schreibe GeoPackage …")
    geschrieben = _schreibe(ziel, bloecke)
    _setze_stile(ziel, profil, geschrieben, befunde, melde)
    melde(100, "Fertig.")
    return geschrieben, befunde


def _setze_stile(ziel, profil, geschrieben, befunde, melde=_nichts):
    """
    Die mitgelieferten Layerstile als Vorgabe ins GeoPackage schreiben.

    Fehlt eine Stildatei oder scheitert das Schreiben, ist das ein Befund und
    kein Abbruch: Die Daten sind dann uebernommen und nur ungestylt - und bei
    einer Notfallsicherung sind die Daten das, worauf es ankommt.
    """
    stile = profil.get("stil") or {}
    for layer, datei in sorted(stile.items()):
        if layer not in geschrieben:
            continue
        pfad = stil_datei(datei)
        if not pfad:
            befunde.append(f"Layerstil {datei} fehlt im Plugin – "
                           f"{layer} bleibt ungestylt.")
            continue
        try:
            melde(95, f"Lege Layerstil auf {layer} …")
            setze_vorgabestil(ziel, layer, pfad, stilname="LANUK",
                              beschreibung="Stil des LANUK, unveraendert")
        except Exception as e:                       # noqa: BLE001
            befunde.append(f"Layerstil {datei} nicht gesetzt ({e}).")


# ── Vollsicherung ───────────────────────────────────────────────────────────

def exportiere_alles(gdb, ziel, melde=_nichts, befunde=None):
    """
    Jede gefuellte Tabelle vollstaendig uebernehmen.

    Bewusst stumpf: keine Auswahl, keine Umbenennung, keine Aufloesung. Was
    hier nicht ankommt, ist nach einem Wegfall von GISPAD verloren - deshalb
    hat Vollstaendigkeit Vorrang. Die Schluesselspalten bleiben erhalten,
    damit die Hierarchie rekonstruierbar ist, und die abgeleiteten
    Beziehungen kommen als Tabelle `gispad_beziehungen` mit: der Export
    selbst fuehrt sie nicht mit, und ohne sie waere spaeter nicht mehr zu
    erkennen, welche Tabelle an welcher haengt.
    """
    ogr = ogr_modul()
    melde(5, "Öffne Geodatabase …")
    ds = oeffne(gdb)
    vorhanden = gefuellte_tabellen(ds)

    bloecke = []
    gelesen = {}          # jede Tabelle nur EINMAL von der Platte holen
    gesamt = max(len(vorhanden), 1)
    for nr, (name, n) in enumerate(sorted(vorhanden.items())):
        melde(10 + int(60 * nr / gesamt), f"Lese {name} ({n}) …")
        lyr = ds.GetLayerByName(name)
        hat_geom = lyr.GetGeomType() != 100
        zeilen, geoms = lies(ds, name, mit_geometrie=hat_geom)
        if not zeilen:
            continue
        defn = lyr.GetLayerDefn()
        spalten = []
        for i in range(defn.GetFieldCount()):
            fd = defn.GetFieldDefn(i)
            typ = {ogr.OFTInteger: "int", ogr.OFTInteger64: "int",
                   ogr.OFTReal: "real"}.get(fd.GetType(), "str")
            spalten.append((fd.GetName(), typ))
        saetze = list(enumerate(zeilen))
        if befunde is not None:
            pb = pruefe_personenbezug(name, spalten, saetze)
            if pb:
                befunde.append(
                    f"{name}: enth\u00e4lt personenbezogene Angaben "
                    f"({', '.join(pb)}). Vor einer Weitergabe pr\u00fcfen.")
        gelesen[name] = zeilen
        bloecke.append((name, lyr.GetGeomType() if hat_geom else 100,
                        lyr.GetSpatialRef() if hat_geom else None,
                        spalten, saetze, geoms))

    melde(75, "Leite Beziehungen ab …")
    geo = [n for n in vorhanden
           if ds.GetLayerByName(n).GetGeomType() != 100]
    sach = {n: z for n, z in gelesen.items() if n not in geo and z}
    bez = beziehungen_mit_geometrie(ds, geo, sach)
    bz_spalten = [("tabelle", "str"), ("eltern", "str"), ("zeilen", "int"),
                  ("befund", "str"), ("kette", "str")]
    bz = []
    for i, kind in enumerate(sorted(bez)):
        info = bez[kind]
        bz.append((i, {
            "tabelle": kind,
            "eltern": info["eltern"] or "",
            "zeilen": info["gleich"],
            "befund": "eindeutig" if info["sicher"] else (
                "mehrdeutig" if info["kandidaten"] else "kein Treffer"),
            "kette": " -> ".join(reversed(kette_nach_oben(bez, kind)))
            if info["sicher"] else ", ".join(
                k for k, _g, _o in info["kandidaten"][:6]),
        }))
    if bz:
        bloecke.append(("gispad_beziehungen", 100, None, bz_spalten, bz, []))

    melde(85, "Schreibe GeoPackage …")
    geschrieben = _schreibe(ziel, bloecke)
    melde(100, "Fertig.")
    return geschrieben


# ── Schreiben ───────────────────────────────────────────────────────────────

def _schreibe(pfad, bloecke):
    ogr = ogr_modul()
    if os.path.exists(pfad):
        os.remove(pfad)
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(pfad)
    if ds is None:
        raise IOError(f"GeoPackage nicht anlegbar: {pfad}")

    typ_map = {"str": ogr.OFTString, "int": ogr.OFTInteger,
               "real": ogr.OFTReal}
    geschrieben = {}
    for name, wkb_typ, srs, spalten, saetze, geoms in bloecke:
        if not saetze:
            continue
        lyr = ds.CreateLayer(name, srs,
                             wkb_typ if wkb_typ != 100 else ogr.wkbNone)
        for feld, typ in spalten:
            if typ == "bool":
                fd = ogr.FieldDefn(feld, ogr.OFTInteger)
                fd.SetSubType(ogr.OFSTBoolean)
            else:
                fd = ogr.FieldDefn(feld, typ_map.get(typ, ogr.OFTString))
            lyr.CreateField(fd)
        defn = lyr.GetLayerDefn()
        typen = dict(spalten)
        lyr.StartTransaction()
        for gi, satz in saetze:
            feat = ogr.Feature(defn)
            for feld, wert in satz.items():
                if wert is None or feld not in typen:
                    continue
                if typen[feld] == "bool":
                    feat.SetField(feld, 1 if wert else 0)
                else:
                    feat.SetField(feld, wert)
            if geoms and gi < len(geoms) and geoms[gi]:
                feat.SetGeometry(ogr.CreateGeometryFromWkb(geoms[gi]))
            lyr.CreateFeature(feat)
            feat = None
        lyr.CommitTransaction()
        geschrieben[name] = len(saetze)
    ds = None
    return geschrieben
