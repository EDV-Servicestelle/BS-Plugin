"""
nrw_grundlagen_dialog.py - GrundlagenDialog
===============================================
Reine UI-Schicht.
"""
import math, os
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QGroupBox, QDialogButtonBox,
    QProgressBar, QTextEdit, QDoubleSpinBox,
    QFileDialog, QLineEdit, QCheckBox, QComboBox,
    QWidget, QScrollArea,
)
from qgis.core import (
    QgsProject, QgsCoordinateReferenceSystem,
    QgsCoordinateTransform, QgsCoordinateTransformContext,
    QgsVectorLayer, QgsWkbTypes,
)

WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")
UTM32 = QgsCoordinateReferenceSystem("EPSG:25832")

from .core.grundlagen import DIENSTE, _REQUESTS_OK, _wgs84_to_utm32, WGS84, UTM32
from .workers.grundlagen_worker import _GrundlagenWorker

class GrundlagenDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("FT – NRW Grundlagendaten abrufen")
        self.setMinimumWidth(530)
        self._worker = None
        self._build_ui()
        self._load_canvas_extent()

    def _build_ui(self):
        lo = QVBoxLayout(self)

        lo.addWidget(QLabel(
            "Ruft Naturschutz-Grundlagendaten für ein Untersuchungsgebiet\n"
            "aus NRW-OGC-API / WFS ab und speichert sie als GeoPackage."))

        # ── Bereich ───────────────────────────────────────────────────────────
        bg = QGroupBox("Untersuchungsgebiet (WGS84)"); bf = QFormLayout()
        def dbl(v, lo_, hi_):
            sb = QDoubleSpinBox(); sb.setDecimals(6)
            sb.setRange(lo_, hi_); sb.setValue(v); sb.setSingleStep(0.001)
            return sb
        self.lon_min = dbl(6.0, 5.8, 9.6)
        self.lat_min = dbl(50.3, 50.2, 52.6)
        self.lon_max = dbl(7.2, 5.8, 9.6)
        self.lat_max = dbl(51.4, 50.2, 52.6)
        bf.addRow("Lon min:", self.lon_min); bf.addRow("Lat min:", self.lat_min)
        bf.addRow("Lon max:", self.lon_max); bf.addRow("Lat max:", self.lat_max)

        cb_row = QHBoxLayout()
        cb_btn = QPushButton("Aus Kartenausschnitt")
        cb_btn.clicked.connect(self._load_canvas_extent)
        cb_row.addWidget(cb_btn)

        self.extent_layer_combo = QComboBox()
        self._populate_layer_combo()
        lyr_btn = QPushButton("Aus Layer"); lyr_btn.setFixedWidth(80)
        lyr_btn.clicked.connect(self._load_layer_extent)
        cb_row.addWidget(self.extent_layer_combo)
        cb_row.addWidget(lyr_btn)
        bf.addRow("", cb_row)

        self.est_lbl = QLabel("")
        self.est_lbl.setStyleSheet("color:gray;font-size:11px;")
        bf.addRow("", self.est_lbl)
        bg.setLayout(bf); lo.addWidget(bg)
        for sb in [self.lon_min, self.lat_min, self.lon_max, self.lat_max]:
            sb.valueChanged.connect(self._update_estimate)
        self._update_estimate()

        # ── Datenschichten ────────────────────────────────────────────────────
        from qgis.PyQt.QtCore import Qt
        dg = QGroupBox("Datenschichten")
        dv = QVBoxLayout()
        self.dienst_checks = {}
        # Gruppiert nach Kategorie
        gruppen = {}
        for key, cfg in DIENSTE.items():
            if cfg.get("typ") == "_intern": continue  # kein Checkbox für berechnete Layer
            g = cfg.get("gruppe", "Sonstige")
            gruppen.setdefault(g, []).append((key, cfg))
        for gruppe, eintraege in gruppen.items():
            grp_lbl = QLabel(f"<b>{gruppe}</b>")
            grp_lbl.setStyleSheet("margin-top:4px;")
            dv.addWidget(grp_lbl)
            for key, cfg in eintraege:
                cb = QCheckBox("  " + cfg["label"])
                cb.setChecked(cfg.get("default_on", False))
                self.dienst_checks[key] = cb
                dv.addWidget(cb)
        inner = QWidget(); inner.setLayout(dv)
        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(280)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        dg_lo = QVBoxLayout(); dg_lo.addWidget(scroll)
        dg.setLayout(dg_lo); lo.addWidget(dg)

        # ── Ausgabe ───────────────────────────────────────────────────────────
        og = QGroupBox("Ausgabe (.gpkg)"); ov = QHBoxLayout()
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("Pfad zur GPKG-Ausgabedatei …")
        ob = QPushButton("…"); ob.setFixedWidth(30)
        ob.clicked.connect(self._browse)
        ov.addWidget(self.out_edit); ov.addWidget(ob)
        og.setLayout(ov); lo.addWidget(og)

        # ── Log ───────────────────────────────────────────────────────────────
        self.log = QTextEdit(); self.log.setReadOnly(True)
        self.log.setFixedHeight(170)
        lo.addWidget(self.log)
        self.bar = QProgressBar(); self.bar.setVisible(False)
        lo.addWidget(self.bar)

        # ── Buttons ───────────────────────────────────────────────────────────
        bb = QDialogButtonBox()
        self.start_btn = bb.addButton(
            "Daten abrufen", QDialogButtonBox.ButtonRole.AcceptRole)
        self.stop_btn = bb.addButton(
            "Abbrechen", QDialogButtonBox.ButtonRole.RejectRole)
        self.start_btn.clicked.connect(self._start)
        self.stop_btn.clicked.connect(self._abort)
        lo.addWidget(bb)

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _populate_layer_combo(self):
        self.extent_layer_combo.clear()
        self.extent_layer_combo.addItem("— Layer wählen —", None)
        for lyr in QgsProject.instance().mapLayers().values():
            self.extent_layer_combo.addItem(lyr.name(), lyr)

    def _load_canvas_extent(self):
        """Liest den aktuellen Kartenausschnitt (Snapshot)."""
        try:
            from qgis.utils import iface
            canvas = iface.mapCanvas()
            ext = canvas.extent()
            crs = canvas.mapSettings().destinationCrs()
            tr  = QgsCoordinateTransform(
                crs, WGS84, QgsCoordinateTransformContext())
            e   = tr.transformBoundingBox(ext)
            self.lon_min.setValue(round(max(5.8,  e.xMinimum()), 6))
            self.lat_min.setValue(round(max(50.2, e.yMinimum()), 6))
            self.lon_max.setValue(round(min(9.6,  e.xMaximum()), 6))
            self.lat_max.setValue(round(min(52.6, e.yMaximum()), 6))
            self._update_estimate()
        except Exception as ex:
            pass  # kein Canvas verfügbar

    def _connect_canvas_sync(self):
        """Verbindet Canvas-Extent-Signal für Live-Nachführung."""
        try:
            from qgis.utils import iface
            iface.mapCanvas().extentsChanged.connect(
                self._load_canvas_extent)
        except Exception:
            pass

    def _disconnect_canvas_sync(self):
        try:
            from qgis.utils import iface
            iface.mapCanvas().extentsChanged.disconnect(
                self._load_canvas_extent)
        except Exception:
            pass

    def _load_layer_extent(self):
        lyr = self.extent_layer_combo.currentData()
        if not lyr: return
        try:
            tr  = QgsCoordinateTransform(
                lyr.crs(), WGS84, QgsCoordinateTransformContext())
            e   = tr.transformBoundingBox(lyr.extent())
            self.lon_min.setValue(max(5.8,  e.xMinimum()))
            self.lat_min.setValue(max(50.2, e.yMinimum()))
            self.lon_max.setValue(min(9.6,  e.xMaximum()))
            self.lat_max.setValue(min(52.6, e.yMaximum()))
            self._update_estimate()
            self._log(f"Ausdehnung von '{lyr.name()}' übernommen.")
        except Exception as ex:
            self._log(f"⚠ {ex}")

    def _update_estimate(self):
        try:
            dlon = self.lon_max.value() - self.lon_min.value()
            dlat = self.lat_max.value() - self.lat_min.value()
            km2  = dlon * dlat * 111.32 * 111.32 * math.cos(
                math.radians((self.lat_min.value() + self.lat_max.value()) / 2))
            self.est_lbl.setText(f"Fläche: ~{km2:.1f} km²")
        except Exception:
            pass

    def _browse(self):
        p, _ = QFileDialog.getSaveFileName(
            self, "GeoPackage speichern", "", "GeoPackage (*.gpkg)")
        if p:
            if not p.endswith(".gpkg"): p += ".gpkg"
            self.out_edit.setText(p)

    def _log(self, msg):
        self.log.append(msg)
        self.log.verticalScrollBar().setValue(
            self.log.verticalScrollBar().maximum())

    def _start(self):
        if not _REQUESTS_OK:
            self._log("⚠ requests fehlt: pip install requests"); return
        out = self.out_edit.text().strip()
        if not out:
            self._log("⚠ Ausgabedatei wählen."); return
        aktiv = {k: cb.isChecked() for k, cb in self.dienst_checks.items()}
        if not any(aktiv.values()):
            self._log("⚠ Mindestens eine Datenschicht auswählen."); return

        cfg = {
            "gpkg_path": out,
            "bbox_4326": (
                self.lon_min.value(), self.lat_min.value(),
                self.lon_max.value(), self.lat_max.value(),
            ),
            "aktiv":   aktiv,
            "timeout": 90,
        }
        self.start_btn.setEnabled(False)
        self.bar.setRange(0, 100); self.bar.setValue(0)
        self.bar.setVisible(True)
        self._worker = _GrundlagenWorker(cfg, parent=self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _abort(self):
        if self._worker and self._worker.isRunning():
            self._worker.abort()
            self._worker.finished.connect(lambda *_: self.reject())
        else:
            self.reject()

    def showEvent(self, event):
        super().showEvent(event)
        self._load_canvas_extent()   # Extent beim Öffnen laden
        self._connect_canvas_sync()  # Live-Nachführung starten

    def closeEvent(self, event):
        self._disconnect_canvas_sync()
        if self._worker and self._worker.isRunning():
            self._worker.abort()
            self._worker.wait(3000)
        event.accept()

    def _on_progress(self, pct, msg):
        if pct >= 0: self.bar.setValue(pct)
        if msg: self._log(msg)

    def _load_layers(self, gpkg_path: str):
        """Lädt alle Grundlagen-Layer mit Features ins QGIS-Projekt."""
        from qgis.core import QgsVectorLayer, QgsProject
        from .core.grundlagen import DIENSTE
        import os as _os
        if not _os.path.exists(gpkg_path):
            return
        proj = QgsProject.instance()
        root = proj.layerTreeRoot()
        grp_name = "Grundlagendaten"
        grp = root.findGroup(grp_name)
        if grp is None:
            grp = root.insertGroup(0, grp_name)
        sub_cache = {}
        for key, cfg in DIENSTE.items():
            lyr = QgsVectorLayer(
                f"{gpkg_path}|layername={key}", cfg["label"], "ogr")
            if not lyr.isValid() or lyr.featureCount() == 0:
                continue
            sub_name = cfg.get("gruppe", "Sonstige")
            if sub_name not in sub_cache:
                sub = grp.findGroup(sub_name) or grp.addGroup(sub_name)
                sub_cache[sub_name] = sub
            proj.addMapLayer(lyr, False)
            sub_cache[sub_name].addLayer(lyr)
            self._log(f"  ✓ {cfg['label']} ({lyr.featureCount()} Features)")

    def _on_finished(self, ok, msg):
        self._log(msg)
        self.bar.setValue(100 if ok else 0)
        self.start_btn.setEnabled(True)
        if ok:
            gpkg_path = self.out_edit.text().strip()
            self._load_layers(gpkg_path)
            # Breaklines im LiDAR-Dialog vorauswählen
            try:
                from .lidar_dialog import LidarDialog as _LD
                from qgis.PyQt.QtWidgets import QApplication
                for w in QApplication.topLevelWidgets():
                    if isinstance(w, _LD):
                        w.preseed_breaklines_from_grundlagen(gpkg_path)
                        self._log("  → Breaklines im LiDAR-Dialog vorausgewählt")
            except Exception:
                pass
