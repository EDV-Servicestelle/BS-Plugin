"""
nrw_hydro_dialog.py - HydroDialog
====================================
Reine UI-Schicht. Geschaeftlogik in core/hydro.py,
Worker in workers/hydro_worker.py.
"""
import os

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QGroupBox, QDialogButtonBox,
    QProgressBar, QTextEdit, QDoubleSpinBox, QSpinBox,
    QFileDialog, QLineEdit, QCheckBox, QComboBox,
    QTabWidget, QWidget,
)
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsProject

from .core.hydro import _ACCEL
try:
    import requests as _req
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False
from .workers.hydro_worker import _HydroWorker

class HydroDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(
            "FT – Hydrologische Analyse (Renaturierung Moore/Gewässer)")
        self.setMinimumWidth(560)
        self._worker = None
        self._build_ui()

    def _build_ui(self):
        lo = QVBoxLayout(self)

        lo.addWidget(QLabel(
            "Berechnet aus einem DTM (COG GeoTIFF) hydrologische Grundlagendaten\n"
            "für die Planung von Renaturierungsmaßnahmen an Mooren und Gewässern."))

        tabs = QTabWidget()

        # ── Tab 1: Eingabe ─────────────────────────────────────────────────────
        t1 = QWidget(); f1 = QFormLayout(t1)

        dtm_row = QHBoxLayout()
        self.dtm_edit = QLineEdit()
        self.dtm_edit.setPlaceholderText("DTM COG GeoTIFF (.tif) …")
        dtm_btn = QPushButton("…"); dtm_btn.setFixedWidth(30)
        dtm_btn.clicked.connect(self._browse_dtm)
        dtm_row.addWidget(self.dtm_edit); dtm_row.addWidget(dtm_btn)
        f1.addRow("DTM (COG .tif):", dtm_row)

        # DTM aus QGIS-Layer
        self.dtm_layer_combo = QComboBox()
        self._populate_raster_combo()
        f1.addRow("oder Layer:", self.dtm_layer_combo)
        self.dtm_layer_combo.currentIndexChanged.connect(self._from_layer)

        out_row = QHBoxLayout()
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("Ausgabe-Verzeichnis …")
        out_btn = QPushButton("…"); out_btn.setFixedWidth(30)
        out_btn.clicked.connect(self._browse_out)
        out_row.addWidget(self.out_edit); out_row.addWidget(out_btn)
        f1.addRow("Ausgabeordner:", out_row)

        self.name_edit = QLineEdit("hydro")
        self.name_edit.setToolTip(
            "Präfix für alle Ausgabedateien, z.B. 'moor_nord'")
        f1.addRow("Präfix:", self.name_edit)

        tabs.addTab(t1, "Eingabe")

        # ── Tab 2: Parameter ───────────────────────────────────────────────────
        t2 = QWidget(); f2 = QFormLayout(t2)

        self.thresh_spin = QSpinBox()
        self.thresh_spin.setRange(10, 100000)
        self.thresh_spin.setValue(500)
        self.thresh_spin.setSingleStep(100)
        self.thresh_spin.setSuffix(" Zellen (Einzugsgebiet)")
        self.thresh_spin.setToolTip(
            "Mindesteinzugsgebiet für Gewässerextraktion:\n"
            "Niedrig (100–500): sehr dichtes Netz, Gräben sichtbar\n"
            "Mittel (500–2000): Hauptgewässer + Nebenbäche\n"
            "Hoch (>5000):     nur Hauptgewässer")
        f2.addRow("Gewässer-Schwelle:", self.thresh_spin)

        self.sink_depth_spin = QDoubleSpinBox()
        self.sink_depth_spin.setRange(0.01, 5.0)
        self.sink_depth_spin.setValue(0.05)
        self.sink_depth_spin.setSingleStep(0.05)
        self.sink_depth_spin.setDecimals(2)
        self.sink_depth_spin.setSuffix(" m Mindesttiefe")
        self.sink_depth_spin.setToolTip(
            "Mindesttiefe einer Senke um erkannt zu werden.\n"
            "0.05 m = 5 cm (empfohlen für Moore)\n"
            "0.20 m = 20 cm (nur tiefe Senken)")
        f2.addRow("Senkentiefe min.:", self.sink_depth_spin)

        self.sink_area_spin = QSpinBox()
        self.sink_area_spin.setRange(1, 10000)
        self.sink_area_spin.setValue(25)
        self.sink_area_spin.setSuffix(" m² Mindestfläche")
        f2.addRow("Senkenfläche min.:", self.sink_area_spin)

        tabs.addTab(t2, "Parameter")

        # ── Tab 3: Ausgabe-Produkte ────────────────────────────────────────────
        t3 = QWidget(); v3 = QVBoxLayout(t3)
        v3.addWidget(QLabel("<b>Raster (COG GeoTIFF, EPSG:25832):</b>"))

        self.cb_fdir    = QCheckBox("Fließrichtung D8              (_fliessrichtung.tif)")
        self.cb_acc     = QCheckBox("Abflussakkumulation (log)     (_akkumulation.tif)")
        self.cb_str_r   = QCheckBox("Strahler-Ordnung Raster       (_gewaessernetz.tif)")
        self.cb_snk_r    = QCheckBox("Abflusssenken Tiefe           (_senken.tif)")
        self.cb_fill_dem = QCheckBox("Gefülltes DEM                 (_filled.tif)")
        self.cb_fill_dem.setToolTip(
            "Speichert das senkengefüllte Höhenmodell als GeoTIFF.")
        for cb in [self.cb_fill_dem, self.cb_fdir, self.cb_acc,
                   self.cb_str_r, self.cb_snk_r]:
            cb.setChecked(True); v3.addWidget(cb)

        v3.addWidget(QLabel("<b>Vektor (GPKG, EPSG:25832):</b>"))
        self.cb_str_v   = QCheckBox("Gewässernetz Linien           (_gewaessernetz.gpkg)")
        self.cb_snk_v   = QCheckBox("Senkenflächen Polygone        (_senken.gpkg)")
        for cb in [self.cb_str_v, self.cb_snk_v]:
            cb.setChecked(True); v3.addWidget(cb)

        v3.addWidget(QLabel(
            "\nHinweis: Gewässernetz-Vektor enthält Strahler-Ordnung\n"
            "als Attribut (1 = Quellbach/Graben, ≥3 = Bach/Fluss)."))
        tabs.addTab(t3, "Produkte")

        lo.addWidget(tabs)

        # ── Log + Fortschritt ──────────────────────────────────────────────────
        self.log = QTextEdit(); self.log.setReadOnly(True)
        self.log.setFixedHeight(160)
        lo.addWidget(self.log)
        self.bar = QProgressBar(); self.bar.setVisible(False)
        lo.addWidget(self.bar)

        bb = QDialogButtonBox()
        self.start_btn = bb.addButton(
            "Analyse starten", QDialogButtonBox.ButtonRole.AcceptRole)
        self.stop_btn  = bb.addButton(
            "Abbrechen", QDialogButtonBox.ButtonRole.RejectRole)
        self.start_btn.clicked.connect(self._start)
        self.stop_btn.clicked.connect(self._abort)
        lo.addWidget(bb)

    # ── Slots ──────────────────────────────────────────────────────────────────

    def _populate_raster_combo(self):
        self.dtm_layer_combo.clear()
        self.dtm_layer_combo.addItem("— aus Datei —", None)
        for lyr in QgsProject.instance().mapLayers().values():
            if hasattr(lyr, "dataProvider"):
                try:
                    dp = lyr.dataProvider()
                    if "gdal" in dp.name().lower() or "wms" not in dp.name().lower():
                        self.dtm_layer_combo.addItem(lyr.name(), lyr)
                except Exception:
                    pass

    def _from_layer(self):
        lyr = self.dtm_layer_combo.currentData()
        if lyr:
            self.dtm_edit.setText(lyr.source())

    def _browse_dtm(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "DTM GeoTIFF wählen", "", "GeoTIFF (*.tif *.tiff)")
        if p:
            self.dtm_edit.setText(p)
            # Ausgabeordner vorbelegen
            if not self.out_edit.text():
                self.out_edit.setText(os.path.dirname(p))

    def _browse_out(self):
        d = QFileDialog.getExistingDirectory(
            self, "Ausgabeordner wählen", self.out_edit.text())
        if d:
            self.out_edit.setText(d)

    def _log(self, msg):
        self.log.append(msg)
        self.log.verticalScrollBar().setValue(
            self.log.verticalScrollBar().maximum())

    def _start(self):
        dtm = self.dtm_edit.text().strip()
        out = self.out_edit.text().strip()
        if not dtm or not os.path.exists(dtm):
            self._log("⚠ DTM-Datei nicht gefunden."); return
        if not out:
            self._log("⚠ Ausgabeordner wählen."); return
        os.makedirs(out, exist_ok=True)

        cfg = {
            "dtm_path":       dtm,
            "out_dir":        out,
            "name":           self.name_edit.text().strip() or "hydro",
            "acc_threshold":  self.thresh_spin.value(),
            "min_sink_depth": self.sink_depth_spin.value(),
            "min_sink_area":  self.sink_area_spin.value(),
            "out_fill_dem":   self.cb_fill_dem.isChecked(),
            "out_fdir":       self.cb_fdir.isChecked(),
            "out_acc":        self.cb_acc.isChecked(),
            "out_sinks":      self.cb_snk_r.isChecked() or self.cb_snk_v.isChecked(),
            "out_sinks_raster": self.cb_snk_r.isChecked(),
            "out_sinks_vector": self.cb_snk_v.isChecked(),
            "out_streams_raster": self.cb_str_r.isChecked(),
            "out_streams_vector": self.cb_str_v.isChecked(),
        }

        self.start_btn.setEnabled(False)
        self.bar.setRange(0, 100); self.bar.setValue(0)
        self.bar.setVisible(True)

        self._worker = _HydroWorker(cfg, parent=self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _abort(self):
        if self._worker and self._worker.isRunning():
            self._worker.abort()
            self._worker.finished.connect(lambda *_: self.reject())
        else:
            self.reject()

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.abort()
            self._worker.wait(3000)
        event.accept()

    def _on_progress(self, pct, msg):
        if pct >= 0: self.bar.setValue(pct)
        if msg: self._log(msg)

    def _on_finished(self, ok, msg):
        self._log(msg)
        self.bar.setValue(100 if ok else 0)
        self.start_btn.setEnabled(True)
