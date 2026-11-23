"""
ornitho_import_dialog.py – ornitho.de-Export (JSON oder Excel) importieren
==============================================================
Liest den ornitho.de-Export im Basic+-Format (JSON) und erstellt
einen QGIS-Punktlayer mit allen Beobachtungen - Einzelbeobachtungen UND
Beobachtungen aus Listen (forms). Alternativ den Excel-Export (.xlsx).
Die Auswertung liegt in core/ornitho.py.
"""

import os
from datetime import datetime

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QGroupBox, QLineEdit,
    QTextEdit, QProgressBar, QFileDialog, QCheckBox,
    QSpinBox, QComboBox,
)
from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry,
    QgsPointXY, QgsFields, QgsField, QgsCoordinateReferenceSystem, NULL,
)

try:
    from qgis_new_project_plugin.core.ornitho import FELDER, lade
except ImportError:
    from .core.ornitho import FELDER, lade


class OrnithoImportDialog(QDialog):
    """Dialog zum Import von ornitho.de Basic+-Exporten."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ornitho.de – Import")
        self.setMinimumWidth(500)
        self._sightings = []
        self._build_ui()

    # ── UI ──────────────────────────────────────────────────────────────────

    def _build_ui(self):
        lo = QVBoxLayout(self)

        # Datei-Auswahl
        file_grp = QGroupBox("Exportdatei (JSON im Basic+-Format oder Excel)")
        file_lo  = QHBoxLayout(file_grp)
        self.file_edit = QLineEdit()
        self.file_edit.setPlaceholderText("export_XXXX.json oder .xlsx …")
        self.file_edit.setReadOnly(True)
        browse_btn = QPushButton("Durchsuchen …")
        browse_btn.clicked.connect(self._browse)
        file_lo.addWidget(self.file_edit)
        file_lo.addWidget(browse_btn)
        lo.addWidget(file_grp)

        # Filter
        flt_grp = QGroupBox("Filter (optional)")
        flt_fl  = QFormLayout(flt_grp)

        self.art_edit = QLineEdit()
        self.art_edit.setPlaceholderText("z.B. Zilpzalp  –  leer = alle Arten")
        flt_fl.addRow("Art (dt. oder lat.):", self.art_edit)

        yr_lo = QHBoxLayout()
        self.year_from = QSpinBox(); self.year_from.setRange(1900, 2100); self.year_from.setValue(2020)
        self.year_to   = QSpinBox(); self.year_to.setRange(1900, 2100)
        self.year_to.setValue(datetime.now().year)
        yr_lo.addWidget(self.year_from)
        yr_lo.addWidget(QLabel("–"))
        yr_lo.addWidget(self.year_to)
        self.year_cb = QCheckBox("Jahresfilter aktiv")
        yr_lo.addWidget(self.year_cb)
        flt_fl.addRow("Zeitraum (Jahr):", yr_lo)

        # Standard: AUS. Sonst fallen alle Beobachtungen weg, die nur einem
        # Ort zugeordnet sind (precision != precise).
        self.only_precise = QCheckBox(
            "Nur exakt verortete Beobachtungen (ohne Ortsangaben)")
        self.only_precise.setChecked(False)
        flt_fl.addRow("", self.only_precise)

        lo.addWidget(flt_grp)

        # Vorschau
        self.info_lbl = QLabel("Keine Datei geladen.")
        self.info_lbl.setStyleSheet("color: gray; font-style: italic;")
        lo.addWidget(self.info_lbl)

        # Log
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(120)
        lo.addWidget(self.log)

        # Buttons
        btn_lo = QHBoxLayout()
        self.import_btn = QPushButton("Layer erstellen")
        self.import_btn.setDefault(True)
        self.import_btn.setEnabled(False)
        self.import_btn.clicked.connect(self._import)
        close_btn = QPushButton("Schließen")
        close_btn.clicked.connect(self.accept)
        btn_lo.addWidget(self.import_btn)
        btn_lo.addWidget(close_btn)
        lo.addLayout(btn_lo)

    # ── Datei laden ─────────────────────────────────────────────────────────

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "ornitho.de-Export öffnen", "",
            "ornitho-Export (*.json *.xlsx);;JSON (*.json);;Excel (*.xlsx);;"
            "Alle Dateien (*)")
        if not path:
            return
        self.file_edit.setText(path)
        self._load_file(path)

    def _load_file(self, path: str):
        try:
            zeilen = lade(path)
            self._sightings = zeilen
            in_listen = sum(1 for z in zeilen if z.get("liste_id"))
            arten = {z.get("art") or "?" for z in zeilen}
            dates = sorted(z["datum"] for z in zeilen if z.get("datum"))
            date_info = f"{dates[0]} – {dates[-1]}" if dates else "?"
            self.info_lbl.setText(
                f"{len(zeilen)} Beobachtungen ({in_listen} davon aus Listen)  |  "
                f"{len(arten)} Arten  |  {date_info}")
            self.info_lbl.setStyleSheet("color: #333;")
            self.import_btn.setEnabled(bool(zeilen))
            art = "Excel" if path.lower().endswith((".xlsx", ".xlsm")) else "JSON"
            self._log(f"✓ {len(zeilen)} Beobachtungen geladen aus "
                      f"{os.path.basename(path)} ({art})"
                      + (f" – davon {in_listen} aus Beobachtungslisten"
                         if in_listen else ""))
        except Exception as e:
            self._log(f"✗ Ladefehler: {e}")

    # ── Import ──────────────────────────────────────────────────────────────

    def _import(self):
        if not self._sightings:
            return
        art_filter   = self.art_edit.text().strip().lower()
        year_filter  = self.year_cb.isChecked()
        y_from       = self.year_from.value()
        y_to         = self.year_to.value()
        only_precise = self.only_precise.isChecked()

        typen = {"str": QVariant.String, "int": QVariant.Int}
        fields = QgsFields()
        for fname, ftyp in FELDER:
            fields.append(QgsField(fname, typen[ftyp]))

        lyr_name = "Ornitho"
        if art_filter:
            lyr_name += f"_{art_filter.replace(' ', '_')}"
        lyr = QgsVectorLayer("Point?crs=EPSG:4326", lyr_name, "memory")
        dp  = lyr.dataProvider()
        dp.addAttributes(fields.toList())
        lyr.updateFields()

        feats = []
        gefiltert = ungenau = ohne_koord = 0
        for z in self._sightings:

            if art_filter and (art_filter not in z["art"].lower()
                               and art_filter not in z["art_lat"].lower()):
                gefiltert += 1
                continue
            if year_filter and z["jahr"] and not (y_from <= z["jahr"] <= y_to):
                gefiltert += 1
                continue
            if only_precise and z["praezision"] and z["praezision"] != "precise":
                ungenau += 1
                continue
            if z["lat"] is None:
                ohne_koord += 1
                continue

            feat = QgsFeature(lyr.fields())
            feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(z["lon"], z["lat"])))
            for fname, _t in FELDER:
                wert = z.get(fname)
                feat[fname] = NULL if wert is None else wert
            feats.append(feat)

        dp.addFeatures(feats)
        lyr.updateExtents()

        # Stil: orangefarbene Punkte
        try:
            sym = lyr.renderer().symbol()
            sym.setColor(QColor(220, 80, 20))
            sym.setSize(2.5)
        except Exception:
            pass

        QgsProject.instance().addMapLayer(lyr)
        teile = [f"✓ Layer '{lyr_name}': {len(feats)} von "
                 f"{len(self._sightings)} Beobachtungen übernommen"]
        if gefiltert:
            teile.append(f"   {gefiltert} durch Art-/Jahresfilter ausgeblendet")
        if ungenau:
            teile.append(f"   {ungenau} nicht exakt verortet (Filter „nur exakt "
                         f"verortete“ ist aktiv)")
        if ohne_koord:
            teile.append(f"   ⚠ {ohne_koord} ohne Koordinaten – nicht übernommen")
        self._log("\n".join(teile))

    def _log(self, msg: str):
        self.log.append(msg)
