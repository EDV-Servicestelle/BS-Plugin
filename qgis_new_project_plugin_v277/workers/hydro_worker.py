"""
workers/hydro_worker.py - HydroWorker QThread
=============================================
Verbindet core.hydro-Algorithmen mit Qt-Signalen.
Laeuft in eigenem Thread, sendet progress/finished.
"""
from qgis.PyQt.QtCore import QThread, pyqtSignal
from osgeo import gdal, osr, ogr
gdal.UseExceptions()
from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer
try:
    from qgis_new_project_plugin.core.hydro import (fill_sinks, flow_direction_d8, flow_accumulation, detect_sinks, extract_streams, strahler_order, _write_cog, _streams_to_gpkg, _sinks_to_gpkg, _load, _load_vector, _ACCEL, _GDAL_OK)
except ImportError:
    from ..core.hydro import (fill_sinks, flow_direction_d8, flow_accumulation, detect_sinks, extract_streams, strahler_order, _write_cog, _streams_to_gpkg, _sinks_to_gpkg, _load, _load_vector, _ACCEL, _GDAL_OK)
# noop — *  # alle Kernfunktionen
import os
import numpy as np

class _HydroWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._abort = False

    def abort(self): self._abort = True

    def run(self):
        try:
            self._process()
        except Exception as e:
            import traceback
            self.finished.emit(False,
                f"✗ {e}\n{traceback.format_exc()[:700]}")

    def _process(self):
        cfg      = self.config
        dtm_path = cfg["dtm_path"]
        out_dir  = cfg["out_dir"]
        base     = os.path.join(out_dir, cfg.get("name", "hydro"))
        thresh   = cfg.get("acc_threshold", 1000)
        min_sink = cfg.get("min_sink_depth", 0.05)
        min_area = cfg.get("min_sink_area",  100)

        def log(pct, msg):
            self.progress.emit(pct, msg)
            if self._abort:
                raise RuntimeError("Abgebrochen.")

        log(0, f"Beschleunigung: {_ACCEL}")
        if _ACCEL == "numpy":
            log(-1,
                "  Tipp: pip install richdem   → 20–100× schneller\n"
                "        pip install pysheds   → 5–30× schneller\n"
                "        pip install numba     → 10–50× schneller (inkl. GPU)")
        log(2, "Lese DTM …")
        if not _GDAL_OK:
            self.finished.emit(False, "GDAL nicht verfügbar."); return

        ds = gdal.Open(dtm_path)
        if ds is None:
            self.finished.emit(False, f"DTM nicht lesbar: {dtm_path}"); return

        gt       = ds.GetGeoTransform()
        srs_wkt  = ds.GetProjection()
        cell_m   = abs(gt[1])
        band     = ds.GetRasterBand(1)
        nodata   = band.GetNoDataValue() or -9999.0
        dem_raw  = band.ReadAsArray().astype(np.float32)
        ds       = None
        log(5, f"  DTM: {dem_raw.shape[1]}×{dem_raw.shape[0]} Zellen, {cell_m:.2f} m/Px")

        # ── 1. Senken füllen ───────────────────────────────────────────────────
        log(10, "Fülle Senken (Priority-Flood) …")
        dem_filled = fill_sinks(dem_raw, nodata)
        log(25, f"  ✓ DEM gefüllt ({_ACCEL})")

        # ── 1b. Gefülltes DEM exportieren (optional) ───────────────────────────
        if cfg.get("out_fill_dem", False):
            p = base + "_dem_gefuellt.tif"
            _write_cog(p, dem_filled, gt, srs_wkt, nodata=nodata)
            log(-1, f"  ✓ Gefülltes DEM COG → {p}")
            _load(p, "DEM gefüllt (Fill Sinks)")

        # ── 2. Abflusssenken erkennen ──────────────────────────────────────────
        if cfg.get("out_sinks", True):
            log(28, "Erkenne Abflusssenken …")
            sinks = detect_sinks(dem_raw, dem_filled, nodata, min_sink)
            n_sinks = (sinks > 0).sum()
            log(30, f"  {n_sinks:,} Senkenzellen (≥ {min_sink} m Tiefe)")
            if cfg.get("out_sinks_raster", True):
                p = base + "_senken.tif"
                _write_cog(p, sinks, gt, srs_wkt, nodata=0.0)
                log(-1, f"  ✓ Senken-COG → {p}")
                _load(p, "Abflusssenken (Tiefe m)")
            if cfg.get("out_sinks_vector", True):
                p = base + "_senken.gpkg"
                _sinks_to_gpkg(sinks, gt, srs_wkt, p, min_area)
                log(-1, f"  ✓ Senkenflächen → {p}")
                _load_vector(p, "senken", "Abflusssenken")

        # ── 3. Abflussrichtung D8 ──────────────────────────────────────────────
        log(35, "Berechne Abflussrichtung (D8) …")
        fdir = flow_direction_d8(dem_filled, cell_m, nodata)
        if cfg.get("out_fdir", True):
            p = base + "_fliessrichtung.tif"
            _write_cog(p, fdir.astype(np.int16), gt, srs_wkt, nodata=0)
            log(-1, f"  ✓ Fließrichtung COG → {p}")
            _load(p, "Fließrichtung D8")
        log(45, "  ✓ Abflussrichtung berechnet")

        # ── 4. Abflussakkumulation ─────────────────────────────────────────────
        log(48, "Berechne Abflussakkumulation …")
        acc = flow_accumulation(fdir)
        if cfg.get("out_acc", True):
            p = base + "_akkumulation.tif"
            _write_cog(p, np.log1p(acc).astype(np.float32), gt, srs_wkt)
            log(-1, f"  ✓ Akkumulation (log) COG → {p}")
            _load(p, "Abflussakkumulation (log)")
        log(65, "  ✓ Akkumulation berechnet")

        # ── 5. Gewässernetz ────────────────────────────────────────────────────
        log(68, f"Extrahiere Gewässernetz (Schwelle: {thresh} Zellen) …")
        streams = extract_streams(acc, thresh)
        n_stream = streams.sum()
        log(72, f"  {n_stream:,} Gewässerzellen")

        # ── 6. Strahler-Ordnung ────────────────────────────────────────────────
        log(75, "Berechne Strahler-Ordnung …")
        order = strahler_order(streams, fdir)
        max_order = int(order.max())
        log(82, f"  Max. Strahler-Ordnung: {max_order}")

        if cfg.get("out_streams_raster", True):
            p = base + "_gewaessernetz.tif"
            _write_cog(p, order.astype(np.int16), gt, srs_wkt, nodata=0)
            log(-1, f"  ✓ Strahler-Ordnung COG → {p}")
            _load(p, "Strahler-Ordnung")

        if cfg.get("out_streams_vector", True):
            log(85, "Vektorisiere Gewässernetz …")
            p = base + "_gewaessernetz.gpkg"
            _streams_to_gpkg(streams, order, fdir, gt, srs_wkt, p)
            log(-1, f"  ✓ Gewässernetz Vektor → {p}")
            _load_vector(p, "gewaessernetz", "Gewässernetz (Strahler)")

        log(100, "")
        self.finished.emit(True,
            f"✓ Hydroanalyse abgeschlossen → {out_dir}")


def _load(path, name):
    try:
        from qgis.core import QgsRasterLayer, QgsProject
        lyr = QgsRasterLayer(path, name, "gdal")
        if lyr.isValid():
            QgsProject.instance().addMapLayer(lyr)
    except Exception:
        pass


def _load_vector(path, layername, name):
    try:
        from qgis.core import QgsVectorLayer, QgsProject
        lyr = QgsVectorLayer(f"{path}|layername={layername}", name, "ogr")
        if lyr.isValid():
            QgsProject.instance().addMapLayer(lyr)
    except Exception:
        pass


# ── Dialog ────────────────────────────────────────────────────────────────────
