"""
core/mako.py - MAKO-Produkte aus einem GISPAD-Export (Notloesung).

Der MAKO-Konverter des LANUK ist ausser Betrieb. Dieses Modul erzeugt die
Grundlage fuer Massnahmentabelle und Ziel-/Massnahmenkarte selbst, und zwar
nur mit OGR: es laeuft in QGIS ohne Zusatzpakete und genauso auf der
Kommandozeile.

Datengrundlage (gegen einen echten Stationsexport geprueft):

  MAS_*            Massnahmenflaeche (LINFOS): KENNUNG, OBJBEZ, OBJBESCHR,
                   FLAECHE, AUFHINWVON
  MASSN            Einzelmassnahme, haengt an der Flaeche: MASSN (Kurzname,
                   OHNE Nummer), Massnahm_Typ, Zeit_Prio, MassnBeschreib ...
  Massn_LRT        Ziel-LRT JE MASSNAHME (Ziel_LRT, ProzAnt)
  Massn_GB         Ziel-§42-Biotop JE MASSNAHME (Ziel_GB_Typ, ProzAnt)
  MassnArten(_Pflanze)  Zielarten je Massnahme
  Ziele            Entwicklungsziel der Flaeche (Erlaeuterung)
  Zielbiotoptypen  haengt an Ziele: Zielbiotoptyp (BT-Code)
  BtypHtyp         an der MAS-Flaeche: der Bestand, den GISPAD beim Anlegen
                   aus BT verschnitten hat (Biotoptyp, Oekotyp, P62_Typ,
                   Flaeche in ha)
  GEFAEHRD         nur an BT - Beeintraechtigungen kommen daher ueber eine
                   echte Verschneidung MAS x BT
  BAUM_Point       Biotopbaeume, gezaehlt je Massnahmenflaeche

Verknuepft wird ueber PKEY -> FKEY (mit GISPADID-Gegenprobe, siehe
gispad.leite_beziehungen_ab), nicht ueber die GISPADID allein. Die GISPADID
dient nur dazu, die Zeilen der Objektklasse MAS von denen anderer Klassen zu
trennen - Sachtabellen wie BtypHtyp oder MASSN bedienen BT und MAS zugleich.

Alle Flaechen werden vor der Verschneidung repariert und nach der
Rechte-Hand-Regel ausgerichtet (gispad.repariere_flaeche).
"""

import csv
import os
import re

_NAMEN = ("oeffne", "lies", "gefuellte_tabellen", "beziehungen_mit_geometrie",
          "lies_referenzliste", "ogr_modul", "LISTEN_DIR", "repariere_flaeche",
          "befund_reparatur", "gruppiere_nach_fkey")

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
 lies_referenzliste, ogr_modul, LISTEN_DIR, repariere_flaeche,
 befund_reparatur, gruppiere_nach_fkey) = (
    getattr(_gispad, _n) for _n in _NAMEN)

_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAKO_DIR = os.path.join(_PLUGIN_DIR, "data", "mako")

#: Zeitliche Priorisierung (MAS v2016a, REF_ZeitPrio)
ZEIT_PRIO = {"1": "sofort", "2": "Beginn innerhalb 5 Jahren",
             "3": "Beginn innerhalb 10 Jahren", "4": "Beginn nach 10 Jahren"}

#: Flaechen unter dieser Groesse (ha) gelten als Verschneidungsrest. Der
#: LANUK-Konverter hat dafuer ein Sliver-Kriterium benutzt; im Muster stehen
#: trotzdem Zeilen mit "0,000 ha". 10 m² sind bei 1:5.000 nicht darstellbar.
MIN_HA = 0.001

#: Zielbiotopgruppen, fuer die die Vorgaben von Wald und Holz NRW gelten
WALD_ZIELGRUPPEN = ("Laubwald", "nicht heimischer Laubwald", "Nadelwald")

KEIN_LRT = "kein lrt"
KEIN_GB = "kein § 30/§ 42 biotoptyp"


def _nichts(_p=0, _t=""):
    pass


# ── Listen ──────────────────────────────────────────────────────────────────

def _csv(name):
    pfad = os.path.join(MAKO_DIR, name)
    if not os.path.isfile(pfad):
        return []
    with open(pfad, encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter=";"))


class Listen:
    """Alle Referenzlisten, einmal geladen."""

    def __init__(self, listen_dir=None):
        ld = listen_dir or LISTEN_DIR
        self.massnahmen = {r["name"].strip(): r for r in
                           _csv("massnahmen_mako.csv")}
        self.gruppen = sorted(
            ((r["praefix"].strip(), r["gruppe"].strip(), r["farbe"].strip())
             for r in _csv("zielbiotopgruppen.csv")),
            key=lambda t: -len(t[0]))
        self.gb_nr = {r["name"].strip(): r["nr"].strip()
                      for r in _csv("gesetzlich_geschuetzte_biotope.csv")}
        self.biotope = lies_referenzliste(os.path.join(ld, "biotoptypen.csv"))
        self.lrt = lies_referenzliste(os.path.join(ld, "lebensraumtypen.csv"))

    def massnahme(self, kurzname):
        """(nr, gruppe) zu einem Massnahmen-Kurznamen."""
        r = self.massnahmen.get((kurzname or "").strip())
        if not r:
            return "", ""
        return r.get("nr", ""), r.get("gruppe", "")

    def zielgruppe(self, bt_code):
        """(gruppe, farbe) zu einem Ziel-Biotoptyp-Code, laengstes Praefix."""
        code = (bt_code or "").strip()
        # Kartierzusaetze wie 'x'/'y'/'z' vor dem Code (zEA1) ignorieren
        if len(code) > 1 and code[0] in "xyz" and code[1].isupper():
            code = code[1:]
        for praefix, gruppe, farbe in self.gruppen:
            if code.startswith(praefix):
                return gruppe, farbe
        return "", ""

    def biotop(self, code):
        return self.biotope.get((code or "").strip()) or (code or "")

    def lrt_text(self, code):
        """'Trockene Heidegebiete (4030)', 'noch kein LRT'."""
        c = (code or "").strip()
        if not c or c.lower() == KEIN_LRT:
            return "noch kein LRT"
        name = self.lrt.get(c)
        return f"{name} ({c})" if name else c

    def gb_text(self, name, mit_nr=True):
        n = (name or "").strip()
        nr = self.gb_nr.get(n, "")
        return f"{n}, {nr}" if (mit_nr and nr) else n


# ── Hilfen ──────────────────────────────────────────────────────────────────

def _t(w):
    """Text oder None."""
    if w is None:
        return None
    s = str(w).strip()
    return s or None


def _zahl(w):
    try:
        return float(str(w).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def ha(w, stellen=3):
    """Deutsche Schreibweise: 2,130 ha"""
    if w is None:
        return ""
    return f"{w:,.{stellen}f}".replace(",", "X").replace(".", ",").replace(
        "X", ".")


def _prozent(w):
    z = _zahl(w)
    if z is None:
        return ""
    return f"{z:g}".replace(".", ",") + " %"


def natuerlich(s):
    """Sortierschluessel: '2 x' vor '10 x', 'M-002' vor 'M-010'."""
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r"(\d+)", s or "")]


def _ohne_doppelte(werte):
    gesehen, aus = set(), []
    for w in werte:
        if w and w not in gesehen:
            gesehen.add(w)
            aus.append(w)
    return aus


# ── Beziehungen auf die Objektklasse einschraenken ──────────────────────────

def _klassen_tabellen(ds, geom_layer, ids, vorhanden):
    """
    Sachtabellen lesen, aber nur die Zeilen der Objekte `ids` behalten.

    Die Sachtabellen eines Exports bedienen alle Objektklassen zugleich.
    Ohne diese Trennung wuerde BtypHtyp z. B. der BT-Geometrie zugeschlagen
    (dort sind mehr Zeilen) und die MAS-Zeilen blieben ohne Elternteil.
    """
    sach = {}
    for name in vorhanden:
        if name in geom_layer:
            continue
        lyr = ds.GetLayerByName(name)
        if lyr is None or lyr.GetGeomType() != 100:
            continue
        zeilen, _ = lies(ds, name)
        zeilen = [z for z in zeilen if z.get("GISPADID") in ids]
        if zeilen:
            sach[name] = zeilen
    return sach


def _pfad(bez, ziel, wurzel, gesehen=frozenset()):
    """Weg von der Wurzel zu `ziel` ueber widerspruchsfreie Kandidaten."""
    if ziel in gesehen:
        return None
    eintrag = bez.get(ziel) or {}
    kand = [k for k, _g, _o in eintrag.get("kandidaten", [])]
    bester = eintrag.get("eltern")
    if bester in kand:
        kand = [bester] + [k for k in kand if k != bester]
    for k in kand:
        if k == wurzel:
            return [ziel]
        oben = _pfad(bez, k, wurzel, gesehen | {ziel})
        if oben is not None:
            return oben + [ziel]
    return None


class _Baum:
    """Absteigen von einem Objekt zu den Zeilen einer Sachtabelle."""

    def __init__(self, bez, sach, wurzel):
        self.bez, self.wurzel = bez, wurzel
        self.index = {t: gruppiere_nach_fkey(z) for t, z in sach.items()}
        self._pfade = {}

    def pfad(self, tabelle):
        if tabelle not in self._pfade:
            self._pfade[tabelle] = (_pfad(self.bez, tabelle, self.wurzel)
                                    if tabelle in self.index else None)
        return self._pfade[tabelle]

    def zeilen(self, tabelle, pkey, gid):
        """Zeilen von `tabelle` unter dem Objekt (pkey, gid)."""
        p = self.pfad(tabelle)
        if not p:
            return []
        aktuell, zeilen = {pkey}, []
        for t in p:
            kinder = []
            for pk in aktuell:
                kinder.extend(z for z in self.index[t].get(pk, [])
                              if z.get("GISPADID") == gid)
            zeilen = kinder
            aktuell = {z["PKEY"] for z in kinder if z.get("PKEY") is not None}
        return zeilen

    def unter(self, tabelle, eltern_tabelle, eltern_zeile):
        """Direkte Kinder einer Zeile (z. B. Massn_LRT unter einer MASSN)."""
        if tabelle not in self.index:
            return []
        pk, gid = eltern_zeile.get("PKEY"), eltern_zeile.get("GISPADID")
        return [z for z in self.index[tabelle].get(pk, [])
                if z.get("GISPADID") == gid]


# ── Geometrie ───────────────────────────────────────────────────────────────

def _geometrien(ds, layer_namen, befunde, ogr):
    """{(layer, i): (zeile, geometrie)} - repariert, mit Rechte-Hand-Regel."""
    aus = []
    for name in layer_namen:
        zeilen, wkbs = lies(ds, name, mit_geometrie=True)
        zaehler = {}
        for z, w in zip(zeilen, wkbs):
            g = ogr.CreateGeometryFromWkb(bytes(w)) if w else None
            if g is not None and name.endswith(("_Polygon", "Polygon")):
                g, b = repariere_flaeche(g)
                if b:
                    zaehler[b] = zaehler.get(b, 0) + 1
            aus.append((name, z, g))
        txt = befund_reparatur(name, zaehler)
        if txt:
            befunde.append(txt)
    return aus


def _schnitt_ha(a, b):
    if a is None or b is None:
        return 0.0
    if not a.GetEnvelope() or not _huellen_ueberlappen(a, b):
        return 0.0
    try:
        s = a.Intersection(b)
    except Exception:                                # noqa: BLE001
        return 0.0
    return (s.GetArea() / 10000.0) if s is not None else 0.0


def _huellen_ueberlappen(a, b):
    ax1, ax2, ay1, ay2 = a.GetEnvelope()
    bx1, bx2, by1, by2 = b.GetEnvelope()
    return not (ax2 < bx1 or bx2 < ax1 or ay2 < by1 or by2 < ay1)


# ── Auswertung ──────────────────────────────────────────────────────────────

def sammle(gdb, ffh_wkbs=None, min_ha=MIN_HA, melde=_nichts, listen=None):
    """
    MAS-Objekte eines Exports mit allem, was Tabelle und Karte brauchen.

    ffh_wkbs: Flaechen der FFH-Gebietsgrenze als WKB im Koordinatensystem
    des Exports, oder None. Ohne sie gibt es keine Aufteilung in Teilflaechen
    inner- und ausserhalb.

    Rueckgabe: dict mit 'titel', 'flaechen' (Liste), 'srs', 'befunde'.
    """
    ogr = ogr_modul()
    listen = listen or Listen()
    befunde = []

    melde(5, "Öffne Geodatabase …")
    ds = oeffne(gdb)
    vorhanden = gefuellte_tabellen(ds)
    mas_layer = [n for n in ("MAS_Polygon", "MAS_Polyline", "MAS_Point",
                             "MAS2_Polygon", "MAS2_Polyline", "MAS2_Point")
                 if n in vorhanden]
    if not mas_layer:
        raise ValueError("Im Export sind keine Maßnahmenflächen (MAS) "
                         "enthalten.")

    melde(10, "Lese Maßnahmenflächen …")
    mas = _geometrien(ds, mas_layer, befunde, ogr)
    ids = {z.get("GISPADID") for _n, z, _g in mas}
    srs = ds.GetLayerByName(mas_layer[0]).GetSpatialRef()

    melde(20, "Lese Sachtabellen …")
    sach = _klassen_tabellen(ds, mas_layer, ids, vorhanden)
    melde(30, "Leite Beziehungen ab …")
    bez = beziehungen_mit_geometrie(ds, mas_layer, sach)
    wurzel = "MAS_*" if any(n.startswith("MAS_") for n in mas_layer) else \
        "MAS2_*"
    baum = _Baum(bez, sach, wurzel)
    for t in ("MASSN", "BtypHtyp"):
        if t not in sach:
            befunde.append(f"Tabelle „{t}“ fehlt im Export oder hat keine "
                           f"Zeilen zu Maßnahmenflächen.")

    melde(40, "Lese Biotoptypen für die Verschneidung …")
    bt_layer = [n for n in ("BT_Polygon",) if n in vorhanden]
    bt = _geometrien(ds, bt_layer, befunde, ogr) if bt_layer else []
    bt_ids = {z.get("GISPADID") for _n, z, _g in bt}
    bt_sach = _klassen_tabellen(ds, bt_layer, bt_ids, vorhanden) if bt else {}
    bt_baum = None
    if bt_sach:
        bt_bez = beziehungen_mit_geometrie(ds, bt_layer, bt_sach)
        bt_baum = _Baum(bt_bez, bt_sach, "BT_*")
    if not bt:
        befunde.append("Keine BT-Flächen im Export – der Bestand kommt aus "
                       "den von GISPAD an der Maßnahmenfläche gespeicherten "
                       "Angaben (können veraltet sein), Beeinträchtigungen "
                       "fehlen.")

    baeume = []
    if "BAUM_Point" in vorhanden:
        baeume = [g for _n, _z, g in _geometrien(ds, ["BAUM_Point"],
                                                 befunde, ogr) if g]
    else:
        befunde.append("Keine Biotopbäume (BAUM) im Export – die Anzahl "
                       "bleibt offen.")

    ffh = None
    if ffh_wkbs:
        ffh = ogr.Geometry(ogr.wkbMultiPolygon)
        for w in ffh_wkbs:
            g, _b = repariere_flaeche(ogr.CreateGeometryFromWkb(bytes(w)))
            if g is None:
                continue
            for i in range(g.GetGeometryCount()):
                ffh.AddGeometry(g.GetGeometryRef(i))
        ffh = ffh.UnionCascaded() if ffh.GetGeometryCount() else None

    titel = None
    flaechen = []
    gesamt = max(len(mas), 1)
    for nr, (lname, z, geom) in enumerate(mas):
        melde(45 + int(45 * nr / gesamt),
              f"Werte {z.get('OBJBEZ') or z.get('KENNUNG')} aus …")
        pk, gid = z.get("PKEY"), z.get("GISPADID")
        titel = titel or _t(z.get("AUFHINWVON")) or _t(z.get("AUFHINVON"))
        f = _flaeche(z, geom, pk, gid, baum, listen, min_ha)

        # Bestand und Beeintraechtigungen: Verschneidung mit den aktuellen
        # BT-Flaechen. Die Bestandszeilen, die GISPAD beim Anlegen einer
        # Massnahmenflaeche nach BtypHtyp kopiert, sind dafuer nicht
        # brauchbar: im Testexport waren sie teils verdoppelt (Anteil 200 %),
        # teils veraltet (6,8 von 47,8 ha), bei 11 von 45 Flaechen fehlten
        # sie ganz. Der LANUK-Konverter hat ebenfalls selbst verschnitten.
        beeintr, ehz, bts = [], [], []
        teile = {"gesamt": ({}, {}), "innen": ({}, {}), "aussen": ({}, {})}

        def buche(teil, c, p62, fl):
            lrt_d, gb_d = teile[teil]
            lrt_d[c] = lrt_d.get(c, 0.0) + fl
            if p62 and p62.lower() != KEIN_GB:
                gb_d[p62] = gb_d.get(p62, 0.0) + fl

        verschnitten = False
        if geom is not None and bt and bt_baum and _ist_flaeche(geom, ogr):
            verschnitten = True
            for _bn, bz, bg in bt:
                if bg is None or not _huellen_ueberlappen(geom, bg):
                    continue
                try:
                    schnitt = geom.Intersection(bg)
                except Exception:                    # noqa: BLE001
                    continue
                fl_s = schnitt.GetArea() / 10000.0 if schnitt else 0.0
                if fl_s < min_ha:
                    continue
                fl_in = _schnitt_ha(schnitt, ffh) if ffh is not None else None
                bpk, bgid = bz.get("PKEY"), bz.get("GISPADID")
                for gz in bt_baum.zeilen("GEFAEHRD", bpk, bgid):
                    b = _t(gz.get("GEFAEHRD"))
                    if not b:
                        continue
                    bem = _t(gz.get("Bemerkung"))
                    beeintr.append(f"{b}, {bem}" if bem else b)
                for hz in bt_baum.zeilen("BtypHtyp", bpk, bgid):
                    c = _t(hz.get("Oekotyp")) or "kein LRT"
                    p62 = _t(hz.get("P62_Typ"))
                    buche("gesamt", c, p62, fl_s)
                    if fl_in is not None:
                        if fl_in >= min_ha:
                            buche("innen", c, p62, fl_in)
                        if fl_s - fl_in >= min_ha:
                            buche("aussen", c, p62, fl_s - fl_in)
                    btc = _t(hz.get("Biotoptyp"))
                    if btc and btc != "OZ":
                        bts.append(btc)
                    e = _t(hz.get("Erhaltungszustand"))
                    if e and c.lower() != KEIN_LRT:
                        ehz.append(f"{c}: {e}")

        def sortiert(d):
            return sorted(d.items(), key=lambda kv: -kv[1])

        if verschnitten:
            f["bestand"] = {k: (sortiert(v[0]), sortiert(v[1]))
                            for k, v in teile.items()}
            f["bestand_bt"] = _ohne_doppelte(bts)
            f["bestand_quelle"] = "Verschneidung mit BT"
        else:
            # Rueckfall: was GISPAD an der Massnahmenflaeche gespeichert hat,
            # ohne Aufteilung nach FFH-Gebiet.
            g_ = (f["bestand_lrt"], f["bestand_gb"])
            f["bestand"] = {"gesamt": g_, "innen": g_, "aussen": g_}
            f["bestand_quelle"] = "GISPAD-Übernahme an der Maßnahmenfläche"
        f["bestand_lrt"], f["bestand_gb"] = f["bestand"]["gesamt"]
        f["beeintraechtigungen"] = _ohne_doppelte(beeintr)
        f["erhaltungszustand"] = _ohne_doppelte(ehz)

        if baeume and geom is not None:
            f["biotopbaeume"] = sum(1 for b in baeume if geom.Contains(b))
        else:
            f["biotopbaeume"] = None

        # Teilflaechen innerhalb / ausserhalb FFH
        if ffh is not None and geom is not None and _ist_flaeche(geom, ogr):
            innen = _schnitt_ha(geom, ffh)
            gesamt_ha = geom.GetArea() / 10000.0
            f["ha_innen"] = innen if innen >= min_ha else 0.0
            aussen = gesamt_ha - innen
            f["ha_aussen"] = aussen if aussen >= min_ha else 0.0
        else:
            f["ha_innen"] = f["ha_aussen"] = None

        f["geom"] = geom
        f["layer"] = lname
        flaechen.append(f)

    flaechen.sort(key=lambda x: natuerlich(x["nr"] or x["kennung"]))
    unbekannt = sorted({m["kurzname"] for f in flaechen for m in f["massnahmen"]
                        if m["kurzname"] and not m["nr"]
                        and "keine massnahme" not in m["kurzname"].lower()})
    if unbekannt:
        befunde.append("Maßnahmen ohne Nummer in der MAKO-Referenzliste: "
                       + "; ".join(unbekannt))
    # Wald ist ein Sonderfall: fuer Wald-MAKOs gibt es Vorgaben von Wald und
    # Holz NRW (Waldstruktur, Forsteinrichtung, Darstellung der
    # Ziel-Bestockung). Die Notloesung bildet das nicht nach - sie meldet
    # nur, welche Flaechen betroffen sind.
    wald = [f["nr"] or f["kennung"] for f in flaechen
            if f["zielgruppe"] in WALD_ZIELGRUPPEN
            or any(m["gruppe"] == "Wald" for m in f["massnahmen"])]
    if wald:
        befunde.append(
            f"{len(wald)} Maßnahmenfläche(n) mit Wald-Zielen oder "
            f"Wald-Maßnahmen ({', '.join(_kurznr(w) for w in wald[:12])}"
            f"{' …' if len(wald) > 12 else ''}). Für Wald gelten Vorgaben "
            f"von Wald und Holz NRW – Tabelle und Karte für diese Flächen "
            f"gesondert abstimmen.")
    melde(95, "Auswertung fertig.")
    return {"titel": titel or "Maßnahmenkonzept", "flaechen": flaechen,
            "srs": srs, "befunde": befunde,
            "ffh_wkb": ffh.ExportToWkb() if ffh is not None else None}


def _ist_flaeche(geom, ogr):
    return ogr.GT_Flatten(geom.GetGeometryType()) in (
        ogr.wkbPolygon, ogr.wkbMultiPolygon)


def _flaeche(z, geom, pk, gid, baum, listen, min_ha):
    """Alles, was an der Massnahmenflaeche selbst haengt."""
    fl = _zahl(z.get("FLAECHE"))
    if not fl and geom is not None:
        fl = geom.GetArea() / 10000.0 or None
    if not fl:
        # Punkt/Linie: geschaetzte Flaeche aus LINFOS2.OffFlaech
        for l2 in baum.zeilen("LINFOS2", pk, gid):
            fl = _zahl(l2.get("OffFlaech")) or fl

    # Bestand: von GISPAD beim Anlegen aus BT uebernommen
    lrt, gb, bts = {}, {}, []
    for h in baum.zeilen("BtypHtyp", pk, gid):
        flh = _zahl(h.get("Flaeche"))
        code = _t(h.get("Oekotyp"))
        btc = _t(h.get("Biotoptyp"))
        if btc and btc != "OZ":
            bts.append(btc)
        if flh is None or flh < min_ha:
            continue
        if code:
            lrt[code] = lrt.get(code, 0.0) + flh
        p62 = _t(h.get("P62_Typ"))
        if p62 and p62.lower() != KEIN_GB:
            gb[p62] = gb.get(p62, 0.0) + flh

    # Ziele der Flaeche
    ziele = baum.zeilen("Ziele", pk, gid)
    ziel_bt = [_t(r.get("Zielbiotoptyp")) for r in
               baum.zeilen("Zielbiotoptypen", pk, gid)]
    ziel_bt = _ohne_doppelte([c for c in ziel_bt if c])
    gruppe, farbe = listen.zielgruppe(ziel_bt[0]) if ziel_bt else ("", "")
    # Aeltere Verfahren (bis v2015b) fuehren Ziel-LRT / Ziel-§42 an den
    # Zielbiotoptypen statt je Massnahme - als Rueckfall mitnehmen.
    alt_lrt = [_t(r.get("Ziel_LRT")) for r in
               baum.zeilen("Zielbiotoptypen", pk, gid)]
    alt_gb = [_t(r.get("Ziel_P62")) for r in
              baum.zeilen("Zielbiotoptypen", pk, gid)]

    def zeilen_text(tab, feld):
        return _ohne_doppelte(_t(r.get(feld)) for r in baum.zeilen(tab, pk, gid))

    massnahmen = []
    for m in baum.zeilen("MASSN", pk, gid):
        kurz = _t(m.get("MASSN"))
        nr, mgruppe = listen.massnahme(kurz)
        zl = [(_t(r.get("Ziel_LRT")), r.get("ProzAnt"))
              for r in baum.unter("Massn_LRT", "MASSN", m)]
        zg = [(_t(r.get("Ziel_GB_Typ")), r.get("ProzAnt"))
              for r in baum.unter("Massn_GB", "MASSN", m)]
        if not zl and any(alt_lrt):
            zl = [(c, None) for c in alt_lrt if c]
        if not zg and any(alt_gb):
            zg = [(c, None) for c in alt_gb if c]
        tiere = _ohne_doppelte(_t(r.get("Tierart"))
                               for r in baum.unter("MassnArten", "MASSN", m))
        pflanzen = _ohne_doppelte(
            [_t(r.get("Pflanzenart")) for r in
             baum.unter("MassnArten", "MASSN", m)] +
            [_t(r.get("Massn_Pflanzenart")) for r in
             baum.unter("MassnArten_Pflanze", "MASSN", m)])
        prio = _t(m.get("Zeit_Prio"))
        prio = ZEIT_PRIO.get(prio.split(".")[0], prio) if prio else None
        massnahmen.append({
            "kurzname": kurz or "",
            "nr": nr,
            "gruppe": mgruppe,
            "zielkategorie": _t(m.get("Massnahm_Typ")),
            "zeit_prio": prio,
            "beschreibung": _t(m.get("MassnBeschreib")),
            "status": _t(m.get("Mass_Status")),
            "wichtigkeit": _t(m.get("Machbarkeit")),
            "machbarkeit_bem": _t(m.get("Machbarkeit_Bemerkung")),
            "umsetzungsfrequenz": _t(m.get("Umsetzungsfrequenz")),
            "finanzierung": _t(m.get("Finanzierung")),
            "ziel_lrt": [(c, p) for c, p in zl if c],
            "ziel_gb": [(c, p) for c, p in zg
                        if c and c.lower() != KEIN_GB],
            "zieltiere": tiere,
            "zielpflanzen": pflanzen,
        })

    return {
        "kennung": _t(z.get("KENNUNG")) or "",
        "nr": _t(z.get("OBJBEZ")) or "",
        "gispadid": gid,
        "ha": fl,
        "ausgangszustand": _t(z.get("OBJBESCHR")),
        "bestand_lrt": sorted(lrt.items(), key=lambda kv: -kv[1]),
        "bestand_gb": sorted(gb.items(), key=lambda kv: -kv[1]),
        "bestand_bt": _ohne_doppelte(bts),
        "relevante_pflanzen": zeilen_text("PlanungRelArten", "PlanRel_P_Art"),
        "relevante_tiere": zeilen_text("PlanungRelArten", "PlanRel_T_Art"),
        "entwicklungsziel": _ohne_doppelte(_t(r.get("Erlaeuterung"))
                                           for r in ziele),
        "ziel_bt_codes": ziel_bt,
        "ziel_bt": [listen.biotop(c) for c in ziel_bt],
        "zielgruppe": gruppe,
        "farbe": farbe,
        "forst": _ohne_doppelte(
            " ".join(str(r.get(k)) for k in ("Abteilung", "Unterabteilung",
                                            "Bestandseinheit")
                     if _t(r.get(k)))
            for r in baum.zeilen("ForstAdresse", pk, gid)),
        "waldstruktur": _ohne_doppelte(
            ", ".join(x for x in (_t(r.get("Waldstruktur")),
                                  (_t(r.get("Laubwaldanteil")) or "") and
                                  f"Laubwaldanteil {r.get('Laubwaldanteil')} %")
                      if x)
            for r in baum.zeilen("Waldstruktur", pk, gid)),
        "massnahmen": massnahmen,
    }


# ── GeoPackage fuer die Karte ───────────────────────────────────────────────

FLAECHEN_LAYER = "MAKO_Massnahmenflaechen"
EINZEL_LAYER = "EinzelMassn_poly"
ZIEL_LRT_LAYER = "ZIEL_LRT_polygon"
ZIEL_GB_LAYER = "ZIEL_GB_polygon"
FFH_LAYER = "FFH_Grenze"


def _lrt_kat(code):
    c = (code or "").strip()
    if not c or c.lower() == KEIN_LRT:
        return None
    return "N-LRT" if c.upper().startswith("N") else "FFH-LRT"


def schreibe_gpkg(daten, ziel, melde=_nichts):
    """
    Layer fuer die Ziel- und Massnahmenkarte schreiben.

    Feldnamen folgen dem LANUK-Konverter (mas_mako), damit die Darstellung
    sich an den Werkzeugkasten anlehnt und Ergebnisse vergleichbar bleiben.
    Rueckgabe: {layer: anzahl}.
    """
    ogr = ogr_modul()
    if os.path.exists(ziel):
        os.remove(ziel)
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(ziel)
    if ds is None:
        raise IOError(f"GeoPackage nicht anlegbar: {ziel}")
    srs = daten["srs"]

    def layer(name, felder, gtyp=ogr.wkbMultiPolygon):
        lyr = ds.CreateLayer(name, srs, gtyp)
        for fname, typ in felder:
            lyr.CreateField(ogr.FieldDefn(
                fname, {"int": ogr.OFTInteger, "real": ogr.OFTReal}.get(
                    typ, ogr.OFTString)))
        return lyr

    flaechen = [f for f in daten["flaechen"] if f["geom"] is not None
                and _ist_flaeche(f["geom"], ogr)]

    melde(96, "Schreibe Kartenlayer …")
    fl_felder = [("KENNUNG", "str"), ("OBJBEZ", "str"), ("KURZNR", "str"),
                 ("FL_HA", "real"),
                 ("ZIEL_BT", "str"), ("ZIEL_BT_C", "str"),
                 ("ZIELBIOTOP", "str"), ("FARBE", "str"),
                 ("ZIEL_LRT", "str"), ("ZIEL_GB", "str"),
                 ("MASS_NR", "str"), ("LABEL", "str"),
                 ("AUS_LRT", "str"), ("AUS_GBT", "str"),
                 ("BEEINTR", "str"), ("AUS_EHZ", "str"),
                 ("FL_FFH_IN", "real"), ("FL_FFH_AUS", "real")]
    lf = layer(FLAECHEN_LAYER, fl_felder)
    le = layer(EINZEL_LAYER, [
        ("KENNUNG", "str"), ("OBJBEZ", "str"), ("FL_HA", "real"),
        ("MASSN", "str"), ("MASS_NR", "str"), ("MASS_GRP", "str"),
        ("ZIELKAT", "str"), ("ZEIT_PRIO", "str"), ("MASSN_BEME", "str"),
        ("MASS_STATU", "str"), ("ZIEL_BT", "str"), ("ZIELBIOTOP", "str"),
        ("ZIEL_LRT", "str"), ("ZIEL_LRT_P", "str"), ("ZIEL_GB", "str"),
        ("ZIELTIER", "str"), ("ZIEL_PFL", "str"),
        ("AUS_LRT", "str"), ("AUS_GBT", "str")])
    lz = layer(ZIEL_LRT_LAYER, [
        ("KENNUNG", "str"), ("OBJBEZ", "str"), ("ZIEL_LRT", "str"),
        ("LRT_KAT", "str"), ("NEU", "int")])
    lg = layer(ZIEL_GB_LAYER, [
        ("KENNUNG", "str"), ("OBJBEZ", "str"), ("ZIEL_GB", "str"),
        ("ZIEL_GB_C", "str"), ("NEU", "int")])

    anz = {FLAECHEN_LAYER: 0, EINZEL_LAYER: 0, ZIEL_LRT_LAYER: 0,
           ZIEL_GB_LAYER: 0}
    ds.StartTransaction()
    for f in flaechen:
        aus_lrt = ", ".join(c for c, _h in f["bestand_lrt"])
        aus_gb = ", ".join(c for c, _h in f["bestand_gb"])
        nrn = _ohne_doppelte(m["nr"] or m["kurzname"] for m in f["massnahmen"])
        alle_zlrt = _ohne_doppelte(c for m in f["massnahmen"]
                                   for c, _p in m["ziel_lrt"])
        alle_zgb = _ohne_doppelte(c for m in f["massnahmen"]
                                  for c, _p in m["ziel_gb"])
        werte = {
            "KENNUNG": f["kennung"], "OBJBEZ": f["nr"],
            "KURZNR": _kurznr(f["nr"]), "FL_HA": f["ha"],
            "ZIEL_BT": f["zielgruppe"],
            "ZIEL_BT_C": ", ".join(f["ziel_bt_codes"]),
            "ZIELBIOTOP": ", ".join(f["ziel_bt"]), "FARBE": f["farbe"],
            "ZIEL_LRT": ", ".join(alle_zlrt), "ZIEL_GB": "; ".join(alle_zgb),
            "MASS_NR": ", ".join(nrn),
            "LABEL": f"{_kurznr(f['nr'])}\n{', '.join(nrn)}",
            "AUS_LRT": aus_lrt, "AUS_GBT": aus_gb,
            "BEEINTR": "; ".join(f["beeintraechtigungen"]),
            "AUS_EHZ": "; ".join(f["erhaltungszustand"]),
            "FL_FFH_IN": f["ha_innen"], "FL_FFH_AUS": f["ha_aussen"],
        }
        _neues(lf, ogr, werte, f["geom"])
        anz[FLAECHEN_LAYER] += 1
        for m in f["massnahmen"]:
            _neues(le, ogr, {
                "KENNUNG": f["kennung"], "OBJBEZ": f["nr"], "FL_HA": f["ha"],
                "MASSN": m["kurzname"], "MASS_NR": m["nr"],
                "MASS_GRP": m["gruppe"], "ZIELKAT": m["zielkategorie"],
                "ZEIT_PRIO": m["zeit_prio"], "MASSN_BEME": m["beschreibung"],
                "MASS_STATU": m["status"], "ZIEL_BT": f["zielgruppe"],
                "ZIELBIOTOP": ", ".join(f["ziel_bt"]),
                "ZIEL_LRT": ", ".join(c for c, _p in m["ziel_lrt"]),
                "ZIEL_LRT_P": ", ".join(_prozent(p) for _c, p in m["ziel_lrt"]
                                        if _prozent(p)),
                "ZIEL_GB": "; ".join(c for c, _p in m["ziel_gb"]),
                "ZIELTIER": ", ".join(m["zieltiere"]),
                "ZIEL_PFL": ", ".join(m["zielpflanzen"]),
                "AUS_LRT": aus_lrt, "AUS_GBT": aus_gb}, f["geom"])
            anz[EINZEL_LAYER] += 1
        bestand = {c for c, _h in f["bestand_lrt"]}
        for c in alle_zlrt:
            kat = _lrt_kat(c)
            if not kat:
                continue
            _neues(lz, ogr, {"KENNUNG": f["kennung"], "OBJBEZ": f["nr"],
                             "ZIEL_LRT": c, "LRT_KAT": kat,
                             "NEU": 0 if c in bestand else 1}, f["geom"])
            anz[ZIEL_LRT_LAYER] += 1
        bestand_gb = {c for c, _h in f["bestand_gb"]}
        for c in alle_zgb:
            _neues(lg, ogr, {"KENNUNG": f["kennung"], "OBJBEZ": f["nr"],
                             "ZIEL_GB": c,
                             "ZIEL_GB_C": _GB_NR.get(c, ""),
                             "NEU": 0 if c in bestand_gb else 1}, f["geom"])
            anz[ZIEL_GB_LAYER] += 1
    if daten.get("ffh_wkb"):
        lf2 = layer(FFH_LAYER, [("NAME", "str")])
        _neues(lf2, ogr, {"NAME": "FFH-Gebiet"},
               ogr.CreateGeometryFromWkb(bytes(daten["ffh_wkb"])))
        anz[FFH_LAYER] = 1
    ds.CommitTransaction()
    ds = None
    return anz


def _kurznr(objbez):
    """
    Kurze Flaechennummer fuer die Kartenbeschriftung.

    'M-002' bleibt, '44 Ackernutzung extensivieren' wird '44'. Es wird nichts
    hinzuerfunden - die Stationen vergeben die Nummern unterschiedlich.
    """
    s = (objbez or "").strip()
    m = re.match(r"^(M[-\s]?\d+[a-z]?)\b", s, re.I)
    if m:
        return m.group(1).upper().replace(" ", "-")
    m = re.match(r"^(\d+[a-z]?)\b", s)
    return m.group(1) if m else s[:12]


_GB_NR = {r["name"].strip(): r["nr"].strip()
          for r in _csv("gesetzlich_geschuetzte_biotope.csv")}


def _neues(lyr, ogr, werte, geom):
    feat = ogr.Feature(lyr.GetLayerDefn())
    for k, v in werte.items():
        if v not in (None, ""):
            feat.SetField(k, v)
    g = geom.Clone()
    if ogr.GT_Flatten(g.GetGeometryType()) == ogr.wkbPolygon:
        g = ogr.ForceToMultiPolygon(g)
    feat.SetGeometry(g)
    lyr.CreateFeature(feat)
