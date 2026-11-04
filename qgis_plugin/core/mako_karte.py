"""
core/mako_karte.py - Ziel- und Massnahmenkarte (QGIS).

Darstellung nach dem LANUK-Muster DE-4816-303 Kahler Asten und den
ArcGIS-Layerdateien des MAKO-Werkzeugkastens 2020:

  * Massnahmenflaechen farbig nach Zielbiotopgruppe (REF_Biotope-Farben)
  * Beschriftung zweizeilig: Flaechennummer schwarz, Massnahmen-Nr. rot mit
    ';' getrennt, weiss freigestellt
  * Ziel-FFH-LRT schwarz schraffiert, Ziel-§30/§42-Biotop rote Grenzlinie;
    neu angestrebte Flaechen gestrichelt (Handbuch Kap. 2.8.1.2)
  * Grenze FFH-Gebiet breit rosa
  * Legende nach Massnahmengruppen, nur mit den vorkommenden Massnahmen
  * Formate der LANUK-Vorlagen: A0, A1, 97 x 59 cm, 78 x 42 cm (quer),
    Regelmassstab 1 : 5.000

Das Layout bleibt im Projekt (Layoutverwaltung), damit Legende und Kopf von
Hand nachbearbeitet werden koennen - so sieht es auch das Handbuch vor.
"""

import datetime
import re

from qgis.core import (
    QgsCategorizedSymbolRenderer, QgsFillSymbol, QgsLayoutExporter,
    QgsLayoutItemLabel, QgsLayoutItemMap, QgsLayoutItemPicture,
    QgsLayoutItemScaleBar, QgsLayoutItemShape, QgsLayoutPoint,
    QgsLayoutSize, QgsLineSymbol, QgsLinePatternFillSymbolLayer,
    QgsPalLayerSettings, QgsPrintLayout, QgsProject, QgsRectangle,
    QgsRendererCategory, QgsRuleBasedRenderer, QgsSimpleFillSymbolLayer,
    QgsSimpleLineSymbolLayer, QgsTextBufferSettings, QgsTextFormat,
    QgsUnitTypes, QgsVectorLayer, QgsVectorLayerSimpleLabeling,
    QgsLayoutMeasurement)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QFont

try:
    from . import mako
except ImportError:                                   # eigenstaendig
    import mako                                       # type: ignore

ROT = QColor("#e00000")
FFH_FARBE = QColor("#f2a0b4")

#: Blattformate der LANUK-Vorlagen (Breite x Hoehe in mm, quer)
FORMATE = {
    "A0 (1189 × 841 mm)": (1189, 841),
    "97 × 59 cm": (970, 590),
    "A1 (841 × 594 mm)": (841, 594),
    "78 × 42 cm": (780, 420),
    "A3 (420 × 297 mm)": (420, 297),
}

#: Massstaebe, die probiert werden, wenn 1 : 5.000 nicht aufs Blatt passt
MASSSTAEBE = (5000, 7500, 10000, 12500, 15000, 20000, 25000, 50000)

#: Massnahmengruppe -> Zielbiotopgruppen, deren Farbfelder darunter stehen
GRUPPE_ZU_ZIEL = {
    "Wald": ("Laubwald", "nicht heimischer Laubwald", "Nadelwald"),
    "Kleingehölze, Hecken, Kopfbäume, Obstbäume": ("Kleingehölze",),
    "Moore, Sümpfe, Röhrichte": ("Moore, Sümpfe, Verlandungsbiotope",),
    "Heiden, Trockenrasen": ("Heiden, Trockenrasen",),
    "Grünland": ("Grünland, Brachen",),
    "Gewässer": ("Gewässer",),
    "Pionier- und Felsbiotope": ("Gesteinsbiotope, Pionierstandorte",),
    "landwirtschafliche und gärtnerische Nutzflächen": (
        "landwirtschaftl. und gärtn. Nutzflächen, Grünanlagen",),
    "Staudenfluren, Brachen, Ruderalbiotope": (
        "Staudenfluren, Brachen, Ruderalfluren, Saum- und "
        "Verlichtungsgesellschaften",),
}

#: Ueberschriften im Stil des Musters
GRUPPE_TITEL = {
    "Beeinträchtigunen und Gefährdungen":
        "Umgang mit Beeinträchtigungen und Gefährdungen",
}


# ── Stile ───────────────────────────────────────────────────────────────────

def _fuellung(farbe, rand="#505050", breite=0.2):
    return QgsFillSymbol.createSimple({
        "color": farbe, "outline_color": rand,
        "outline_width": str(breite), "outline_width_unit": "MM"})


def stil_flaechen(lyr):
    """Kategorisiert nach Zielbiotopgruppe, Farbe aus dem Feld FARBE."""
    farben = {}
    for f in lyr.getFeatures():
        g = f["ZIEL_BT"] or ""
        if g not in farben:
            farben[g] = f["FARBE"] or "#ffffff"
    kategorien = []
    for g in sorted(farben, key=lambda x: (x == "", x)):
        kategorien.append(QgsRendererCategory(
            g, _fuellung(farben[g] or "#ffffff"),
            g or "ohne Zielbiotopgruppe"))
    lyr.setRenderer(QgsCategorizedSymbolRenderer("ZIEL_BT", kategorien))

    # Beschriftung: Nummer schwarz, Massnahmen rot (HTML-Formatierung)
    pal = QgsPalLayerSettings()
    pal.isExpression = True
    # Zwei <div>-Bloecke: QGIS 3.34 bricht nur an Blockelementen um, <br>
    # und Zeilenumbrueche werden bei HTML-Formatierung zu Leerzeichen.
    pal.fieldName = ("'<div style=\"color:#000000\">' || "
                     "coalesce(\"KURZNR\", '') || '</div>"
                     "<div style=\"color:#e00000\">' || "
                     "replace(coalesce(\"MASS_NR\", ''), ', ', ';') || "
                     "'</div>'")
    fmt = QgsTextFormat()
    fmt.setFont(QFont("Arial"))
    fmt.setSize(9)
    fmt.setSizeUnit(QgsUnitTypes.RenderPoints)
    fmt.setAllowHtmlFormatting(True)
    puffer = QgsTextBufferSettings()
    puffer.setEnabled(True)
    puffer.setSize(0.8)
    puffer.setColor(QColor("white"))
    fmt.setBuffer(puffer)
    pal.setFormat(fmt)
    try:
        pal.placement = QgsPalLayerSettings.OverPoint
    except AttributeError:
        pass
    pal.multilineAlign = QgsPalLayerSettings.MultiCenter
    pal.centroidInside = True
    lyr.setLabeling(QgsVectorLayerSimpleLabeling(pal))
    lyr.setLabelsEnabled(True)


def _schraffur(gestrichelt):
    sym = QgsFillSymbol()
    sym.deleteSymbolLayer(0)
    muster = QgsLinePatternFillSymbolLayer()
    muster.setLineAngle(45)
    muster.setDistance(4.0)
    muster.setDistanceUnit(QgsUnitTypes.RenderMillimeters)
    linie = QgsLineSymbol.createSimple({
        "color": "#000000", "width": "0.35", "width_unit": "MM",
        "line_style": "dash" if gestrichelt else "solid"})
    muster.setSubSymbol(linie)
    sym.appendSymbolLayer(muster)
    rand = QgsSimpleLineSymbolLayer(QColor("#000000"), 0.35)
    rand.setPenStyle(Qt.PenStyle.DashLine if gestrichelt else Qt.PenStyle.SolidLine)
    # Rand als Linie ueber eine einfache Fuellung ohne Flaeche
    fill = QgsSimpleFillSymbolLayer()
    fill.setBrushStyle(Qt.BrushStyle.NoBrush)
    fill.setStrokeColor(QColor("#000000"))
    fill.setStrokeWidth(0.35)
    fill.setStrokeStyle(Qt.PenStyle.DashLine if gestrichelt else Qt.PenStyle.SolidLine)
    sym.appendSymbolLayer(fill)
    return sym


def stil_ziel_lrt(lyr):
    """FFH-LRT schraffiert; N-LRT werden nicht dargestellt (wie LYR)."""
    wurzel = QgsRuleBasedRenderer.Rule(None)
    for neu, titel in ((0, "FFH-Lebensraumtyp"),
                       (1, "FFH-Lebensraumtyp (Entwicklung)")):
        r = QgsRuleBasedRenderer.Rule(
            _schraffur(bool(neu)),
            filterExp=f"\"LRT_KAT\" = 'FFH-LRT' AND \"NEU\" = {neu}",
            label=titel)
        wurzel.appendChild(r)
    lyr.setRenderer(QgsRuleBasedRenderer(wurzel))


def _grenze(farbe, breite, gestrichelt=False):
    sym = QgsFillSymbol()
    sym.deleteSymbolLayer(0)
    fill = QgsSimpleFillSymbolLayer()
    fill.setBrushStyle(Qt.BrushStyle.NoBrush)
    fill.setStrokeColor(farbe)
    fill.setStrokeWidth(breite)
    fill.setStrokeStyle(Qt.PenStyle.DashLine if gestrichelt else Qt.PenStyle.SolidLine)
    sym.appendSymbolLayer(fill)
    return sym


def stil_ziel_gb(lyr):
    wurzel = QgsRuleBasedRenderer.Rule(None)
    for neu, titel in ((0, "§ 30/§ 42-Biotop"),
                       (1, "§ 30/§ 42-Biotop (Entwicklung)")):
        wurzel.appendChild(QgsRuleBasedRenderer.Rule(
            _grenze(ROT, 0.7, bool(neu)), filterExp=f"\"NEU\" = {neu}",
            label=titel))
    lyr.setRenderer(QgsRuleBasedRenderer(wurzel))


def stil_ffh(lyr):
    from qgis.core import QgsSingleSymbolRenderer
    lyr.setRenderer(QgsSingleSymbolRenderer(_grenze(FFH_FARBE, 2.0)))


def stil_einzel(lyr):
    """Einzelmassnahmen: nur Umriss, standardmaessig ausgeblendet."""
    from qgis.core import QgsSingleSymbolRenderer
    lyr.setRenderer(QgsSingleSymbolRenderer(_grenze(QColor("#505050"), 0.2)))


STILE = {
    mako.FLAECHEN_LAYER: ("Maßnahmenflächen (Zielbiotopgruppe)",
                          stil_flaechen),
    mako.ZIEL_LRT_LAYER: ("Ziel-FFH-Lebensraumtyp", stil_ziel_lrt),
    mako.ZIEL_GB_LAYER: ("Ziel-§ 30/§ 42-Biotop", stil_ziel_gb),
    mako.FFH_LAYER: ("Grenze FFH-Gebiet", stil_ffh),
    mako.EINZEL_LAYER: ("Einzelmaßnahmen (Tabelle)", stil_einzel),
}


def lade(gpkg, projekt=None, gruppe="MAKO Ziel- und Maßnahmenkarte",
         speichere_stil=True):
    """
    Die MAKO-Layer aus dem GeoPackage laden, stylen und gruppieren.
    Rueckgabe: {layername: QgsVectorLayer}.
    """
    projekt = projekt or QgsProject.instance()
    wurzel = projekt.layerTreeRoot()
    alt = wurzel.findGroup(gruppe)
    if alt is not None:
        for lyr_id in [k.layerId() for k in alt.findLayers()]:
            projekt.removeMapLayer(lyr_id)
        wurzel.removeChildNode(alt)
    knoten = wurzel.insertGroup(0, gruppe)
    aus = {}
    # Reihenfolge von oben nach unten
    for name in (mako.FFH_LAYER, mako.ZIEL_GB_LAYER, mako.ZIEL_LRT_LAYER,
                 mako.FLAECHEN_LAYER, mako.EINZEL_LAYER):
        lyr = QgsVectorLayer(f"{gpkg}|layername={name}", name, "ogr")
        if not lyr.isValid() or lyr.featureCount() == 0:
            continue
        titel, stil = STILE[name]
        lyr.setName(titel)
        stil(lyr)
        if speichere_stil:
            try:
                lyr.saveStyleToDatabase("MAKO", "BioSt-GIS MAKO-Notlösung",
                                        True, "")
            except Exception:                        # noqa: BLE001
                pass
        projekt.addMapLayer(lyr, False)
        k = knoten.addLayer(lyr)
        if name == mako.EINZEL_LAYER:
            k.setItemVisibilityChecked(False)
        aus[name] = lyr
    return aus


# ── Legende ─────────────────────────────────────────────────────────────────

def _nr_schluessel(nr):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", nr or "")]


def legende(daten):
    """
    Legendeninhalt: Liste von (gruppe, [(zielgruppe, farbe)],
    [(nr, kurzname)]), sortiert nach Massnahmennummer.
    """
    ziel_da = {}
    for f in daten["flaechen"]:
        if f["zielgruppe"]:
            ziel_da[f["zielgruppe"]] = f["farbe"]
    gruppen = {}
    for f in daten["flaechen"]:
        for m in f["massnahmen"]:
            g = m["gruppe"] or ("keine Massnahme nötig"
                                if "keine massnahme" in m["kurzname"].lower()
                                else "sonstige Maßnahmen")
            gruppen.setdefault(g, {})[m["nr"] or m["kurzname"]] = m["kurzname"]
    # Zielgruppen ohne Massnahme ihrer Gruppe trotzdem zeigen
    verwendet = set()
    for g, zs in GRUPPE_ZU_ZIEL.items():
        if any(z in ziel_da for z in zs):
            gruppen.setdefault(g, {})

    def ordnung(g):
        """(Rang, Hauptnummer, Name) - Wald (1.x) vor Grünland (5.x)."""
        nrn = [n for n in gruppen[g] if re.match(r"^\d", n)]
        if nrn:
            return (0, int(re.match(r"^(\d+)", nrn[0]).group(1)), g)
        for i, kname in enumerate(GRUPPE_ZU_ZIEL):
            if kname == g:
                return (0, i + 1, g)
        return (1 if g != "keine Massnahme nötig" else 2, 0, g)

    aus = []
    for g in sorted(gruppen, key=ordnung):
        felder = [(z, ziel_da[z]) for z in GRUPPE_ZU_ZIEL.get(g, ())
                  if z in ziel_da]
        verwendet.update(z for z, _f in felder)
        ms = sorted(gruppen[g].items(), key=lambda kv: _nr_schluessel(kv[0]))
        ms = [(n if re.match(r"^\d", n) else "", k) for n, k in ms]
        aus.append((GRUPPE_TITEL.get(g, g), felder, ms))
    rest = [(z, c) for z, c in ziel_da.items() if z not in verwendet]
    if rest:
        aus.append(("weitere Zielbiotopgruppen", rest, []))
    return aus


# ── Layout ──────────────────────────────────────────────────────────────────

def _label(layout, text, x, y, b, h, groesse=8, fett=False, farbe=None,
           ausrichtung=Qt.AlignmentFlag.AlignLeft):
    lab = QgsLayoutItemLabel(layout)
    lab.setText(text)
    font = QFont("Arial")
    font.setBold(fett)
    fmt = QgsTextFormat()
    fmt.setFont(font)
    fmt.setSize(groesse)
    fmt.setSizeUnit(QgsUnitTypes.RenderPoints)
    if farbe is not None:
        fmt.setColor(farbe)
    try:
        lab.setTextFormat(fmt)
    except AttributeError:                            # QGIS < 3.24
        lab.setFont(font)
        if farbe is not None:
            lab.setFontColor(farbe)
    lab.setHAlign(ausrichtung)
    lab.setVAlign(Qt.AlignmentFlag.AlignTop)
    lab.setMarginX(0)
    lab.setMarginY(0)
    layout.addLayoutItem(lab)
    lab.attemptMove(QgsLayoutPoint(x, y, QgsUnitTypes.LayoutMillimeters))
    lab.attemptResize(QgsLayoutSize(b, h, QgsUnitTypes.LayoutMillimeters))
    return lab


def _kasten(layout, x, y, b, h, fuellung=None, rand="#000000", breite=0.2,
            symbol=None):
    k = QgsLayoutItemShape(layout)
    k.setShapeType(QgsLayoutItemShape.Rectangle)
    if symbol is None:
        symbol = QgsFillSymbol.createSimple({
            "color": fuellung or "255,255,255,0",
            "style": "solid" if fuellung else "no",
            "outline_color": rand, "outline_width": str(breite),
            "outline_width_unit": "MM"})
    k.setSymbol(symbol)
    layout.addLayoutItem(k)
    k.attemptMove(QgsLayoutPoint(x, y, QgsUnitTypes.LayoutMillimeters))
    k.attemptResize(QgsLayoutSize(b, h, QgsUnitTypes.LayoutMillimeters))
    return k


def _zeilen(text, breite_mm, groesse_pt, fett=False):
    """Grobe Schaetzung, in wie viele Zeilen ein Text umbricht (Arial)."""
    zeichen_mm = groesse_pt * 0.3528 * (0.56 if fett else 0.52)
    pro_zeile = max(1, int(breite_mm / zeichen_mm))
    import math
    return max(1, math.ceil(len(text or "") / pro_zeile))


def _massstab_passend(ausdehnung, b_mm, h_mm, wunsch=5000):
    for m in [wunsch] + [x for x in MASSSTAEBE if x > wunsch]:
        if (ausdehnung.width() * 1000 / m <= b_mm and
                ausdehnung.height() * 1000 / m <= h_mm):
            return m
    return MASSSTAEBE[-1]


def baue_layout(daten, layer, titel, kartentitel="Ziel- und Maßnahmenkarte",
                format_name="A0 (1189 × 841 mm)", massstab=5000,
                bearbeitung="", projekt=None, name=None):
    """
    Drucklayout anlegen (ersetzt ein gleichnamiges). Rueckgabe:
    (layout, massstab, befunde).
    """
    projekt = projekt or QgsProject.instance()
    befunde = []
    seite_b, seite_h = FORMATE.get(format_name, FORMATE["A0 (1189 × 841 mm)"])
    k = seite_b / 1189.0                                # Skalierung zu A0
    rand = max(8.0, 12 * k)
    spalte = max(110.0, 170 * k)                        # Legendenspalte
    name = name or f"MAKO {kartentitel}"

    mgr = projekt.layoutManager()
    alt = mgr.layoutByName(name)
    if alt is not None:
        mgr.removeLayout(alt)
    layout = QgsPrintLayout(projekt)
    layout.initializeDefaults()
    layout.setName(name)
    seite = layout.pageCollection().page(0)
    seite.setPageSize(QgsLayoutSize(seite_b, seite_h,
                                    QgsUnitTypes.LayoutMillimeters))

    # Kartenfenster
    karte_b = seite_b - 2 * rand - spalte - rand / 2
    karte_h = seite_h - 2 * rand
    karte = QgsLayoutItemMap(layout)
    karte.attemptMove(QgsLayoutPoint(rand, rand,
                                     QgsUnitTypes.LayoutMillimeters))
    karte.attemptResize(QgsLayoutSize(karte_b, karte_h,
                                      QgsUnitTypes.LayoutMillimeters))
    karte.setFrameEnabled(True)
    karte.setFrameStrokeWidth(QgsLayoutMeasurement(
        0.5, QgsUnitTypes.LayoutMillimeters))
    layout.addLayoutItem(karte)

    flaechen = layer.get(mako.FLAECHEN_LAYER)
    ausdehnung = QgsRectangle(flaechen.extent()) if flaechen else \
        QgsRectangle()
    if mako.FFH_LAYER in layer:
        ausdehnung.combineExtentWith(layer[mako.FFH_LAYER].extent())
    ausdehnung.scale(1.04)
    m = _massstab_passend(ausdehnung, karte_b, karte_h, massstab)
    if m != massstab:
        befunde.append(
            f"Das Gebiet passt bei 1 : {massstab:,} nicht auf das Blatt "
            f"{format_name}; die Karte ist im Maßstab 1 : {m:,} angelegt. "
            f"Größeres Blatt wählen oder im Layout einen Atlas einrichten."
            .replace(",", "."))
    # Erst das Koordinatensystem, dann Ausschnitt und Massstab - sonst
    # deutet die Karte die Ausdehnung im Projekt-KBS.
    karte.setCrs(flaechen.crs() if flaechen else projekt.crs())
    karte.zoomToExtent(ausdehnung)
    karte.setScale(m)

    # Legendenspalte
    x0 = rand + karte_b + rand / 2
    _kasten(layout, x0, rand, spalte, karte_h, rand="#000000", breite=0.5)
    pad = 4 * max(k, 0.6)
    x, y = x0 + pad, rand + pad
    sb = spalte - 2 * pad
    gross = max(8.0, 18 * k)
    mittel = max(7.0, 13 * k)
    klein = max(6.0, 10 * k)
    zeile = klein * 0.42 + 0.8

    _label(layout, "Maßnahmen zur Erhaltung, Verbesserung, Neuanlage/ "
           "Wiederherstellung von wertbestimmenden Lebensräumen und Habitaten",
           x, y, sb, gross * 1.6, groesse=gross, fett=True)
    y += gross * 1.7
    feld_b, feld_h = 12 * max(k, 0.6), 6 * max(k, 0.6)
    for gruppe, felder, ms in legende(daten):
        zh = mittel * 0.3528 * 1.25                    # Zeilenhoehe in mm
        n = _zeilen(gruppe, sb, mittel, True)
        _label(layout, gruppe, x, y, sb, n * zh + 1, groesse=mittel,
               fett=True)
        y += n * zh + 1.5
        for z, farbe in felder:
            n = _zeilen(z, sb - feld_b - 3, mittel, True)
            h = max(feld_h, n * zh)
            _kasten(layout, x, y, feld_b, feld_h, fuellung=farbe)
            _label(layout, z, x + feld_b + 3, y + 0.3, sb - feld_b - 3,
                   h + 1, groesse=mittel, fett=True)
            y += h + 1.5
        if ms:
            y += 1
        nr_b = 15 * max(k, 0.6)
        for nr, kurz in ms:
            n = _zeilen(kurz, sb - nr_b, klein)
            _label(layout, nr, x, y, nr_b - 1, zeile, groesse=klein,
                   fett=True, farbe=ROT)
            _label(layout, kurz, x + nr_b, y, sb - nr_b, n * zeile + 0.5,
                   groesse=klein)
            y += n * zeile
        y += mittel * 0.45

    # Nachrichtliche Darstellung (unten in der Spalte)
    eintraege = []
    if mako.FFH_LAYER in layer:
        eintraege.append((_grenze(FFH_FARBE, 2.0), "Grenze FFH-Gebiet"))
    if mako.ZIEL_GB_LAYER in layer:
        eintraege.append((_grenze(ROT, 0.7), "§ 30/§ 42-Biotop"))
        eintraege.append((_grenze(ROT, 0.7, True),
                          "§ 30/§ 42-Biotop (Entwicklung)"))
    if mako.ZIEL_LRT_LAYER in layer:
        eintraege.append((_schraffur(False), "FFH-Lebensraumtyp"))
        eintraege.append((_schraffur(True), "FFH-Lebensraumtyp (Entwicklung)"))
    kopf_h = 70 * max(k, 0.55)
    yu = rand + karte_h - kopf_h - pad - len(eintraege) * (feld_h + 2.5)
    if yu < y + 5:
        befunde.append("Die Legende ist für das Blattformat zu lang und "
                       "überlappt – im Layout von Hand kürzen oder ein "
                       "größeres Blatt wählen.")
    for sym, text in eintraege:
        _kasten(layout, x, yu, feld_b * 1.6, feld_h, symbol=sym.clone())
        _label(layout, text, x + feld_b * 1.6 + 3, yu + 0.5, sb, feld_h,
               groesse=mittel)
        yu += feld_h + 2.5

    # Kartenkopf
    yk = rand + karte_h - kopf_h
    _kasten(layout, x0, yk, spalte, kopf_h, rand="#000000", breite=0.5)
    _label(layout, titel, x0 + pad, yk + pad, sb, kopf_h * 0.36,
           groesse=mittel, fett=True, ausrichtung=Qt.AlignmentFlag.AlignHCenter)
    _label(layout, kartentitel, x0 + pad, yk + kopf_h * 0.40, sb,
           mittel * 0.6, groesse=gross, fett=True,
           ausrichtung=Qt.AlignmentFlag.AlignHCenter)
    info = (f"Maßstab 1 : {m:,}".replace(",", ".") +
            f"\nStand: {datetime.date.today():%d.%m.%Y}")
    if bearbeitung:
        info += f"\nBearbeitung: {bearbeitung}"
    info += ("\nErstellt mit BioSt-GIS (Notlösung für den "
             "MAKO-Konverter des LANUK)")
    _label(layout, info, x0 + pad, yk + kopf_h * 0.58, sb, kopf_h * 0.4,
           groesse=klein, ausrichtung=Qt.AlignmentFlag.AlignHCenter)

    # Massstabsleiste und Nordpfeil im Kartenfenster unten links
    leiste = QgsLayoutItemScaleBar(layout)
    leiste.setStyle("Single Box")
    leiste.setLinkedMap(karte)
    leiste.setUnits(QgsUnitTypes.DistanceMeters)
    leiste.setUnitLabel("m")
    leiste.setNumberOfSegments(4)
    leiste.setNumberOfSegmentsLeft(0)
    leiste.setUnitsPerSegment(100 if m <= 7500 else 250 if m <= 15000
                              else 500)
    leiste.setHeight(2 * max(k, 0.6))
    fmt = QgsTextFormat()
    fmt.setFont(QFont("Arial"))
    fmt.setSize(klein)
    try:
        leiste.setTextFormat(fmt)
    except AttributeError:
        pass
    leiste.setBackgroundEnabled(True)
    layout.addLayoutItem(leiste)
    leiste.attemptMove(QgsLayoutPoint(rand + 5, rand + karte_h - 18 * max(
        k, 0.6), QgsUnitTypes.LayoutMillimeters))

    pfeil = QgsLayoutItemPicture(layout)
    pfeil.setPicturePath(":/images/north_arrows/layout_default_north_arrow.svg")
    pfeil.setLinkedMap(karte)
    pfeil.setNorthMode(QgsLayoutItemPicture.GridNorth)
    layout.addLayoutItem(pfeil)
    groesse = 18 * max(k, 0.6)
    pfeil.attemptMove(QgsLayoutPoint(rand + karte_b - groesse - 5, rand + 5,
                                     QgsUnitTypes.LayoutMillimeters))
    pfeil.attemptResize(QgsLayoutSize(groesse, groesse,
                                      QgsUnitTypes.LayoutMillimeters))

    mgr.addLayout(layout)
    return layout, m, befunde


def exportiere_pdf(layout, pfad, dpi=200):
    exp = QgsLayoutExporter(layout)
    ein = QgsLayoutExporter.PdfExportSettings()
    ein.dpi = dpi
    ein.rasterizeWholeImage = False
    ergebnis = exp.exportToPdf(pfad, ein)
    return ergebnis == QgsLayoutExporter.Success


def exportiere_png(layout, pfad, dpi=40):
    """Vorschaubild (fuer Tests und Kontrolle)."""
    exp = QgsLayoutExporter(layout)
    ein = QgsLayoutExporter.ImageExportSettings()
    ein.dpi = dpi
    return exp.exportToImage(pfad, ein) == QgsLayoutExporter.Success
