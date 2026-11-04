"""
mako_dialog.py - MAKO-Produkte aus einem GISPAD-Export (Notloesung)

Der MAKO-Konverter des LANUK ist ausser Betrieb. Dieser Dialog erzeugt aus
einem GISPAD-Export mit Massnahmenflaechen (MAS):

  * die Massnahmentabelle als ODT und PDF (Layout der LANUK-Eingabemaske)
  * die Ziel- und Massnahmenkarte als Drucklayout im Projekt und als PDF
  * ein GeoPackage mit den Kartenlayern (Feldnamen wie der LANUK-Konverter)

Fuer die Aufteilung "innerhalb / ausserhalb des FFH-Gebietes" wird die
FFH-Grenze aus einem Layer des Projekts genommen - im GISPAD-Export ist sie
in der Regel nicht enthalten. Ohne sie entsteht eine Tabelle ohne
Aufteilung.
"""
import os

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGroupBox,
    QLineEdit, QComboBox, QProgressBar, QTextEdit, QCheckBox, QFileDialog,
    QMessageBox, QDialogButtonBox, QFormLayout,
)
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsWkbTypes, QgsCoordinateReferenceSystem,
    QgsCoordinateTransform, QgsFeatureRequest, QgsRectangle, QgsGeometry,
)

try:
    from qgis_new_project_plugin.core.gispad import raeume_auf
    from qgis_new_project_plugin.workers.gispad_worker import GispadWorker
except ImportError:
    from .core.gispad import raeume_auf
    from .workers.gispad_worker import GispadWorker


def _dateiname(titel):
    """'... (DE-4816-303)' -> 'DE-4816-303'; sonst ein kurzer ASCII-Name."""
    import re
    m = re.search(r"DE[-\s]?\d{4}[-\s]?\d{3}", titel or "")
    if m:
        return m.group(0).replace(" ", "-")
    ersatz = {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe",
              "Ü": "Ue", "ß": "ss"}
    t = "".join(ersatz.get(c, c) for c in (titel or ""))
    t = re.sub(r"[^A-Za-z0-9-]+", "_", t).strip("_")
    return t[:40].rstrip("_") or "MAKO"


class MakoDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MAKO-Produkte aus GISPAD-Export (Notlösung)")
        self.resize(760, 680)
        self._worker = None
        self._temp = None
        self._quelle = ""
        self._gdb = None
        self._daten = None
        self._build_ui()
        self._fuelle_ffh()

    # ── Oberfläche ──────────────────────────────────────────────────────────
    def _build_ui(self):
        lo = QVBoxLayout(self)
        hinweis = QLabel(
            "Erzeugt Maßnahmentabelle und Ziel- und Maßnahmenkarte aus einem "
            "GISPAD-Export mit Maßnahmenflächen (MAS) – als Ersatz für den "
            "derzeit nicht verfügbaren MAKO-Konverter des LANUK.\n"
            "Der Export sollte MAS und BT enthalten, für die "
            "Biotopbaum-Anzahl auch BAUM.")
        hinweis.setWordWrap(True)
        hinweis.setStyleSheet("color: #444;")
        lo.addWidget(hinweis)

        box1 = QGroupBox("1. GISPAD-Export wählen")
        l1 = QVBoxLayout(box1)
        z = QHBoxLayout()
        self.pfad_edit = QLineEdit()
        self.pfad_edit.setReadOnly(True)
        self.pfad_edit.setPlaceholderText("Ordner des Exports oder ZIP-Archiv")
        self.btn_ordner = QPushButton("Ordner …")
        self.btn_ordner.clicked.connect(self._waehle_ordner)
        self.btn_zip = QPushButton("ZIP-Datei …")
        self.btn_zip.clicked.connect(self._waehle_archiv)
        z.addWidget(self.pfad_edit, 1)
        z.addWidget(self.btn_ordner)
        z.addWidget(self.btn_zip)
        l1.addLayout(z)
        self.befund_label = QLabel("Noch kein Export gewählt.")
        self.befund_label.setWordWrap(True)
        self.befund_label.setStyleSheet("color: #666;")
        l1.addWidget(self.befund_label)
        lo.addWidget(box1)

        box2 = QGroupBox("2. Angaben")
        f2 = QFormLayout(box2)
        self.ffh_combo = QComboBox()
        self.ffh_combo.setToolTip(
            "Polygonlayer mit der FFH-Gebietsgrenze, z. B. über "
            "„NRW Grundlagendaten abrufen“ geladen. Es werden nur die "
            "Flächen verwendet, die die Maßnahmenflächen berühren.")
        btn_neu = QPushButton("↻")
        btn_neu.setFixedWidth(30)
        btn_neu.setToolTip("Layerliste neu einlesen")
        btn_neu.clicked.connect(self._fuelle_ffh)
        zf = QHBoxLayout()
        zf.addWidget(self.ffh_combo, 1)
        zf.addWidget(btn_neu)
        f2.addRow("FFH-Gebietsgrenze:", zf)
        self.titel_edit = QLineEdit()
        self.titel_edit.setPlaceholderText(
            "z. B. Maßnahmenkonzept FFH-Gebiet Kahler Asten (DE-4816-303)")
        f2.addRow("Titel:", self.titel_edit)
        self.bearb_edit = QLineEdit()
        self.bearb_edit.setPlaceholderText("z. B. Biologische Station …")
        f2.addRow("Bearbeitung:", self.bearb_edit)
        self.format_combo = QComboBox()
        try:
            from .core.mako_karte import FORMATE
        except ImportError:
            from qgis_new_project_plugin.core.mako_karte import FORMATE
        self.format_combo.addItems(list(FORMATE))
        f2.addRow("Blattformat der Karte:", self.format_combo)
        lo.addWidget(box2)

        box3 = QGroupBox("3. Ausgabe")
        l3 = QVBoxLayout(box3)
        z3 = QHBoxLayout()
        self.ziel_edit = QLineEdit()
        self.ziel_edit.setPlaceholderText("Ordner für die Ergebnisse")
        b3 = QPushButton("…")
        b3.setFixedWidth(34)
        b3.clicked.connect(self._waehle_ziel)
        z3.addWidget(self.ziel_edit, 1)
        z3.addWidget(b3)
        l3.addLayout(z3)
        self.cb_tabelle = QCheckBox("Maßnahmentabelle (ODT und PDF)")
        self.cb_tabelle.setChecked(True)
        self.cb_karte = QCheckBox(
            "Ziel- und Maßnahmenkarte (Layer laden, Drucklayout, PDF)")
        self.cb_karte.setChecked(True)
        l3.addWidget(self.cb_tabelle)
        l3.addWidget(self.cb_karte)
        lo.addWidget(box3)

        self.start_btn = QPushButton("Erzeugen")
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self._starte)
        lo.addWidget(self.start_btn)
        self.balken = QProgressBar()
        self.balken.setVisible(False)
        lo.addWidget(self.balken)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet("font-family: monospace; font-size: 11px;")
        lo.addWidget(self.log, 1)
        kn = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        kn.rejected.connect(self.reject)
        lo.addWidget(kn)

    def _sage(self, text):
        self.log.append(text)
        self.log.ensureCursorVisible()

    def _fuelle_ffh(self):
        aktuell = self.ffh_combo.currentData()
        self.ffh_combo.clear()
        self.ffh_combo.addItem("– keine (Tabelle ohne Aufteilung) –", None)
        vorschlag = 0
        for lyr in QgsProject.instance().mapLayers().values():
            if (isinstance(lyr, QgsVectorLayer) and lyr.geometryType() ==
                    QgsWkbTypes.PolygonGeometry):
                self.ffh_combo.addItem(lyr.name(), lyr.id())
                if "ffh" in lyr.name().lower() and not vorschlag:
                    vorschlag = self.ffh_combo.count() - 1
                if lyr.id() == aktuell:
                    vorschlag = self.ffh_combo.count() - 1
        self.ffh_combo.setCurrentIndex(vorschlag)

    # ── Export wählen ───────────────────────────────────────────────────────
    def _waehle_ordner(self):
        p = QFileDialog.getExistingDirectory(self, "GISPAD-Export wählen",
                                             self._quelle or "")
        if p:
            self._erschliesse(p)

    def _waehle_archiv(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "Gepackten GISPAD-Export wählen", self._quelle or "",
            "Gepackte Exporte (*.zip *.gdb *.gdb.zip);;Alle Dateien (*)")
        if p:
            self._erschliesse(p)

    def _waehle_ziel(self):
        p = QFileDialog.getExistingDirectory(self, "Ausgabeordner wählen",
                                             self.ziel_edit.text() or "")
        if p:
            self.ziel_edit.setText(p)

    def _erschliesse(self, pfad):
        self._raeume_temp_auf()
        self._quelle = pfad
        self._gdb = None
        self.pfad_edit.setText(pfad)
        self.befund_label.setText("Sehe nach, was darin liegt …")
        self.start_btn.setEnabled(False)
        self.log.clear()
        self._starte_worker("erschliessen", {"quelle": pfad})

    def _nach_erschliessen(self, ergebnis):
        gdbs = ergebnis["gdbs"]
        self._temp = ergebnis["temp"]
        if not gdbs:
            self.befund_label.setText(
                "Keine File-Geodatabase gefunden. 7z-Archive bitte vorher "
                "auspacken oder als ZIP packen.")
            return
        gdb = gdbs[0]
        if len(gdbs) > 1:
            from qgis.PyQt.QtWidgets import QInputDialog
            namen = [os.path.basename(t) for t in gdbs]
            name, ok = QInputDialog.getItem(
                self, "Geodatabase wählen", "Mehrere Geodatabases gefunden:",
                namen, 0, False)
            if not ok:
                return
            gdb = gdbs[namen.index(name)]
        self._gdb = gdb
        self.pfad_edit.setText(gdb)
        self._sichte(gdb)

    def _sichte(self, gdb):
        """Schnell nachsehen, ob MAS, BT und BAUM drin sind; Titel holen."""
        try:
            from osgeo import ogr
            ds = ogr.Open(gdb)
            anz = {}
            for n in ("MAS_Polygon", "MAS_Point", "MAS_Polyline",
                      "BT_Polygon", "BAUM_Point"):
                lyr = ds.GetLayerByName(n)
                anz[n] = lyr.GetFeatureCount() if lyr else 0
            mas = anz["MAS_Polygon"] + anz["MAS_Point"] + anz["MAS_Polyline"]
            teile = [f"{mas} Maßnahmenflächen (MAS)",
                     f"{anz['BT_Polygon']} Biotoptypen (BT)",
                     f"{anz['BAUM_Point']} Biotopbäume (BAUM)"]
            self.befund_label.setText("Gefunden: " + ", ".join(teile))
            if not mas:
                self.befund_label.setText(
                    "Der Export enthält keine Maßnahmenflächen (MAS).")
                return
            lyr = ds.GetLayerByName("MAS_Polygon") or ds.GetLayerByName(
                "MAS_Point")
            self._export_srs = lyr.GetSpatialRef().ExportToWkt() \
                if lyr and lyr.GetSpatialRef() else None
            if not self.titel_edit.text() and lyr:
                lyr.ResetReading()
                for f in lyr:
                    i = f.GetFieldIndex("AUFHINWVON")
                    if i >= 0 and f.GetField(i):
                        self.titel_edit.setText(str(f.GetField(i)).strip())
                        break
            if not self.ziel_edit.text():
                basis = gdb[:-4] if gdb.lower().endswith(".gdb") else gdb
                quelle = self._quelle if not self._temp else os.path.dirname(
                    self._quelle)
                self.ziel_edit.setText(os.path.join(
                    os.path.dirname(quelle) if not self._temp else quelle,
                    os.path.basename(basis) + "_MAKO"))
            self.start_btn.setEnabled(True)
        except Exception as e:                       # noqa: BLE001
            self.befund_label.setText(f"Export nicht lesbar: {e}")

    # ── FFH-Grenze ──────────────────────────────────────────────────────────
    def _ffh_wkbs(self):
        lyr_id = self.ffh_combo.currentData()
        if not lyr_id:
            return None
        lyr = QgsProject.instance().mapLayer(lyr_id)
        if lyr is None:
            return None
        ziel = QgsCoordinateReferenceSystem()
        if getattr(self, "_export_srs", None):
            ziel = QgsCoordinateReferenceSystem.fromWkt(self._export_srs)
        if not ziel.isValid():
            ziel = QgsCoordinateReferenceSystem("EPSG:25832")
        tr = QgsCoordinateTransform(lyr.crs(), ziel, QgsProject.instance())
        # Nur Flaechen in der Naehe der Massnahmenflaechen
        from osgeo import ogr
        ds = ogr.Open(self._gdb)
        x1 = y1 = float("inf")
        x2 = y2 = float("-inf")
        for n in ("MAS_Polygon", "MAS_Point", "MAS_Polyline"):
            l = ds.GetLayerByName(n)
            if l and l.GetFeatureCount():
                a, b, c, d = l.GetExtent()
                x1, x2, y1, y2 = min(x1, a), max(x2, b), min(y1, c), max(y2, d)
        bbox = QgsRectangle(x1, y1, x2, y2)
        bbox_lyr = tr.transformBoundingBox(
            bbox, QgsCoordinateTransform.ReverseTransform)
        wkbs = []
        for f in lyr.getFeatures(QgsFeatureRequest().setFilterRect(bbox_lyr)):
            g = QgsGeometry(f.geometry())
            if g.isEmpty():
                continue
            g.transform(tr)
            wkbs.append(bytes(g.asWkb()))
        return wkbs or None

    # ── Ablauf ──────────────────────────────────────────────────────────────
    def _starte(self):
        ziel = self.ziel_edit.text().strip()
        if not ziel:
            QMessageBox.warning(self, "Ausgabe", "Bitte einen Ausgabeordner "
                                "wählen.")
            return
        os.makedirs(ziel, exist_ok=True)
        self._ausgabe = ziel
        try:
            ffh = self._ffh_wkbs()
        except Exception as e:                       # noqa: BLE001
            self._sage(f"FFH-Grenze nicht lesbar ({e}) – ohne Aufteilung.")
            ffh = None
        if self.ffh_combo.currentData() and not ffh:
            self._sage("Hinweis: Der gewählte FFH-Layer berührt die "
                       "Maßnahmenflächen nicht – Tabelle ohne Aufteilung.")
        gpkg = os.path.join(ziel, "MAKO_Kartenlayer.gpkg")
        self._gpkg = gpkg
        self._sage("Werte den Export aus …")
        self._starte_worker("mako", {"gdb": self._gdb, "ziel": gpkg,
                                     "ffh": ffh})

    def _starte_worker(self, auftrag, config):
        self.balken.setVisible(True)
        self.balken.setValue(0)
        self.start_btn.setEnabled(False)
        self.btn_ordner.setEnabled(False)
        self.btn_zip.setEnabled(False)
        self._auftrag = auftrag
        self._worker = GispadWorker(auftrag, config, self)
        self._worker.fortschritt.connect(self._fortschritt)
        self._worker.fertig.connect(self._fertig)
        self._worker.start()

    def _fortschritt(self, prozent, text):
        if prozent >= 0:
            self.balken.setValue(prozent)
        if text:
            self.balken.setFormat(f"{text}  (%p%)")

    def _fertig(self, erfolg, fehler, ergebnis):
        self.balken.setVisible(False)
        self.btn_ordner.setEnabled(True)
        self.btn_zip.setEnabled(True)
        self.start_btn.setEnabled(bool(self._gdb))
        if not erfolg:
            self._sage("\nFehlgeschlagen:\n" + fehler)
            QMessageBox.critical(self, "Fehlgeschlagen",
                                 fehler.split("\n")[0])
            return
        if self._auftrag == "erschliessen":
            self._nach_erschliessen(ergebnis)
            return
        self._erzeuge_produkte(ergebnis)

    def _erzeuge_produkte(self, ergebnis):
        from qgis.PyQt.QtWidgets import QApplication
        try:
            from .core import mako_tabelle, mako_karte
        except ImportError:
            from qgis_new_project_plugin.core import mako_tabelle, mako_karte
        daten = ergebnis["daten"]
        titel = self.titel_edit.text().strip() or daten["titel"]
        n_fl = len(daten["flaechen"])
        n_m = sum(len(f["massnahmen"]) for f in daten["flaechen"])
        self._sage(f"{n_fl} Maßnahmenflächen mit {n_m} Einzelmaßnahmen "
                   f"ausgewertet.")
        dateien = [self._gpkg]
        sicher = _dateiname(titel)
        if self.cb_tabelle.isChecked():
            self._sage("Schreibe Maßnahmentabelle …")
            QApplication.processEvents()
            odt = os.path.join(self._ausgabe, f"Massnahmentabelle_{sicher}.odt")
            pdf = os.path.join(self._ausgabe, f"Massnahmentabelle_{sicher}.pdf")
            try:
                bloecke = mako_tabelle.erzeuge(daten, odt, pdf, titel)
                self._sage(f"   {bloecke} Blöcke → {os.path.basename(odt)}, "
                           f"{os.path.basename(pdf)}")
                dateien += [odt, pdf]
            except Exception as e:                   # noqa: BLE001
                import traceback
                self._sage(f"   Tabelle fehlgeschlagen: {e}\n"
                           f"{traceback.format_exc()[:800]}")
        if self.cb_karte.isChecked():
            self._sage("Lade Kartenlayer und lege das Drucklayout an …")
            QApplication.processEvents()
            try:
                layer = mako_karte.lade(self._gpkg)
                layout, m, bef = mako_karte.baue_layout(
                    daten, layer, titel,
                    format_name=self.format_combo.currentText(),
                    bearbeitung=self.bearb_edit.text().strip())
                daten["befunde"].extend(bef)
                pdf = os.path.join(self._ausgabe,
                                   f"Massnahmenkarte_{sicher}.pdf")
                if mako_karte.exportiere_pdf(layout, pdf):
                    dateien.append(pdf)
                self._sage(f"   Drucklayout „{layout.name()}“ im Projekt, "
                           f"Maßstab 1 : {m:,}".replace(",", ".") +
                           f" → {os.path.basename(pdf)}")
            except Exception as e:                   # noqa: BLE001
                import traceback
                self._sage(f"   Karte fehlgeschlagen: {e}\n"
                           f"{traceback.format_exc()[:800]}")
        if daten["befunde"]:
            self._sage("\nHinweise:")
            for b in daten["befunde"]:
                self._sage(f"   • {b}")
        self._sage("\nDateien:")
        for d in dateien:
            self._sage(f"   {d}")
        self._sage("\nBitte vor der Weitergabe auf Plausibilität prüfen – "
                   "Korrekturen gehören in die Daten, nicht in die Tabelle.")
        QMessageBox.information(
            self, "Fertig", f"MAKO-Produkte erzeugt in:\n{self._ausgabe}")

    # ── Aufräumen ───────────────────────────────────────────────────────────
    def _raeume_temp_auf(self):
        if self._temp:
            raeume_auf(self._temp)
            self._temp = None

    def _laeuft_noch(self):
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "Noch nicht fertig",
                                    "Der Vorgang läuft noch.")
            return True
        return False

    def closeEvent(self, ereignis):
        if self._laeuft_noch():
            ereignis.ignore()
            return
        self._raeume_temp_auf()
        super().closeEvent(ereignis)

    def reject(self):
        if self._laeuft_noch():
            return
        self._raeume_temp_auf()
        super().reject()
