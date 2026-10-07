"""
workers/lidar_worker.py - LidarWorker QThread
===============================================
Koordiniert Download, Verarbeitung und Ausgabe.
"""
from qgis.PyQt.QtCore import QThread, pyqtSignal
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsRasterLayer,
    QgsVectorFileWriter, QgsFields, QgsField, QgsFeature,
    QgsGeometry, QgsWkbTypes, QgsCoordinateReferenceSystem,
    QgsCoordinateTransform, QgsCoordinateTransformContext, QgsPointXY,
)
from qgis.PyQt.QtCore import QVariant
from concurrent.futures import ThreadPoolExecutor, as_completed
import os, tempfile, shutil, math
import numpy as np
try:
    import requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

try:
    from qgis_new_project_plugin.core.lidar import (CLASS_GROUND, GRID_M, LAS_TILE_M, LAS_URL, WGS84, UTM32, _LASPY_OK, _GDAL_OK, _QGIS_OK, _wgs84_to_utm32, _las_tiles, _read_las_points, _points_to_grid, _clip_grid_to_wkt, _fill_gaps, _aggregate_grid, _grid_to_features, _grid_to_features_numpy, _derive_products,
    _NUMPY_OK, _PDAL_OK)
except ImportError:
    from ..core.lidar import (CLASS_GROUND, GRID_M, LAS_TILE_M, LAS_URL, WGS84, UTM32, _LASPY_OK, _GDAL_OK, _QGIS_OK, _wgs84_to_utm32, _las_tiles, _read_las_points, _points_to_grid, _clip_grid_to_wkt, _fill_gaps, _aggregate_grid, _grid_to_features, _grid_to_features_numpy, _derive_products,
    _NUMPY_OK, _PDAL_OK)
# noop — *  # alle Core-Funktionen importieren

class _LidarWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        tmp = tempfile.mkdtemp(prefix="nrw_lidar_")
        try:
            self._process(tmp)
        except Exception as e:
            import traceback
            self.finished.emit(False,
                f"✗ {e}\n{traceback.format_exc()[:800]}")
        finally:
            if not self.config.get("keep_source", False):
                shutil.rmtree(tmp, ignore_errors=True)
                self.progress.emit(-1, "  Temp-Dateien gelöscht.")

    def _process(self, tmp):
        cfg        = self.config
        out_path   = cfg["output_path"]
        bwgs       = cfg["bbox_4326"]
        workers    = cfg.get("max_workers", 4)
        cls_filter = cfg.get("class_filter", CLASS_GROUND)
        cell_m     = cfg.get("cell_size", GRID_M)

        lon_min, lat_min, lon_max, lat_max = bwgs
        e_min, n_min, e_max, n_max = _wgs84_to_utm32(*bwgs)

        tiles = _las_tiles(e_min, n_min, e_max, n_max)
        self.progress.emit(2,
            f"AOI: {e_min:.0f}–{e_max:.0f} E, {n_min:.0f}–{n_max:.0f} N")
        self.progress.emit(2, f"  {len(tiles)} LAS-Kacheln (1×1 km)")

        if not tiles:
            self.finished.emit(False, "Keine Kacheln im Bereich."); return

        # ── Download ──────────────────────────────────────────────────────────
        downloaded = []
        n_err      = 0

        def fetch(tile):
            ekm, nkm = tile
            url  = LAS_URL.format(e=ekm, n=nkm)
            path = os.path.join(tmp, f"las_{ekm}_{nkm}.laz")
            try:
                r = requests.get(url, timeout=180, stream=True)
                if r.status_code != 200:
                    return None, f"{ekm}/{nkm}: HTTP {r.status_code}"
                with open(path, "wb") as f:
                    for chunk in r.iter_content(65536):
                        f.write(chunk)
                return path, None
            except Exception as ex:
                return None, f"{ekm}/{nkm}: {ex}"

        self.progress.emit(5, f"Lade {len(tiles)} LAS/LAZ-Dateien …")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(fetch, t): t for t in tiles}
            done = 0
            for fut in as_completed(futs):
                if self._abort:
                    self.finished.emit(False, "Abgebrochen."); return
                done += 1
                path, err = fut.result()
                if path:
                    downloaded.append(path)
                else:
                    n_err += 1
                    if n_err <= 5:
                        self.progress.emit(-1, f"  ⚠ {err}")
                if done % 3 == 0 or done == len(tiles):
                    pct = int(5 + done/len(tiles)*35)
                    self.progress.emit(pct,
                        f"  {done}/{len(tiles)} Dateien"
                        + (f"  ✗ {n_err} Fehler" if n_err else ""))

        if not downloaded:
            self.finished.emit(False,
                "Keine LAS/LAZ-Dateien heruntergeladen."); return

        self.progress.emit(42, f"  {len(downloaded)} Dateien OK")

        # ── Punkte lesen + Raster berechnen ───────────────────────────────────
        cls_name = "Boden (Kl. 2)" if cls_filter == CLASS_GROUND else "alle"
        self.progress.emit(45,
            f"Lese Punktwolke ({cls_name}) …")

        all_grid = {}
        n_files  = len(downloaded)
        for fi, las_path in enumerate(downloaded):
            if self._abort:
                self.finished.emit(False, "Abgebrochen."); return
            try:
                pts = _read_las_points(las_path, cls_filter)
                if pts.shape[0] == 0:
                    self.progress.emit(-1,
                        f"  ⚠ {os.path.basename(las_path)}: keine Punkte"
                        " (Klassifizierungsfilter prüfen)")
                    continue

                tile_grid = _points_to_grid(pts, e_min, n_min,
                                             e_max, n_max, cell_m)
                # Grid zusammenführen
                for key, zvals in tile_grid.items():
                    if key in all_grid:
                        all_grid[key].extend(zvals)
                    else:
                        all_grid[key] = zvals

                n_pts = pts.shape[0]
                pct   = int(45 + (fi+1)/n_files * 30)
                self.progress.emit(pct,
                    f"  {fi+1}/{n_files}: {os.path.basename(las_path)}"
                    f"  {n_pts:,} Punkte → {len(tile_grid)} Zellen")
            except Exception as e:
                self.progress.emit(-1,
                    f"  ⚠ {os.path.basename(las_path)}: {e}")

        if not all_grid:
            self.finished.emit(False,
                "Keine Rasterzellen erzeugt – "
                "Klassifizierung oder Bereich prüfen.")
            return

        self.progress.emit(76,
            f"  {len(all_grid):,} Rasterzellen (1×1 m) berechnet")

        # ── Zuschnitt auf gewählte Abgrenzung (Layer-Geometrie) ──────────
        clip_wkt = cfg.get("clip_wkt")
        if clip_wkt:
            self.progress.emit(77, "  Schneide auf gewählte Abgrenzung zu …")
            all_grid, _removed = _clip_grid_to_wkt(
                all_grid, clip_wkt, e_min, n_min, cfg.get("cell_size", 1.0),
                _log=lambda m: self.progress.emit(-1, m))
            if not all_grid:
                self.finished.emit(False,
                    "Nach dem Zuschnitt auf die Abgrenzung sind keine "
                    "Rasterzellen übrig – Abgrenzung und Bereich prüfen.")
                return

        # ── Lücken füllen (IDW) ──────────────────────────────────────────
        if cfg.get("fill_gaps", True) and all_grid:
            self.progress.emit(78, "  Fülle Lücken (IDW, Radius 5 m) …")
            all_grid, n_filled = _fill_gaps(
                all_grid, e_min, n_min, e_max, n_max, cell_m,
                max_search=max(3, int(5 / cfg.get("cell_size", 1.0)))
            )
            if n_filled:
                self.progress.emit(80,
                    f"  {n_filled:,} Lücken gefüllt → "
                    f"{len(all_grid):,} Zellen gesamt")

        # ── Aggregation (optional) ───────────────────────────────────────────
        agg_cell_m = cfg.get("agg_cell_m", 0.0)
        agg_func   = cfg.get("agg_func", "mean")
        if agg_cell_m and agg_cell_m > cell_m:
            self.progress.emit(77,
                f"  Aggregiere {cell_m:.1f} m → {agg_cell_m:.1f} m ({agg_func}) …")
            all_grid = _aggregate_grid(all_grid, cell_m, agg_cell_m, agg_func)
            cell_m   = agg_cell_m  # Zellgröße aktualisieren für Features + Derive
            self.progress.emit(78,
                f"  → {len(all_grid):,} Zellen nach Aggregation")

        # ── Features berechnen ────────────────────────────────────────────────
        self.progress.emit(78, "Berechne Statistik pro Zelle …")
        if _NUMPY_OK:
            features = _grid_to_features_numpy(all_grid, e_min, n_min, cell_m)
        else:
            features = _grid_to_features(all_grid, e_min, n_min, cell_m)

        # ── GeoPackage schreiben ──────────────────────────────────────────────
        self.progress.emit(82, f"Schreibe GeoPackage ({len(features):,} Features) …")

        fields = QgsFields()
        fields.append(QgsField("hoehe_avg",   QVariant.Double))
        fields.append(QgsField("hoehe_min",   QVariant.Double))
        fields.append(QgsField("hoehe_max",   QVariant.Double))
        fields.append(QgsField("hoehe_range", QVariant.Double))
        fields.append(QgsField("n_punkte",    QVariant.Int))

        crs_utm = QgsCoordinateReferenceSystem("EPSG:25832")
        opts    = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName   = "GPKG"
        opts.fileEncoding = "UTF-8"
        opts.layerName    = "hoehenraster_1m"
        opts.actionOnExistingFile = (
            QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile)

        writer = QgsVectorFileWriter(
            out_path, "UTF-8", fields,
            QgsWkbTypes.Type.Polygon, crs_utm, "GPKG")
        if writer.hasError() != QgsVectorFileWriter.WriterError.NoError:
            self.finished.emit(False,
                f"GeoPackage-Fehler: {writer.errorMessage()}"); return

        BATCH = 5000
        feat  = QgsFeature(fields)
        for i, (wkt, avg, zmin, zmax, cnt) in enumerate(features):
            if self._abort:
                del writer
                self.finished.emit(False, "Abgebrochen."); return
            feat.setGeometry(QgsGeometry.fromWkt(wkt))
            feat.setAttributes([avg, zmin, zmax,
                                  round(zmax-zmin, 3), cnt])
            writer.addFeature(feat)
            if (i+1) % BATCH == 0:
                pct = int(82 + (i+1)/len(features)*15)
                self.progress.emit(pct,
                    f"  {i+1:,}/{len(features):,} Features")

        del writer  # schließt + committed

        size_mb = os.path.getsize(out_path) / 1_048_576
        self.progress.emit(97, f"  ✓ Höhenraster: {size_mb:.1f} MB")
        _derive_products(cfg, out_path.replace(".gpkg",""),
                         all_grid, e_min, n_min, e_max, n_max, cell_m, self)

        # Wenn TIN aktiv: Vektor-Höhenwerte aus tin_analyse.tif aktualisieren
        if cfg.get("out_tin", False):
            import os as _os_tin
            tin_analyse = out_path.replace(".gpkg", "_tin_analyse.tif")
            if _os_tin.path.exists(tin_analyse):
                try:
                    from osgeo import gdal as _gd3
                    import numpy as _np3
                    ds_t = _gd3.Open(tin_analyse)
                    arr_t = ds_t.GetRasterBand(1).ReadAsArray()
                    gt_t  = ds_t.GetGeoTransform()
                    nd_t  = ds_t.GetRasterBand(1).GetNoDataValue() or -9999
                    ds_t  = None
                    updated = 0
                    for feat in features:
                        geom = feat.geometry()
                        if not geom: continue
                        px = geom.asPoint()
                        c_t = int((px.x() - gt_t[0]) / gt_t[1])
                        r_t = int((px.y() - gt_t[3]) / gt_t[5])
                        if 0 <= c_t < arr_t.shape[1] and 0 <= r_t < arr_t.shape[0]:
                            z = float(arr_t[r_t, c_t])
                            if z != nd_t and z > -9000:
                                feat["hoehe_avg"] = z
                                updated += 1
                    self.progress.emit(-1,
                        f"  → {updated:,} Vektor-Höhenwerte aus TIN-Analyse aktualisiert")
                except Exception as _ev:
                    self.progress.emit(-1, f"  ⚠ TIN→Vektor-Update: {_ev}")

        self.progress.emit(100, "✓ Alle Produkte erstellt.")
        self.finished.emit(True,
            f"✓ {len(features):,} Rasterzellen → {out_path} ({size_mb:.1f} MB)")



# ── Dialog ────────────────────────────────────────────────────────────────────

