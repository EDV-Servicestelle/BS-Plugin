"""
nrw_lidar_dialog.py - LidarDialog
=====================================
Reine UI-Schicht.
Algorithmen: core/lidar.py | Worker: workers/lidar_worker.py
"""
import os
from qgis.PyQt.QtWidgets import (
    QTabWidget, QWidget,
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QGroupBox, QDialogButtonBox,
    QProgressBar, QTextEdit, QDoubleSpinBox, QSpinBox,
    QFileDialog, QLineEdit, QCheckBox, QComboBox,
)
from qgis.core import (
    QgsProject, QgsCoordinateReferenceSystem,
    QgsCoordinateTransform, QgsCoordinateTransformContext,
    QgsVectorLayer, QgsWkbTypes, QgsGeometry,
)

WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")
UTM32 = QgsCoordinateReferenceSystem("EPSG:25832")

from .core.lidar import (
    _LASPY_OK, _GDAL_OK, _REQUESTS_OK, _NUMPY_OK, _PDAL_OK,
    CLASS_GROUND, GRID_M, WGS84, UTM32,
    _las_tiles, _wgs84_to_utm32,
)
from .workers.lidar_worker import _LidarWorker

class LidarDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("FT – NRW LiDAR → Höhenraster (1×1 m)")
        self.setMinimumWidth(520)
        self._worker = None
        self._build_ui()
        self._load_canvas_extent()
        self._check_deps()

    def _check_deps(self):
        if not _REQUESTS_OK:
            self._log("⚠ requests fehlt: pip install requests")
        if not _LASPY_OK and not _PDAL_OK:
            self._log("⚠ Weder laspy noch PDAL gefunden – LAZ-Dateien können NICHT gelesen werden!")
            self._log("  → QGIS über OSGeo4W Shell starten (pdal ist dort im PATH)")
            self._log("  → ODER: pip install laspy lazrs-python")
            self._log("  → ODER: In QGIS Python-Konsole ausführen:")
            self._log("     import subprocess, sys")
            self._log("     subprocess.run([sys.executable, '-m', 'pip', 'install', 'laspy', 'lazrs-python'])")
        elif not _LASPY_OK and _PDAL_OK:
            self._log("ℹ laspy nicht installiert – nutze PDAL für LAZ-Lesen (langsamer)")
            self._log("  Tipp: pip install laspy lazrs-python  (5× schneller)")
        elif _LASPY_OK:
            self._log("✓ laspy verfügbar – LAZ-Lesen aktiviert")
        if not _NUMPY_OK:
            self._log("⚠ numpy fehlt: pip install numpy")

    def _build_ui(self):
        lo = QVBoxLayout(self)

        lo.addWidget(QLabel(
            "Lädt LiDAR-Punktwolken (LAZ) von OpenGeoData NRW,\n"
            "berechnet mittlere Höhe pro 1×1 m Zelle und\n"
            "schreibt ein Polygon-Vektorraster als GeoPackage."))

        # Bereich
        bg = QGroupBox("Bereich (WGS84)")
        bf = QFormLayout()
        def dbl(v, lo_, hi_):
            sb = QDoubleSpinBox(); sb.setDecimals(6)
            sb.setRange(lo_, hi_); sb.setValue(v); sb.setSingleStep(0.001)
            return sb
        self.lon_min = dbl(6.80, 5.8, 9.6)
        self.lat_min = dbl(51.20, 50.2, 52.6)
        self.lon_max = dbl(6.85, 5.8, 9.6)
        self.lat_max = dbl(51.24, 50.2, 52.6)
        bf.addRow("Lon min:", self.lon_min); bf.addRow("Lat min:", self.lat_min)
        bf.addRow("Lon max:", self.lon_max); bf.addRow("Lat max:", self.lat_max)
        cb_btn = QPushButton("Aus Kartenausschnitt")
        cb_btn.clicked.connect(self._load_canvas_extent)
        bf.addRow("", cb_btn)
        # Layer-Ausdehnung
        lyr_row = QHBoxLayout()
        self.extent_layer_combo = QComboBox()
        self._populate_layer_combo()
        lyr_btn = QPushButton("Aus Layer")
        lyr_btn.setFixedWidth(80)
        lyr_btn.clicked.connect(self._load_layer_extent)
        lyr_row.addWidget(self.extent_layer_combo)
        lyr_row.addWidget(lyr_btn)
        bf.addRow("Abgrenzung:", lyr_row)

        opt_row = QHBoxLayout()
        self.clip_cb = QCheckBox("auf Geometrie zuschneiden")
        self.clip_cb.setToolTip(
            "Statt nur der rechteckigen Ausdehnung wird das Ergebnis auf die "
            "tatsächliche Fläche des Layers beschnitten "
            "(z. B. Untersuchungsgebiet, Schutzgebiet).")
        self.sel_only_cb = QCheckBox("nur ausgewählte Objekte")
        self.sel_only_cb.setToolTip(
            "Nur die im Layer selektierten Objekte als Abgrenzung verwenden.")
        opt_row.addWidget(self.clip_cb)
        opt_row.addWidget(self.sel_only_cb)
        opt_row.addStretch(1)
        bf.addRow("", opt_row)
        self.clip_lbl = QLabel("")
        self.clip_lbl.setStyleSheet("color:gray;font-size:11px;")
        bf.addRow("", self.clip_lbl)
        for _cb in (self.clip_cb, self.sel_only_cb):
            _cb.toggled.connect(lambda *_: self._build_clip_geometry(
                self.extent_layer_combo.currentData()))

        self.est_lbl = QLabel("")
        self.est_lbl.setStyleSheet("color:gray;font-size:11px;")
        bf.addRow("", self.est_lbl)
        bg.setLayout(bf); lo.addWidget(bg)
        for sb in [self.lon_min,self.lat_min,self.lon_max,self.lat_max]:
            sb.valueChanged.connect(self._update_estimate)
        self._update_estimate()

        # Optionen
        og = QGroupBox("Einstellungen")
        of = QFormLayout()

        self.cls_combo = QComboBox()
        self.cls_combo.addItem("Nur Boden (Klasse 2 – empfohlen)", CLASS_GROUND)
        self.cls_combo.addItem("Alle Punkte (inkl. Vegetation/Gebäude)", None)
        self.cls_combo.addItem("Erste Rückgabe (Oberfläche)", 1)

        self.workers_spin = QSpinBox(); self.workers_spin.setRange(1,8)
        self.workers_spin.setValue(3); self.workers_spin.setSuffix(" Threads")
        self.cell_spin = QDoubleSpinBox()
        self.cell_spin.setRange(0.25, 10.0)
        self.cell_spin.setValue(1.0)
        self.cell_spin.setSingleStep(0.25)
        self.cell_spin.setDecimals(2)
        self.cell_spin.setSuffix(" m (Zellgröße)")
        self.cell_spin.setToolTip(
            "0.25 m = sehr fein (viel Speicher)\n"
            "1.0 m  = Standard (NRW LiDAR-Dichte)\n"
            "2.5 m  = grob (schnell, wenig Lücken)")
        self.keep_cb = QCheckBox("LAZ-Quelldateien behalten")
        self.fill_cb = QCheckBox("Lücken füllen (IDW, Radius 5 m)")
        self.fill_cb.setChecked(True)
        self.fill_cb.setToolTip(
            "Füllt Zellen ohne LiDAR-Punkte durch gewichtete Interpolation\n"
            "der bis zu 5 m entfernten Nachbarzellen (IDW 1/d²).\n\n"
            "Wird automatisch deaktiviert wenn TIN gewählt ist,\n"
            "da TIN Lücken selbst durch Interpolation schließt.")

        # Aggregation
        self.agg_spin = QDoubleSpinBox()
        self.agg_spin.setRange(0.0, 10.0)
        self.agg_spin.setValue(0.0)
        self.agg_spin.setSingleStep(0.5)
        self.agg_spin.setDecimals(1)
        self.agg_spin.setSpecialValueText("keine Aggregation")
        self.agg_spin.setToolTip(
            "0.0 = keine Aggregation\n"
            "2.0 m = 4 × Basiszellen zusammenfassen\n"
            "5.0 m = 25 × Basiszellen zusammenfassen\n"
            "10.0 m = 100 × Basiszellen zusammenfassen")
        self.agg_func_combo = QComboBox()
        for lbl, val in [
                ("Mittelwert (mean)", "mean"),
                ("Minimum",           "min"),
                ("Maximum",           "max"),
                ("Median",            "median"),
                ("Anzahl Punkte",     "count"),
                ("Standardabw.",      "std")]:
            self.agg_func_combo.addItem(lbl, val)
        of.addRow("Punktklasse:", self.cls_combo)
        of.addRow("Zellgröße:",   self.cell_spin)
        of.addRow("Aggregation:", self.agg_spin)
        of.addRow("Funktion:",    self.agg_func_combo)
        of.addRow("Threads:",     self.workers_spin)
        of.addRow("",             self.fill_cb)
        of.addRow("",             self.keep_cb)

        out_grp = QGroupBox("Ausgabe-Produkte")
        out_v = QVBoxLayout()
        self.cb_hoehenraster = QCheckBox("Höhenraster (Polygon-GPKG)")
        self.cb_hoehenraster.setChecked(True)
        self.cb_schummerung  = QCheckBox("Schummerung / Hillshade (GeoTIFF)")
        self.cb_schummerung.setChecked(True)
        self.cb_neigung      = QCheckBox("Neigung / Slope (GeoTIFF, Grad)")
        self.cb_neigung.setChecked(False)
        # TIN – zwei Outputs
        self.cb_tin          = QCheckBox("TIN (Triangulated Irregular Network)")
        self.cb_tin.setChecked(False)
        self.cb_tin.setToolTip(
            "Erzeugt zwei GeoTIFFs aus einem TIN:\n"
            "  • _tin_analyse.tif  – roh, ohne Glättung (für Auswertungen)\n"
            "  • _tin_anzeige.tif  – Gauß-geglättet (für Visualisierung)")
        tin_row = QHBoxLayout()
        self.gauss_spin = QSpinBox()
        self.gauss_spin.setRange(1, 15)
        self.gauss_spin.setValue(3)
        self.gauss_spin.setSingleStep(2)   # nur ungerade Werte: 1,3,5,7…
        self.gauss_spin.setSuffix("px Gauß-Kernel")
        self.gauss_spin.setToolTip(
            "Kernel-Größe für die Gauß-Glättung des Anzeige-Rasters:\n"
            "  1 = keine Glättung\n"
            "  3 = leicht (Standard)\n"
            "  5 = stärker\n"
            "  7 = stark (Detailverlust bei kleinen Strukturen)")
        self.cb_tin.toggled.connect(self.gauss_spin.setEnabled)
        self.cb_tin.toggled.connect(self._on_tin_toggled)
        self.gauss_spin.setEnabled(False)
        tin_row.addWidget(self.cb_tin)
        tin_row.addWidget(self.gauss_spin)
        hl_row2 = QHBoxLayout()
        self.cb_hoehenlinien = QCheckBox("Höhenlinien (Vektor-GPKG)")
        self.cb_hoehenlinien.setChecked(True)
        self.equidist_spin   = QDoubleSpinBox()
        self.equidist_spin.setRange(0.1, 20.0); self.equidist_spin.setValue(1.0)
        self.equidist_spin.setSingleStep(0.5); self.equidist_spin.setDecimals(1)
        self.equidist_spin.setSuffix(" m Äquidistanz")
        hl_row2.addWidget(self.cb_hoehenlinien)
        hl_row2.addWidget(self.equidist_spin)
        out_v.addWidget(self.cb_hoehenraster)
        out_v.addWidget(self.cb_schummerung)
        out_v.addWidget(self.cb_neigung)
        out_v.addLayout(hl_row2)
        out_v.addLayout(tin_row)

        # Breaklines – Gewässerlagen für TIN-Verbesserung
        bl_grp = QGroupBox("TIN Breaklines (Gewässer)")
        bl_grp.setToolTip(
            "Verbessert das TIN an stehenden Gewässern und Fließgewässern.\n"
            "Stehende Gewässer: Uferlinie als Constraint, Innenfläche mit\n"
            "  konstantem Höhenwert (hydrostatisch korrekt).\n"
            "Fließgewässer:     Mittellinie als Gefälle-Constraint.")
        bl_lo = QFormLayout(bl_grp)

        # Stehende Gewässer (Polygon-Layer)
        sw_row = QHBoxLayout()
        self.sw_combo = QComboBox()
        self.sw_combo.addItem("— kein Layer —", None)
        self._fill_vector_combo(self.sw_combo, geom_types=["Polygon", "MultiPolygon"])
        sw_row.addWidget(self.sw_combo)
        bl_lo.addRow("Stehende Gewässer (Polygon):", sw_row)

        # Fließgewässer (Linie-Layer)
        fw_row = QHBoxLayout()
        self.fw_combo = QComboBox()
        self.fw_combo.addItem("— kein Layer —", None)
        self._fill_vector_combo(self.fw_combo, geom_types=["LineString", "MultiLineString"])
        fw_row.addWidget(self.fw_combo)
        bl_lo.addRow("Fließgewässer (Linie):", fw_row)

        # Gebäude-Grundrisse (LOD-2)
        bld_row = QHBoxLayout()
        self.bld_combo = QComboBox()
        self.bld_combo.addItem("— keins —", None)
        self.bld_combo.setToolTip(
            "Gebäude-Grundrisse aus LOD-2 / ALKIS als TIN-Constraint.\n"
            "Dachhöhe (measuredHeight) wird auf die LiDAR-Grundhöhe\n"
            "addiert und als feste Constraint-Höhe eingetragen.")
        for lyr in QgsProject.instance().mapLayers().values():
            from qgis.core import QgsVectorLayer as _QVL, QgsWkbTypes as _QWT
            if not isinstance(lyr, _QVL): continue
            if lyr.geometryType() != _QWT.GeometryType.PolygonGeometry: continue
            if any(f.name() in ("measuredHeight","function","gml_id")
                   for f in lyr.fields()):
                self.bld_combo.addItem(lyr.name(), lyr)
        bld_row.addWidget(self.bld_combo)
        bl_lo.addRow("Gebäude LOD-2 (Polygon):", bld_row)

        # Breaklines nur wenn TIN aktiv
        bl_grp.setEnabled(False)
        self.cb_tin.toggled.connect(bl_grp.setEnabled)
        bl_grp.setLayout(bl_lo)
        out_v.addWidget(bl_grp)
        out_grp.setLayout(out_v); lo.addWidget(out_grp)
        og.setLayout(of); lo.addWidget(og)

        # Ausgabe
        outg = QGroupBox("Ausgabe (.gpkg)")
        ov = QHBoxLayout()
        self.out_edit = QLineEdit(); self.out_edit.setPlaceholderText("Pfad …")
        ob = QPushButton("…"); ob.setFixedWidth(30)
        ob.clicked.connect(self._browse)
        ov.addWidget(self.out_edit); ov.addWidget(ob)
        outg.setLayout(ov); lo.addWidget(outg)

        self.log = QTextEdit(); self.log.setReadOnly(True)
        self.log.setFixedHeight(150); lo.addWidget(self.log)
        self.bar = QProgressBar(); self.bar.setVisible(False); lo.addWidget(self.bar)

        bb = QDialogButtonBox()
        self.start_btn = bb.addButton("Download & Verarbeiten",
                                      QDialogButtonBox.ButtonRole.AcceptRole)
        self.stop_btn  = bb.addButton("Abbrechen",
                                      QDialogButtonBox.ButtonRole.RejectRole)
        self.start_btn.clicked.connect(self._start)
        self.stop_btn.clicked.connect(self._abort)
        lo.addWidget(bb)

    def _fill_vector_combo(self, combo, geom_types=None):
        """Befüllt ComboBox mit Vektorlayern des aktuellen Projekts."""
        from qgis.core import QgsVectorLayer
        for lyr in QgsProject.instance().mapLayers().values():
            if not isinstance(lyr, QgsVectorLayer): continue
            if geom_types:
                wkb = lyr.wkbType()
                wkb_name = str(wkb)
                match = any(g.lower() in wkb_name.lower() for g in geom_types)
                # Geometrie-Typ via geometryType()-Enum
                gt = lyr.geometryType()
                if "Polygon" in geom_types and gt == 2: match = True
                if "LineString" in geom_types and gt == 1: match = True
                if not match: continue
            combo.addItem(lyr.name(), lyr)

    def _populate_layer_combo(self):
        self.extent_layer_combo.clear()
        self.extent_layer_combo.addItem("— Layer wählen —", None)
        try:
            from qgis.core import QgsProject
            for lyr in QgsProject.instance().mapLayers().values():
                self.extent_layer_combo.addItem(lyr.name(), lyr)
        except Exception:
            pass

    def _load_layer_extent(self):
        lyr = self.extent_layer_combo.currentData()
        if lyr is None:
            return
        try:
            from qgis.core import (QgsCoordinateTransform,
                                   QgsCoordinateTransformContext)
            ext = lyr.extent()
            tr  = QgsCoordinateTransform(
                lyr.crs(), WGS84, QgsCoordinateTransformContext())
            e   = tr.transformBoundingBox(ext)
            self.lon_min.setValue(max(5.8,  e.xMinimum()))
            self.lat_min.setValue(max(50.2, e.yMinimum()))
            self.lon_max.setValue(min(9.6,  e.xMaximum()))
            self.lat_max.setValue(min(52.6, e.yMaximum()))
            self._update_estimate()
            self._log(f"Ausdehnung von '{lyr.name()}' übernommen.")
            self._build_clip_geometry(lyr)
        except Exception as ex:
            self._log(f"⚠ Layer-Ausdehnung: {ex}")

    def _build_clip_geometry(self, lyr):
        """
        Ermittelt die Abgrenzungs-Geometrie (Vereinigung) in EPSG:25832.
        Wird nur genutzt, wenn 'auf Geometrie zuschneiden' aktiv ist.
        """
        self._clip_wkt = None
        self.clip_lbl.setText("")
        if not self.clip_cb.isChecked() or lyr is None:
            return
        if not isinstance(lyr, QgsVectorLayer):
            self._log("⚠ Zuschnitt: nur Vektorlayer möglich – Ausdehnung wird genutzt.")
            return
        if QgsWkbTypes.geometryType(lyr.wkbType()) != QgsWkbTypes.PolygonGeometry:
            self._log("⚠ Zuschnitt: Layer enthält keine Polygone – "
                      "Ausdehnung wird genutzt.")
            return
        try:
            feats = (lyr.getSelectedFeatures() if self.sel_only_cb.isChecked()
                     else lyr.getFeatures())
            geoms = [f.geometry() for f in feats
                     if f.geometry() and not f.geometry().isEmpty()]
            if not geoms:
                self._log("⚠ Zuschnitt: keine Geometrien gefunden"
                          + (" (Auswahl leer)." if self.sel_only_cb.isChecked() else "."))
                return
            union = QgsGeometry.unaryUnion(geoms)
            if union is None or union.isEmpty():
                self._log("⚠ Zuschnitt: Geometrien konnten nicht vereinigt werden.")
                return
            if lyr.crs() != UTM32:
                tr = QgsCoordinateTransform(lyr.crs(), UTM32,
                                            QgsCoordinateTransformContext())
                union.transform(tr)
            self._clip_wkt = union.asWkt()
            self.clip_lbl.setText(
                "Abgrenzung aktiv: %d Objekt(e) aus „%s“%s"
                % (len(geoms), lyr.name(),
                   " (Auswahl)" if self.sel_only_cb.isChecked() else ""))
            self._log(f"Zuschnitt-Geometrie aus '{lyr.name()}' übernommen "
                      f"({len(geoms)} Objekt(e)).")
        except Exception as ex:
            self._clip_wkt = None
            self._log(f"⚠ Zuschnitt-Geometrie: {ex}")

    def _load_canvas_extent(self):
        """Liest aktuellen Kartenausschnitt (wird auch live nachgeführt)."""
        try:
            from qgis.utils import iface
            ext = iface.mapCanvas().extent()
            crs = iface.mapCanvas().mapSettings().destinationCrs()
            tr  = QgsCoordinateTransform(
                crs, WGS84, QgsCoordinateTransformContext())
            e   = tr.transformBoundingBox(ext)
            self.lon_min.setValue(round(max(5.8,  e.xMinimum()), 6))
            self.lat_min.setValue(round(max(50.2, e.yMinimum()), 6))
            self.lon_max.setValue(round(min(9.6,  e.xMaximum()), 6))
            self.lat_max.setValue(round(min(52.6, e.yMaximum()), 6))
            self._update_estimate()
        except Exception:
            pass

    def _connect_canvas_sync(self):
        """Verbindet Canvas-Signal für Live-Nachführung des Ausschnitts."""
        try:
            from qgis.utils import iface
            iface.mapCanvas().extentsChanged.connect(self._load_canvas_extent)
        except Exception:
            pass

    def _disconnect_canvas_sync(self):
        try:
            from qgis.utils import iface
            iface.mapCanvas().extentsChanged.disconnect(self._load_canvas_extent)
        except Exception:
            pass

    def showEvent(self, event):
        super().showEvent(event)
        self._load_canvas_extent()
        self._connect_canvas_sync()


    def _update_estimate(self):
        try:
            e_min,n_min,e_max,n_max = _wgs84_to_utm32(
                self.lon_min.value(), self.lat_min.value(),
                self.lon_max.value(), self.lat_max.value())
            tiles  = _las_tiles(e_min,n_min,e_max,n_max)
            km2    = ((e_max-e_min)*(n_max-n_min))/1e6
            cells  = int(km2 * 1e6)   # 1 Zelle / m²
            mb_dl  = len(tiles) * 150  # ~150 MB pro LAZ-Kachel
            mb_out = cells * 120 / 1e6  # ~120 Byte/Feature im GPKG
            self.est_lbl.setText(
                f"{len(tiles)} LAZ-Kacheln × ~150 MB ≈ {mb_dl:,} MB Download  |  "
                f"~{cells:,} Zellen  |  GPKG ~{mb_out:.0f} MB"
            )
        except Exception:
            pass

    def _browse(self):
        p,_ = QFileDialog.getSaveFileName(
            self, "GeoPackage", "", "GeoPackage (*.gpkg)")
        if p:
            if not p.endswith(".gpkg"): p += ".gpkg"
            self.out_edit.setText(p)

    def _on_tin_toggled(self, checked: bool):
        """TIN schließt Lücken selbst → IDW-Fill deaktivieren."""
        if checked:
            self.fill_cb.setChecked(False)
            self.fill_cb.setEnabled(False)
        else:
            self.fill_cb.setEnabled(True)

    def _log(self, msg):
        self.log.append(msg)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _start(self):
        if not _REQUESTS_OK: self._log("⚠ requests fehlt"); return
        out = self.out_edit.text().strip()
        if not out: self._log("⚠ Ausgabedatei wählen."); return

        cfg = {
            "output_path":  out,
            "bbox_4326":    (self.lon_min.value(), self.lat_min.value(),
                             self.lon_max.value(), self.lat_max.value()),
            "max_workers":  self.workers_spin.value(),
            "class_filter": self.cls_combo.currentData(),
            "cell_size":    GRID_M,
            "keep_source":  self.keep_cb.isChecked(),
            "cell_size":    self.cell_spin.value(),
            "agg_cell_m":   self.agg_spin.value(),
            "agg_func":     self.agg_func_combo.currentData(),
            "fill_gaps":        self.fill_cb.isChecked(),
            "out_hoehenraster": self.cb_hoehenraster.isChecked(),
            "out_schummerung":  self.cb_schummerung.isChecked(),
            "out_neigung":      self.cb_neigung.isChecked(),
            "out_hoehenlinien": self.cb_hoehenlinien.isChecked(),
            "equidistanz":      self.equidist_spin.value(),
            "out_tin":          self.cb_tin.isChecked(),
            "tin_gauss_kernel": self.gauss_spin.value(),
            "tin_sw_layer":     self.sw_combo.currentData(),   # stehende Gewässer
            "tin_fw_layer":     self.fw_combo.currentData(),   # Fließgewässer
            "tin_bld_layer":    self.bld_combo.currentData(),  # Gebäude LOD-2
            "clip_wkt":         getattr(self, "_clip_wkt", None),
        }
        self.start_btn.setEnabled(False)
        self.bar.setRange(0,100); self.bar.setValue(0); self.bar.setVisible(True)
        self._worker = _LidarWorker(cfg, parent=self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _abort(self):
        if self._worker and self._worker.isRunning():
            self._worker.abort()
            # Worker erst beenden lassen bevor Dialog schließt
            # (sonst QGIS-Crash wegen dangling C++ Qt-Objekt)
            self._worker.finished.connect(self._on_abort_done)
            self.start_btn.setEnabled(False)
            self._log("Breche ab – warte auf Worker …")
        else:
            self.reject()

    def _on_abort_done(self, *_):
        """Wird aufgerufen wenn Worker nach Abbruch fertig ist."""
        self.reject()

    def closeEvent(self, event):
        self._disconnect_canvas_sync()
        """Verhindert Crash wenn Dialog während laufendem Worker geschlossen wird."""
        if self._worker and self._worker.isRunning():
            self._worker.abort()
            self._worker.wait(3000)  # max. 3 Sekunden warten
        event.accept()

    def _on_progress(self, pct, msg):
        if pct >= 0: self.bar.setValue(pct)
        self._log(msg)

    def _on_finished(self, ok, msg):
        self._log(msg)
        self.bar.setValue(100 if ok else 0)
        self.start_btn.setEnabled(True)
        if ok and self._worker:
            cfg     = self._worker.config
            out     = cfg.get("output_path", "")
            base    = out.replace(".gpkg", "")
            # Höhenraster GPKG laden
            if cfg.get("out_hoehenraster", True) and os.path.exists(out):
                from qgis.core import QgsVectorLayer, QgsProject
                lyr = QgsVectorLayer(
                    f"{out}|layername=hoehenraster_1m",
                    "Höhenraster 1m (LiDAR)", "ogr")
                if lyr.isValid():
                    QgsProject.instance().addMapLayer(lyr)
                    self._log("✓ Höhenraster in QGIS geladen")
            # GeoTIFFs laden
            from qgis.core import QgsRasterLayer, QgsProject
            for suffix, name in [
                ("_dtm.tif",          "DTM COG (LiDAR)"),
                ("_schummerung.tif",  "Schummerung (LiDAR)"),
                ("_neigung.tif",      "Neigung ° (LiDAR)"),
            ]:
                p = base + suffix
                if os.path.exists(p):
                    lyr = QgsRasterLayer(p, name, "gdal")
                    if lyr.isValid():
                        QgsProject.instance().addMapLayer(lyr)
                        self._log(f"✓ {name} in QGIS geladen")
            # Höhenlinien GPKG laden
            hl = base + "_hoehenlinien.gpkg"
            if os.path.exists(hl):
                from qgis.core import QgsVectorLayer, QgsProject
                eq  = cfg.get("equidistanz", 1.0)
                lyr = QgsVectorLayer(
                    f"{hl}|layername=hoehenlinien",
                    f"Höhenlinien {eq}m (LiDAR)", "ogr")
                if lyr.isValid():
                    QgsProject.instance().addMapLayer(lyr)
                    self._log("✓ Höhenlinien in QGIS geladen")

