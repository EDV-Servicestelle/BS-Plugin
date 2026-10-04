"""
nrw_luftbild_dialog.py - LuftbildDialog
==========================================
Reine UI-Schicht.
Algorithmen: core/luftbild.py | Worker: workers/luftbild_worker.py
"""
import os
import re

# requests ist in manchen QGIS-Installationen nicht vorhanden; die
# Aufrufstellen pruefen vorher _REQUESTS_OK aus core.luftbild.
try:
    import requests
except ImportError:
    requests = None
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QGroupBox, QDialogButtonBox,
    QProgressBar, QTextEdit, QDoubleSpinBox, QSpinBox,
    QFileDialog, QLineEdit, QCheckBox, QComboBox,
)
from qgis.core import (
    QgsProject, QgsCoordinateReferenceSystem,
    QgsCoordinateTransform, QgsCoordinateTransformContext,
    QgsVectorLayer, QgsWkbTypes,
)

WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")
UTM32 = QgsCoordinateReferenceSystem("EPSG:25832")

from .core.luftbild import (WCS_URL, DEFAULT_ZOOMS, _REQUESTS_OK, WGS84, UTM32,
                             _GDAL_OK, _discover_coverage, _wgs84_to_utm32,
                             _blocks)
from .workers.luftbild_worker import _WcsWorker

class LuftbildDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("FT – NRW Luftbild → COG GeoTIFF (EPSG:25832)")
        self.setMinimumWidth(520)
        self._worker = None
        self._build_ui()
        self._load_canvas_extent()
        if not _GDAL_OK:
            self._log("⚠ GDAL nicht gefunden – Plugin aus QGIS/OSGeo4W starten.")
        if not _REQUESTS_OK:
            self._log("⚠ requests fehlt: pip install requests")

    def _build_ui(self):
        lo = QVBoxLayout(self)

        # Info + Coverages-Check
        hdr = QHBoxLayout()
        hdr.addWidget(QLabel(f"WCS: {WCS_URL}"))
        caps_btn = QPushButton("Coverages prüfen")
        caps_btn.setFixedWidth(145)
        caps_btn.clicked.connect(self._check_coverages)
        hdr.addWidget(caps_btn)
        lo.addLayout(hdr)

        # Bereich
        bg = QGroupBox("Bereich (WGS84)"); bf = QFormLayout()
        def dbl(v,lo_,hi_):
            sb=QDoubleSpinBox(); sb.setDecimals(6)
            sb.setRange(lo_,hi_); sb.setValue(v); sb.setSingleStep(0.01)
            return sb
        self.lon_min=dbl(6.0, 5.8,9.6);  self.lat_min=dbl(50.3,50.2,52.6)
        self.lon_max=dbl(7.2, 5.8,9.6);  self.lat_max=dbl(51.4,50.2,52.6)
        bf.addRow("Lon min:", self.lon_min); bf.addRow("Lat min:", self.lat_min)
        bf.addRow("Lon max:", self.lon_max); bf.addRow("Lat max:", self.lat_max)
        cb_btn=QPushButton("Aus Kartenausschnitt")
        cb_btn.clicked.connect(self._load_canvas_extent)
        bf.addRow("",cb_btn)
        lyr_row=QHBoxLayout()
        self.extent_layer_combo=QComboBox()
        self._populate_layer_combo()
        lyr_btn=QPushButton("Aus Layer"); lyr_btn.setFixedWidth(80)
        lyr_btn.clicked.connect(self._load_layer_extent)
        lyr_row.addWidget(self.extent_layer_combo); lyr_row.addWidget(lyr_btn)
        bf.addRow("",lyr_row)
        bg.setLayout(bf); lo.addWidget(bg)

        # Auflösungsinfo (COG hat keine Zoom-Stufen)
        zg=QGroupBox("Ausgabe-Auflösung"); zv=QVBoxLayout()
        zv.addWidget(QLabel(
            "COG GeoTIFF – Auflösung bestimmt durch WCS-Block-Größe (px/Block).\n"
            "Standard: 2000 px / 2 km = 100 cm/Pixel (NRW DOP)."))
        # COG hat keine Zoom-Stufen – Auflösung kommt vom WCS-Block
        self.est_lbl=QLabel(""); self.est_lbl.setStyleSheet("color:gray;font-size:11px;")
        zv.addWidget(self.est_lbl); zg.setLayout(zv); lo.addWidget(zg)
        for sb in [self.lon_min,self.lat_min,self.lon_max,self.lat_max]:
            sb.valueChanged.connect(self._update_estimate)
        self._update_estimate()

        # Optionen
        og=QGroupBox("Einstellungen"); of=QFormLayout()
        self.workers_spin=QSpinBox(); self.workers_spin.setRange(1,8)
        self.workers_spin.setValue(4); self.workers_spin.setSuffix(" Threads")
        self.quality_spin=QSpinBox(); self.quality_spin.setRange(50,95)
        self.quality_spin.setValue(75)
        self.quality_spin.setSuffix(" JPEG-Qualität (75 = guter Kompromiss)")
        self.quality_spin.setToolTip(
            "50 = kleinste Datei (~30 MB/6 km²), sichtbare Kompressionsartefakte\n"
            "75 = guter Kompromiss (Standard)\n"
            "85 = gute Qualität\n"
            "95 = maximale Qualität (~400 MB/6 km²)")
        self.res_spin = QSpinBox()
        self.res_spin.setRange(512, 2048)
        self.res_spin.setValue(2000)
        self.res_spin.setSingleStep(256)
        self.res_spin.setSuffix(" px/Block (max. WCS-Limit)")
        self.res_spin.setToolTip(
            "Pixel pro 1×1 km Block.\n"
            "2000 px = ~100 cm/Pixel (bei 2km-Block)\n"
            "1024 px = ~98 cm/Pixel (schneller, kleinere Datei)\n"
            "Bei WCS-Fehler 'raster size out of range': Wert reduzieren.")
        self.keep_cb=QCheckBox("Temp-Dateien behalten (Debug)")
        of.addRow("Auflösung:", self.res_spin)
        of.addRow("Threads:",   self.workers_spin)
        of.addRow("Qualität:",  self.quality_spin)
        of.addRow("",           self.keep_cb)
        og.setLayout(of); lo.addWidget(og)

        # Ausgabe
        outg=QGroupBox("Ausgabe – COG GeoTIFF (.tif, EPSG:25832)"); ov=QHBoxLayout()
        self.out_edit=QLineEdit(); self.out_edit.setPlaceholderText("Pfad zur .tif-Datei …")
        ob=QPushButton("…"); ob.setFixedWidth(30)
        ob.clicked.connect(self._browse)
        ov.addWidget(self.out_edit); ov.addWidget(ob)
        outg.setLayout(ov); lo.addWidget(outg)

        self.log=QTextEdit(); self.log.setReadOnly(True); self.log.setFixedHeight(150)
        lo.addWidget(self.log)
        self.bar=QProgressBar(); self.bar.setVisible(False); lo.addWidget(self.bar)

        bb=QDialogButtonBox()
        self.start_btn=bb.addButton("Download & Konvertieren",
                                    QDialogButtonBox.ButtonRole.AcceptRole)
        self.stop_btn =bb.addButton("Abbrechen",
                                    QDialogButtonBox.ButtonRole.RejectRole)
        self.start_btn.clicked.connect(self._start)
        self.stop_btn.clicked.connect(self._abort)
        lo.addWidget(bb)

    def _check_coverages(self):
        """Fragt GetCapabilities ab und zeigt verfügbare Coverages."""
        if not _REQUESTS_OK:
            self._log("⚠ requests nicht verfügbar."); return
        self._log("Frage GetCapabilities ab …")
        try:
            r = requests.get(WCS_URL, params={
                "SERVICE":"WCS","VERSION":"1.0.0","REQUEST":"GetCapabilities"
            }, timeout=20)
            if r.status_code == 200:
                names = re.findall(r'<Name>([^<]+)</Name>', r.text)
                names += re.findall(r'<Identifier>([^<]+)</Identifier>', r.text)
                names = list(dict.fromkeys(n.strip() for n in names))
                dop = [n for n in names
                       if any(k in n.lower()
                              for k in ('dop','rgb','luft','ortho'))]
                if dop:
                    self._log(f"  DOP-Coverages: {dop}")
                self._log(f"  Alle ({len(names)}): {', '.join(names[:15])}")
            else:
                self._log(f"  HTTP {r.status_code}")
        except Exception as ex:
            self._log(f"  ⚠ {ex}")

    def _populate_layer_combo(self):
        self.extent_layer_combo.clear()
        self.extent_layer_combo.addItem("— Layer wählen —", None)
        try:
            for lyr in QgsProject.instance().mapLayers().values():
                self.extent_layer_combo.addItem(lyr.name(), lyr)
        except Exception:
            pass

    def _load_layer_extent(self):
        lyr = self.extent_layer_combo.currentData()
        if lyr is None: return
        try:
            tr = QgsCoordinateTransform(
                lyr.crs(), WGS84, QgsCoordinateTransformContext())
            e = tr.transformBoundingBox(lyr.extent())
            self.lon_min.setValue(max(5.8,  e.xMinimum()))
            self.lat_min.setValue(max(50.2, e.yMinimum()))
            self.lon_max.setValue(min(9.6,  e.xMaximum()))
            self.lat_max.setValue(min(52.6, e.yMaximum()))
            self._update_estimate()
        except Exception as ex:
            self._log(f"⚠ {ex}")

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
            e_min,n_min,e_max,n_max=_wgs84_to_utm32(
                self.lon_min.value(),self.lat_min.value(),
                self.lon_max.value(),self.lat_max.value())
            blks=_blocks(e_min,n_min,e_max,n_max)
            km2=((e_max-e_min)*(n_max-n_min))/1e6
            self.est_lbl.setText(
                f"{len(blks)} WCS-Blöcke (1×1 km)"
                f"  |  ~{len(blks)*5:.0f} MB Download"
                f"  |  ~{km2:.1f} km²")
        except Exception:
            pass

    def _browse(self):
        p,_=QFileDialog.getSaveFileName(
            self,"COG GeoTIFF speichern","","GeoTIFF (*.tif)")
        if p:
            if not p.endswith(".tif"): p+=".tif"
            self.out_edit.setText(p)

    def _log(self,msg):
        self.log.append(msg)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _start(self):
        if not _REQUESTS_OK: self._log("⚠ requests fehlt"); return
        if not _GDAL_OK:     self._log("⚠ GDAL fehlt"); return
        out=self.out_edit.text().strip()
        if not out: self._log("⚠ Ausgabedatei wählen."); return
        cfg={
            "output_path":  out,
            "bbox_4326":    (self.lon_min.value(),self.lat_min.value(),
                             self.lon_max.value(),self.lat_max.value()),
            "max_workers":  self.workers_spin.value(),
            "jpeg_quality": self.quality_spin.value(),
            "keep_source":  self.keep_cb.isChecked(),
            "block_px":     self.res_spin.value(),
            "timeout":      90,
        }
        self.start_btn.setEnabled(False)
        self.bar.setRange(0,100); self.bar.setValue(0); self.bar.setVisible(True)
        self._worker=_WcsWorker(cfg,parent=self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _abort(self):
        if self._worker and self._worker.isRunning():
            self._worker.abort()
            self._worker.finished.connect(self._on_abort_done)
            self._log("Breche ab …")
        else:
            self.reject()

    def _on_abort_done(self, *_):
        self.reject()

    def closeEvent(self, event):
        self._disconnect_canvas_sync()
        if self._worker and self._worker.isRunning():
            self._worker.abort()
            self._worker.wait(3000)
        event.accept()

    def _on_progress(self,pct,msg):
        if pct>=0: self.bar.setValue(pct)
        self._log(msg)

    def _on_finished(self,ok,msg):
        self._log(msg); self.bar.setValue(100 if ok else 0)
        self.start_btn.setEnabled(True)

