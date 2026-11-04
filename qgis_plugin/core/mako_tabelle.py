"""
core/mako_tabelle.py - MAKO-Massnahmentabelle als ODT und PDF.

Aufbau nach der LANUK-Eingabemaske (massnahmentabelle_eingabemaske.doc) und
dem Muster DE-4816-303 Kahler Asten:

  * je Einzelmassnahme ein Block mit vier Spalten
    Nr. Flaeche | Bestand | Entwicklungsziele | Massnahmen
  * weitere Massnahmen derselben Flaeche: Bestand "siehe oben"
  * Abschnitt 1 innerhalb, Abschnitt 2 ausserhalb des FFH-Gebietes; eine
    Flaeche, die die Grenze schneidet, steht in beiden mit ihrer Teilflaeche
  * Querformat, Fusszeile "MAKO Massnahmentabelle - <Titel> - Seite x / y"

Der HTML-Aufbau ist reines Python. Die Ausgabe nach ODT/PDF braucht Qt und
nimmt es aus QGIS (qgis.PyQt) - keine weiteren Pakete.
"""

import html

try:
    from .mako import ha, Listen, _prozent
except ImportError:                                   # eigenstaendig
    from mako import ha, Listen, _prozent            # type: ignore


def _e(s):
    return html.escape(str(s)) if s not in (None, "") else ""


def _feld(label, werte, leer=None):
    """Beschriftetes Feld; Liste = je Wert eine Zeile."""
    if isinstance(werte, (list, tuple)):
        werte = [w for w in werte if w]
        if not werte:
            if leer is None:
                return ""
            werte = [leer]
        inhalt = "<br/>".join(_e(w) for w in werte)
    else:
        if werte in (None, ""):
            if leer is None:
                return ""
            werte = leer
        inhalt = _e(werte).replace("\n", "<br/>")
    return f'<p class="f"><span class="l">{_e(label)}</span><br/>{inhalt}</p>'


def _ziel_lrt(listen, liste):
    aus = []
    for code, anteil in liste:
        t = listen.lrt_text(code)
        p = _prozent(anteil)
        aus.append(f"{t}, {p}" if p and p != "100 %" else t)
    return aus


def _ziel_gb(liste):
    aus = []
    for name, anteil in liste:
        p = _prozent(anteil)
        aus.append(f"{name}, {p}" if p and p != "100 %" else name)
    return aus


def _bestand(f, teil, listen):
    lrt, gb = f["bestand"].get(teil) or f["bestand"]["gesamt"]
    zeilen = [_feld("Ausgangszustand:", f["ausgangszustand"], leer="")]
    if f["forst"]:
        zeilen.insert(0, _feld("Forst-Kennung:", f["forst"]))
    zeilen.append(_feld("Beeinträchtigung(en):", f["beeintraechtigungen"]))
    arten = f["relevante_pflanzen"] + f["relevante_tiere"]
    zeilen.append(_feld("Maßnahmenrelevante Art(en):", arten))
    zeilen.append(_feld("Waldstruktur (Laubwaldanteil in %):",
                        f["waldstruktur"]))
    bb = f["biotopbaeume"]
    zeilen.append(_feld("Biotopbäume Anzahl:",
                        "keine Angabe" if bb is None else str(bb)))
    zeilen.append(_feld("§42-Biotop(e):",
                        [f"{listen.gb_text(n)}, {ha(h)} ha" for n, h in gb]))
    zeilen.append(_feld("Lebensraumtyp(en):",
                        [f"{listen.lrt_text(c)}, {ha(h)} ha" for c, h in lrt],
                        leer=""))
    return "".join(zeilen)


def _ziele(f, m, listen):
    z = [f'<p class="f"><b>{_e(m["zielkategorie"] or "")}</b></p>'
         if m["zielkategorie"] else ""]
    z.append(_feld("Ziel-Biotoptyp(en):", f["ziel_bt"]))
    z.append(_feld("Ziel-§42-Biotop(e) (Anteil in %):",
                   _ziel_gb(m["ziel_gb"])))
    z.append(_feld("Ziel-Lebensraumtyp(en) (Anteil in %):",
                   _ziel_lrt(listen, m["ziel_lrt"])))
    z.append(_feld("Zielart(en) Pflanzenart(en):", m["zielpflanzen"]))
    z.append(_feld("Zielart(en) Tierart(en):", m["zieltiere"]))
    z.append(_feld("Entwicklungsziele:", f["entwicklungsziel"]))
    return "".join(z)


def _massnahme(f, m, teil):
    if m["nr"]:
        kopf = f'{m["nr"]} - {m["kurzname"]}'
    else:
        kopf = m["kurzname"] or "(ohne Maßnahme)"
    z = [f'<p class="f"><b>{_e(kopf)}</b></p>']
    z.append(f'<p class="f">Fläche: {ha(f["ha"])} ha')
    if teil == "innen" and f["ha_innen"] is not None:
        z.append(f'<br/>Teilfläche innerhalb des FFH-Gebietes: '
                 f'{ha(f["ha_innen"])} ha')
    elif teil == "aussen" and f["ha_aussen"] is not None:
        z.append(f'<br/>Teilfläche außerhalb des FFH-Gebietes: '
                 f'{ha(f["ha_aussen"])} ha')
    z.append("</p>")
    besch = m["beschreibung"]
    if not besch and "keine massnahme" in (m["kurzname"] or "").lower():
        besch = "keine Maßnahmenplanung"
    if besch:
        z.append(f'<p class="f">{_e(besch).replace(chr(10), "<br/>")}</p>')
    wichtig = ", ".join(x for x in (m["wichtigkeit"], m["machbarkeit_bem"])
                        if x)
    z.append(_feld("Wichtigkeit:", wichtig))
    z.append(_feld("Umsetzungsfrequenz:", m["umsetzungsfrequenz"]))
    if m["zeit_prio"]:
        z.append(f'<p class="f">{_e(m["zeit_prio"])}</p>')
    return "".join(z)


def _block(f, m, teil, erste, listen):
    nr = (f'<p class="f"><span class="l">Nr:</span><br/>{_e(f["nr"])}</p>'
          f'<p class="f"><span class="l">Osiris-Kennung:</span><br/>'
          f'{_e(f["kennung"])}</p>')
    bestand = (_bestand(f, teil, listen) if erste else
               _feld("Ausgangszustand:", "siehe oben"))
    return (f'<tr><td class="c1">{nr}</td><td class="c2">{bestand}</td>'
            f'<td class="c3">{_ziele(f, m, listen)}</td>'
            f'<td class="c4">{_massnahme(f, m, teil)}</td></tr>')


_KOPF = ('<thead><tr><th class="c1">Nr. Fläche</th><th class="c2">Bestand</th>'
         '<th class="c3">Entwicklungsziele</th><th class="c4">Maßnahmen</th>'
         '</tr></thead>')

_STIL = """
<style>
 body { font-family: 'Arial'; font-size: 8pt; }
 h1 { font-size: 12pt; font-weight: bold; margin-bottom: 4pt; }
 h2 { font-size: 10pt; font-weight: bold; margin-top: 8pt; margin-bottom: 4pt; }
 table { border-collapse: collapse; }
 th { background-color: #d9d9d9; font-weight: bold; text-align: left;
      padding: 3px; }
 td { vertical-align: top; padding: 3px; }
 p.f { margin-top: 0px; margin-bottom: 5px; }
 span.l { font-weight: bold; }
</style>
"""


def baue_html(daten, titel=None, listen=None):
    """
    Die Tabelle als HTML. Rueckgabe: (html, anzahl_bloecke).

    Mit FFH-Grenze zwei Abschnitte (innerhalb/ausserhalb), sonst einer.
    """
    listen = listen or Listen()
    titel = titel or daten["titel"]
    flaechen = daten["flaechen"]
    mit_ffh = any(f["ha_innen"] is not None for f in flaechen)
    if mit_ffh:
        abschnitte = [
            ("1. Maßnahmenplanung innerhalb des FFH-Gebietes", "innen",
             [f for f in flaechen if f["ha_innen"]]),
            ("2. Maßnahmenplanung außerhalb des FFH-Gebietes", "aussen",
             [f for f in flaechen if f["ha_aussen"]]),
        ]
    else:
        abschnitte = [("Maßnahmenplanung", "gesamt", flaechen)]

    teile = [f"<html><head><meta charset='utf-8'/>{_STIL}</head><body>",
             f"<h1>{_e(titel)}</h1>"]
    bloecke = 0
    for i, (ueberschrift, teil, liste) in enumerate(abschnitte):
        if not liste:
            continue
        umbruch = ' style="page-break-before: always;"' if i else ""
        teile.append(f"<h2{umbruch}>{_e(ueberschrift)}</h2>")
        teile.append('<table width="100%" border="1" cellspacing="0" '
                     'cellpadding="3">'
                     '<colgroup><col width="11%"/><col width="29%"/>'
                     '<col width="24%"/><col width="36%"/></colgroup>')
        teile.append(_KOPF)
        for f in liste:
            ms = f["massnahmen"] or [{
                "kurzname": "", "nr": "", "gruppe": "", "zielkategorie": None,
                "zeit_prio": None, "beschreibung": None, "status": None,
                "wichtigkeit": None, "machbarkeit_bem": None,
                "umsetzungsfrequenz": None, "finanzierung": None,
                "ziel_lrt": [], "ziel_gb": [], "zieltiere": [],
                "zielpflanzen": []}]
            for j, m in enumerate(ms):
                teile.append(_block(f, m, teil, j == 0, listen))
                bloecke += 1
        teile.append("</table>")
    teile.append("</body></html>")
    return "".join(teile), bloecke


# ── Ausgabe (Qt) ────────────────────────────────────────────────────────────

def _qt():
    try:
        from qgis.PyQt import QtCore, QtGui
    except ImportError:                               # ohne QGIS
        from PyQt5 import QtCore, QtGui               # type: ignore
    return QtCore, QtGui


def _dokument(html_text):
    QtCore, QtGui = _qt()
    doc = QtGui.QTextDocument()
    doc.setDefaultFont(QtGui.QFont("Arial", 8))
    doc.setHtml(html_text)
    # Tabellenkopf auf jeder Seite wiederholen
    cur = QtGui.QTextCursor(doc)
    rahmen = doc.rootFrame()
    for kind in rahmen.childFrames():
        tab = kind if isinstance(kind, QtGui.QTextTable) else None
        if tab is not None:
            fmt = tab.format()
            fmt.setHeaderRowCount(1)
            fmt.setBorderStyle(QtGui.QTextFrameFormat.BorderStyle.BorderStyle_Solid)
            fmt.setBorder(0.5)
            fmt.setCellSpacing(0)
            fmt.setCellPadding(3)
            tab.setFormat(fmt)
    del cur
    return doc


_STYLES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles
 xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
 xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
 xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
 xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
 office:version="1.2">
 <office:automatic-styles>
  <style:page-layout style:name="pmQuer">
   <style:page-layout-properties fo:page-width="29.7cm" fo:page-height="21cm"
     style:print-orientation="landscape" fo:margin-top="1.2cm"
     fo:margin-bottom="0.8cm" fo:margin-left="1.2cm" fo:margin-right="1.2cm"/>
   <style:footer-style>
    <style:header-footer-properties fo:min-height="0.6cm" fo:margin-top="0.2cm"/>
   </style:footer-style>
  </style:page-layout>
  <style:style style:name="Fuss" style:family="paragraph">
   <style:paragraph-properties fo:text-align="end"/>
   <style:text-properties fo:font-size="7pt" style:font-name="Arial"/>
  </style:style>
 </office:automatic-styles>
 <office:master-styles>
  <style:master-page style:name="Standard" style:page-layout-name="pmQuer">
   <style:footer><text:p text:style-name="Fuss">{fuss} - Seite <text:page-number text:select-page="current"/> / <text:page-count/></text:p></style:footer>
  </style:master-page>
 </office:master-styles>
</office:document-styles>
"""


def _odt_ergaenzen(pfad, fusszeile):
    """
    Qt schreibt ODT ohne styles.xml - LibreOffice kommt damit zurecht,
    strengere Leser nicht, und Seitenformat und Fusszeile fehlen. Hier wird
    eine styles.xml mit A4 quer und Fusszeile samt Seitenzahl nachgereicht.
    """
    import zipfile
    import tempfile
    import shutil
    import os
    from xml.sax.saxutils import escape
    tmp = tempfile.mktemp(suffix=".odt", dir=os.path.dirname(pfad) or None)
    with zipfile.ZipFile(pfad) as alt, zipfile.ZipFile(tmp, "w") as neu:
        # mimetype muss als erstes und unkomprimiert stehen
        neu.writestr(zipfile.ZipInfo("mimetype"), alt.read("mimetype"),
                     compress_type=zipfile.ZIP_STORED)
        for name in alt.namelist():
            if name in ("mimetype", "styles.xml"):
                continue
            daten = alt.read(name)
            if name == "META-INF/manifest.xml" and b"styles.xml" not in daten:
                daten = daten.replace(
                    b"</manifest:manifest>",
                    b' <manifest:file-entry manifest:media-type="text/xml" '
                    b'manifest:full-path="styles.xml"/>\n'
                    b"</manifest:manifest>")
            neu.writestr(name, daten, compress_type=zipfile.ZIP_DEFLATED)
        neu.writestr("styles.xml",
                     _STYLES_XML.replace("{fuss}", escape(fusszeile)),
                     compress_type=zipfile.ZIP_DEFLATED)
    shutil.move(tmp, pfad)


def schreibe_odt(html_text, pfad, fusszeile=""):
    """ODT ueber QTextDocumentWriter. Rueckgabe: True bei Erfolg."""
    QtCore, QtGui = _qt()
    doc = _dokument(html_text)
    w = QtGui.QTextDocumentWriter(pfad)
    w.setFormat(b"odf")
    ok = bool(w.write(doc))
    if ok:
        _odt_ergaenzen(pfad, fusszeile)
    return ok


def schreibe_pdf(html_text, pfad, fusszeile):
    """
    PDF im Querformat A4 mit Fusszeile '<fusszeile> - Seite x / y'.

    Seitenweise gezeichnet statt QTextDocument.print_(), weil nur so eine
    eigene Fusszeile mit Gesamtseitenzahl moeglich ist.
    """
    QtCore, QtGui = _qt()
    doc = _dokument(html_text)
    writer = QtGui.QPdfWriter(pfad)
    writer.setPageSize(QtGui.QPageSize(QtGui.QPageSize.PageSizeId.A4))
    writer.setPageOrientation(QtGui.QPageLayout.Orientation.Landscape)
    writer.setPageMargins(QtCore.QMarginsF(12, 12, 12, 14),
                          QtGui.QPageLayout.Unit.Millimeter)
    writer.setResolution(300)
    writer.setTitle(fusszeile)
    writer.setCreator("BioSt-GIS – MAKO-Notlösung")

    painter = QtGui.QPainter(writer)
    try:
        seite = writer.pageLayout().paintRectPixels(writer.resolution())
        fuss_h = int(writer.resolution() * 0.25)       # ~6 mm
        inhalt = QtCore.QRectF(0, 0, seite.width(), seite.height() - fuss_h)
        # Layout in Geraeteeinheiten: Schriftgroessen in pt bleiben richtig,
        # weil das Dokument die Aufloesung des Painters uebernimmt.
        doc.documentLayout().setPaintDevice(writer)
        doc.setPageSize(inhalt.size())
        seiten = max(1, doc.pageCount())
        schrift = QtGui.QFont("Arial", 7)
        for s in range(seiten):
            if s:
                writer.newPage()
            painter.save()
            painter.translate(0, -s * inhalt.height())
            ctx = QtGui.QAbstractTextDocumentLayout.PaintContext()
            ctx.clip = QtCore.QRectF(0, s * inhalt.height(), inhalt.width(),
                                     inhalt.height())
            painter.setClipRect(ctx.clip)
            doc.documentLayout().draw(painter, ctx)
            painter.restore()
            painter.setFont(schrift)
            painter.drawText(
                QtCore.QRectF(0, seite.height() - fuss_h, seite.width(),
                              fuss_h),
                QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter,
                f"{fusszeile} - Seite {s + 1} / {seiten}")
    finally:
        painter.end()
    return True


def erzeuge(daten, odt_pfad=None, pdf_pfad=None, titel=None, listen=None):
    """HTML bauen und als ODT und/oder PDF schreiben. Rueckgabe: bloecke."""
    titel = titel or daten["titel"]
    html_text, bloecke = baue_html(daten, titel, listen)
    fuss = f"MAKO Maßnahmentabelle - {titel}"
    if odt_pfad:
        schreibe_odt(html_text, odt_pfad, fuss)
    if pdf_pfad:
        schreibe_pdf(html_text, pdf_pfad, fuss)
    return bloecke
