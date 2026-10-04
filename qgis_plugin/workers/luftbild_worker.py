"""
workers/luftbild_worker.py - WcsWorker QThread
===============================================
Koordiniert WCS-Bloecke, Georeferenzierung und COG-Erstellung.
"""
from qgis.PyQt.QtCore import QThread, pyqtSignal
from osgeo import gdal, osr, ogr
gdal.UseExceptions()
from qgis.core import (
    QgsProject, QgsRasterLayer,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform, QgsCoordinateTransformContext, QgsPointXY,
)
from concurrent.futures import ThreadPoolExecutor, as_completed
import os, tempfile, shutil
import requests

try:
    from qgis_new_project_plugin.core.luftbild import (WGS84, UTM32, WCS_URL, WCS_COVERAGE_CANDIDATES, BLOCK_M, BLOCK_PX, _REQUESTS_OK, _GDAL_OK, _blocks, _wgs84_to_utm32, _discover_coverage, _parse_wcs_error, _fetch_wcs_block, _georeference_block)
except ImportError:
    from ..core.luftbild import (WGS84, UTM32, WCS_URL, WCS_COVERAGE_CANDIDATES, BLOCK_M, BLOCK_PX, _REQUESTS_OK, _GDAL_OK, _blocks, _wgs84_to_utm32, _discover_coverage, _parse_wcs_error, _fetch_wcs_block, _georeference_block)
# noop — *

class _WcsWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._abort = False

    def abort(self): self._abort = True

    def run(self):
        tmp = tempfile.mkdtemp(prefix="nrw_wcs_")
        try:
            self._process(tmp)
        except Exception as e:
            import traceback
            self.finished.emit(False, f"✗ {e}\n{traceback.format_exc()[:600]}")
        finally:
            if not self.config.get("keep_source", False):
                shutil.rmtree(tmp, ignore_errors=True)
                self.progress.emit(-1, "  Temp-Dateien gelöscht.")

    def _process(self, tmp):
        cfg     = self.config
        out     = cfg["output_path"]
        workers = cfg.get("max_workers", 4)
        quality = cfg.get("jpeg_quality", 85)
        bwgs    = cfg["bbox_4326"]

        # Coverage automatisch ermitteln
        self.progress.emit(1, "  Ermittle Coverage-Namen …")
        coverage, wcs_format = _discover_coverage(cfg.get("wcs_url", WCS_URL))
        self.progress.emit(2, f"  Coverage: {coverage}  Format: {wcs_format}")

        e_min, n_min, e_max, n_max = _wgs84_to_utm32(*bwgs)
        blks = _blocks(e_min, n_min, e_max, n_max)

        self.progress.emit(3,
            f"  AOI: {(e_max-e_min)/1000:.1f}×{(n_max-n_min)/1000:.1f} km"
            f"  → {len(blks)} WCS-Blöcke")

        # Download
        downloaded = []
        n_err = 0
        self.progress.emit(5, f"Lade {len(blks)} WCS-Blöcke …")

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {
                pool.submit(_fetch_wcs_block,
                            e0, n0, e1, n1, tmp, coverage, wcs_format,
                            px=cfg.get("block_px", BLOCK_PX),
                            timeout=cfg.get("timeout", 90)): (e0,n0)
                for e0,n0,e1,n1 in blks
            }
            done = 0
            for fut in as_completed(futs):
                if self._abort:
                    self.finished.emit(False,"Abgebrochen."); return
                done += 1
                path, err = fut.result()
                if path:
                    downloaded.append(path)
                else:
                    n_err += 1
                    if n_err <= 3:
                        self.progress.emit(-1, f"  ⚠ {err}")
                    elif n_err == 4:
                        self.progress.emit(-1, "  (weitere Fehler werden nicht angezeigt)")
                if done % max(1, len(blks)//20) == 0 or done == len(blks):
                    pct = int(5 + done/len(blks)*40)
                    self.progress.emit(pct,
                        f"  {done}/{len(blks)} Blöcke"
                        + (f"  ✗ {n_err} Fehler" if n_err else " ✓"))

        if not downloaded:
            self.finished.emit(False,
                f"Keine WCS-Daten erhalten (Coverage: {coverage}).\n"
                "→ 'Coverages prüfen' zeigt verfügbare Namen.\n"
                f"→ URL: {WCS_URL}?SERVICE=WCS&REQUEST=GetCapabilities")
            return

        self.progress.emit(46,
            f"  {len(downloaded)}/{len(blks)} Blöcke OK")

        if not _GDAL_OK:
            self.finished.emit(False,
                "GDAL (osgeo) fehlt – Plugin aus QGIS/OSGeo4W starten.")
            return

        # GDAL
        self.progress.emit(48, "GDAL: Mosaik …")
        vrt   = os.path.join(tmp, "mosaic.vrt")
        w25832 = os.path.join(tmp, "mosaic_25832.tif")
        # Nur georeferenzierte Dateien verwenden
        geo_files = [f for f in downloaded if f.endswith(".tif")]
        if not geo_files:
            geo_files = downloaded   # Fallback: alle
        self.progress.emit(48,
            f"  {len(geo_files)} georef. Dateien für Mosaik")
        # WCS liefert UTM32N → VRT behält Ursprungs-CRS (EPSG:25832)
        ds_vrt = gdal.BuildVRT(vrt, geo_files, resampleAlg="bilinear")
        if ds_vrt is None:
            self.finished.emit(False,
                f"GDAL BuildVRT fehlgeschlagen.\n"
                f"Dateien: {geo_files[:3]}")
            return
        ds_vrt.FlushCache(); ds_vrt = None

        self.progress.emit(58, "GDAL: Reprojiziere → EPSG:25832 (UTM32N/ETRS89) …")
        # OpenCL-Beschleunigung aktivieren falls verfügbar (NVIDIA/AMD/Intel GPU)
        gdal.SetConfigOption("GDAL_USE_OVR_RESAMPLING_FACTOR", "YES")
        gdal.SetConfigOption("GDAL_NUM_THREADS", "ALL_CPUS")
        n_cpu = str(__import__("os").cpu_count() or 4)
        gdal.Warp(w25832, vrt, dstSRS="EPSG:25832",
                  resampleAlg="bilinear", format="GTiff",
                  warpOptions=["NUM_THREADS=ALL_CPUS"],
                  multithread=True,
                  creationOptions=[
                      "COMPRESS=JPEG", f"JPEG_QUALITY={quality}",
                      "TILED=YES","BLOCKXSIZE=512","BLOCKYSIZE=512",
                      f"NUM_THREADS={n_cpu}","BIGTIFF=YES"])
        gdal.SetConfigOption("GDAL_NUM_THREADS", None)

        self.progress.emit(70, "GDAL: COG GeoTIFF erstellen …")
        # COG – EPSG:25832 (ETRS89/UTM32N)
        # Quelle: https://docs.qfield.org/reference/data-format/
        self.progress.emit(70, "GDAL: COG erstellen (EPSG:25832) …")
        gdal.Translate(
            out, w25832,
            format="COG",
            creationOptions=[
                "BLOCKSIZE=512",
                "COMPRESS=JPEG",
                f"QUALITY={quality}",
                "OVERVIEW_RESAMPLING=BILINEAR",
                "NUM_THREADS=ALL_CPUS",
                "BIGTIFF=YES",
            ],
        )
        size = os.path.getsize(out)/1_048_576
        self.progress.emit(100, f"✓ Fertig: {size:.1f} MB")
        self.finished.emit(True, f"✓ COG GeoTIFF: {size:.1f} MB → {out}")
        try:
            from qgis.core import QgsRasterLayer
            lyr = QgsRasterLayer(out, "NRW Luftbild COG", "gdal")
            if lyr.isValid():
                QgsProject.instance().addMapLayer(lyr)
                self.progress.emit(-1,"✓ Layer in QGIS geladen.")
        except Exception:
            pass


# ── Dialog ────────────────────────────────────────────────────────────────────

