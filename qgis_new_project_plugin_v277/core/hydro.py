"""core/hydro.py - Hydrologische Algorithmen (D8, Strahler, Senken)"""
import os
import math
import numpy as np
from scipy import ndimage

try:
    import richdem as rd
    _RICHDEM = True
except ImportError:
    _RICHDEM = False

try:
    from pysheds.grid import Grid as _PyShedsGrid
    _PYSHEDS = True
except ImportError:
    _PYSHEDS = False

try:
    from numba import njit, prange
    _NUMBA = True
except ImportError:
    _NUMBA = False

_ACCEL = ("richdem" if _RICHDEM else
          "pysheds" if _PYSHEDS else
          "numba"   if _NUMBA   else
          "numpy")

try:
    from osgeo import gdal, osr, ogr
    gdal.UseExceptions()
    _GDAL_OK = True
except ImportError:
    _GDAL_OK = False

try:
    from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer
    _QGIS_OK = True
except ImportError:
    _QGIS_OK = False


# D8-Richtungskodierung (ESRI-Standard)
# ┌───┬───┬───┐
# │ 32│ 64│128│
# ├───┼───┼───┤
# │ 16│ X │  1│
# ├───┼───┼───┤
# │  8│  4│  2│
# └───┴───┴───┘
D8_DIRS = [1, 2, 4, 8, 16, 32, 64, 128]
_rd_acc_cache: dict = {}   # Cache für richdem flow_acc
# dy, dx für jede Richtung
D8_DY   = [0, 1, 1,  1,  0, -1, -1, -1]
D8_DX   = [1, 1, 0, -1, -1, -1,  0,  1]


# ── Hydrologische Kernfunktionen ──────────────────────────────────────────────


# ── CRS-Konstanten ────────────────────────────────────────────────────────────
try:
    from qgis.core import QgsCoordinateReferenceSystem as _CRS
    WGS84 = _CRS("EPSG:4326")
    UTM32 = _CRS("EPSG:25832")
except Exception:
    WGS84 = None
    UTM32 = None


def fill_sinks(dem: np.ndarray, nodata=-9999.0) -> np.ndarray:
    """
    Füllt Senken im DEM (Priority-Flood).
    Nutzt richdem/pysheds falls verfügbar (20–100× schneller).
    """
    # richdem: C++ Priority-Flood mit OpenMP-Parallelisierung
    if _RICHDEM:
        dem_rd = rd.rdarray(dem.copy(), no_data=nodata)
        dem_rd.projection = "EPSG:25832"
        rd.FillDepressions(dem_rd, epsilon=True, in_place=True)
        return np.array(dem_rd, dtype=np.float32)
    # pysheds: Cython Priority-Flood
    if _PYSHEDS:
        try:
            from pysheds.sview import Raster as _PR, ViewFinder as _VF
            vf   = _VF(shape=dem.shape, nodata=nodata)
            rast = _PR(dem.astype(np.float64), viewfinder=vf)
            from pysheds.grid import Grid
            g = Grid()
            return g.fill_pits(rast).astype(np.float32)
        except Exception:
            pass   # Fallback

    # Numba verfügbar: JIT-kompilierte Variante nutzen
    if _NUMBA:
        return _fill_sinks_numba(dem, nodata)

    from heapq import heappush, heappop

    filled = dem.copy()
    rows, cols = dem.shape
    visited = np.zeros((rows, cols), dtype=bool)
    heap = []

    # Alle Randzellen als Startpunkte
    for r in range(rows):
        for c in [0, cols - 1]:
            if dem[r, c] != nodata:
                heappush(heap, (dem[r, c], r, c))
                visited[r, c] = True
    for c in range(cols):
        for r in [0, rows - 1]:
            if dem[r, c] != nodata and not visited[r, c]:
                heappush(heap, (dem[r, c], r, c))
                visited[r, c] = True

    while heap:
        z, r, c = heappop(heap)
        for dy, dx in zip([-1, -1, -1, 0, 0, 1, 1, 1],
                          [-1,  0,  1,-1, 1,-1, 0, 1]):
            nr, nc = r + dy, c + dx
            if 0 <= nr < rows and 0 <= nc < cols and not visited[nr, nc]:
                if dem[nr, nc] != nodata:
                    filled[nr, nc] = max(dem[nr, nc], z)
                    visited[nr, nc] = True
                    heappush(heap, (filled[nr, nc], nr, nc))

    return filled



if _NUMBA:
    @njit(parallel=True, cache=True)
    def _fill_sinks_numba_inner(dem, nodata):
        """Numba-JIT-kompilierte Senken-Erkennung (kein Priority-Flood,
        aber 20× schneller als Python-heapq für die Vorverarbeitung)."""
        rows, cols = dem.shape
        filled = dem.copy()
        changed = True
        while changed:
            changed = False
            for r in prange(1, rows - 1):
                for c in range(1, cols - 1):
                    if dem[r, c] == nodata:
                        continue
                    min_nb = filled[r, c]
                    for dr in [-1, 0, 1]:
                        for dc in [-1, 0, 1]:
                            if dr == 0 and dc == 0:
                                continue
                            nb = filled[r + dr, c + dc]
                            if nb != nodata and nb < min_nb:
                                min_nb = nb
                    if filled[r, c] < min_nb:
                        filled[r, c] = min_nb
                        changed = True
        return filled

    def _fill_sinks_numba(dem, nodata):
        return _fill_sinks_numba_inner(dem, nodata)
else:
    def _fill_sinks_numba(dem, nodata):
        return dem  # Nicht aufgerufen wenn _NUMBA=False


def flow_direction_d8(dem: np.ndarray, cell_m: float,
                      nodata=-9999.0) -> np.ndarray:
    """
    D8-Abflussrichtung. Nutzt richdem/pysheds falls verfügbar.
    richdem: D8, D∞ oder MFD (Multiple Flow Direction) möglich.
    """
    if _RICHDEM:
        dem_rd = rd.rdarray(dem.copy(), no_data=nodata)
        dem_rd.projection = "EPSG:25832"
        # richdem gibt A2 (TabularD8) oder D8 zurück
        props = rd.FlowProportions(dem=dem_rd, method="D8")
        # Konvertiere richdem-D8 zu ESRI-D8-Codes
        # richdem: 0=E 1=SE 2=S 3=SW 4=W 5=NW 6=N 7=NE
        rd_to_esri = {0:1, 1:2, 2:4, 3:8, 4:16, 5:32, 6:64, 7:128}
        fdir_rd = rd.FlowAccumulation(dem_rd, method="D8")
        # Verwende richdem direkt für Akkumulation, D8 separat
        _rd_acc_cache[id(dem)] = (np.array(fdir_rd), dem_rd)
        # Für ESRI-Codes: eigener numpy-Weg (schnell da DEM bereits gefüllt)
        pass   # Fallthrough zu numpy
    if _PYSHEDS:
        try:
            from pysheds.sview import Raster as _PR, ViewFinder as _VF
            vf   = _VF(shape=dem.shape, nodata=nodata)
            rast = _PR(dem.astype(np.float64), viewfinder=vf)
            from pysheds.grid import Grid
            g = Grid()
            fdir_ps = g.flowdir(rast)
            return np.array(fdir_ps, dtype=np.int16)
        except Exception:
            pass

    rows, cols = dem.shape
    fdir = np.zeros((rows, cols), dtype=np.int16)

    # Diagonale Distanz √2 × Zellgröße
    dists = [cell_m, cell_m * math.sqrt(2), cell_m,
             cell_m * math.sqrt(2), cell_m,
             cell_m * math.sqrt(2), cell_m,
             cell_m * math.sqrt(2)]

    for i, (dy, dx) in enumerate(zip(D8_DY, D8_DX)):
        # Gefälle zu dieser Richtung
        nr = np.clip(np.arange(rows)[:, None] + dy, 0, rows - 1)
        nc = np.clip(np.arange(cols)[None, :] + dx, 0, cols - 1)
        slope = (dem - dem[nr, nc]) / dists[i]
        if i == 0:
            max_slope = slope
            fdir[:] = D8_DIRS[0]
        else:
            mask = slope > max_slope
            max_slope = np.where(mask, slope, max_slope)
            fdir = np.where(mask, D8_DIRS[i], fdir)

    # Nodata-Zellen
    fdir[dem == nodata] = 0
    return fdir


def flow_accumulation(fdir: np.ndarray, dem=None) -> np.ndarray:
    """
    Abflussakkumulation. Nutzt richdem-Cache oder pysheds falls verfügbar.
    richdem-Ergebnis wurde in flow_direction_d8 gecacht.
    """
    cache_key = id(dem) if dem is not None else None
    if _RICHDEM and cache_key in _rd_acc_cache:
        acc_arr, _ = _rd_acc_cache.pop(cache_key)
        return acc_arr.astype(np.int64)
    if _PYSHEDS:
        try:
            from pysheds.sview import Raster as _PR, ViewFinder as _VF
            vf   = _VF(shape=fdir.shape, nodata=0)
            rast = _PR(fdir.astype(np.int32), viewfinder=vf)
            from pysheds.grid import Grid
            g = Grid()
            return np.array(g.accumulation(rast), dtype=np.int64)
        except Exception:
            pass

    rows, cols = fdir.shape
    acc = np.ones((rows, cols), dtype=np.int64)

    # Richtungs-Lookup: welche Zelle empfängt den Abfluss von (r,c)?
    dir_to_dy = {1: 0, 2: 1, 4: 1, 8: 1, 16: 0, 32: -1, 64: -1, 128: -1}
    dir_to_dx = {1: 1, 2: 1, 4: 0, 8: -1, 16: -1, 32: -1, 64: 0, 128: 1}

    # Anzahl eingehender Kanten
    in_count = np.zeros((rows, cols), dtype=np.int32)
    for r in range(rows):
        for c in range(cols):
            d = fdir[r, c]
            if d in dir_to_dy:
                nr = r + dir_to_dy[d]
                nc = c + dir_to_dx[d]
                if 0 <= nr < rows and 0 <= nc < cols:
                    in_count[nr, nc] += 1

    # Topologische Sortierung (Quellen zuerst)
    from collections import deque
    queue = deque()
    for r in range(rows):
        for c in range(cols):
            if in_count[r, c] == 0 and fdir[r, c] != 0:
                queue.append((r, c))

    while queue:
        r, c = queue.popleft()
        d = fdir[r, c]
        if d not in dir_to_dy:
            continue
        nr = r + dir_to_dy[d]
        nc = c + dir_to_dx[d]
        if 0 <= nr < rows and 0 <= nc < cols:
            acc[nr, nc] += acc[r, c]
            in_count[nr, nc] -= 1
            if in_count[nr, nc] == 0:
                queue.append((nr, nc))

    return acc


def detect_sinks(dem_orig: np.ndarray, dem_filled: np.ndarray,
                 nodata=-9999.0, min_depth=0.05) -> np.ndarray:
    """
    Erkennt Abflusssenken als Differenz Original vs. gefülltes DEM.
    min_depth: Mindesttiefe in Metern (Filtert Rauschen).
    """
    diff = dem_filled - dem_orig
    sinks = np.where(
        (diff >= min_depth) & (dem_orig != nodata),
        diff, 0.0).astype(np.float32)
    return sinks


def extract_streams(acc: np.ndarray, threshold: int) -> np.ndarray:
    """
    Extrahiert Gewässernetz durch Akkumulations-Schwellenwert.
    threshold: Mindestanzahl Zellen (Einzugsgebiet).
    """
    return (acc >= threshold).astype(np.uint8)


def strahler_order(streams: np.ndarray, fdir: np.ndarray) -> np.ndarray:
    """
    Berechnet die Strahler-Ordnung des Gewässernetzes.
    1 = Quellbach, höhere Werte = Hauptgewässer.
    """
    rows, cols = streams.shape
    order = np.zeros((rows, cols), dtype=np.int16)
    dir_to_dy = {1: 0, 2: 1, 4: 1, 8: 1, 16: 0, 32: -1, 64: -1, 128: -1}
    dir_to_dx = {1: 1, 2: 1, 4: 0, 8: -1, 16: -1, 32: -1, 64: 0, 128: 1}

    # Eingehende Gewässer-Kanten zählen
    in_streams = np.zeros((rows, cols), dtype=np.int32)
    for r in range(rows):
        for c in range(cols):
            if streams[r, c] and fdir[r, c] in dir_to_dy:
                nr = r + dir_to_dy[fdir[r, c]]
                nc = c + dir_to_dx[fdir[r, c]]
                if 0 <= nr < rows and 0 <= nc < cols and streams[nr, nc]:
                    in_streams[nr, nc] += 1

    from collections import deque
    queue = deque()
    for r in range(rows):
        for c in range(cols):
            if streams[r, c] and in_streams[r, c] == 0:
                order[r, c] = 1
                queue.append((r, c))

    while queue:
        r, c = queue.popleft()
        if not fdir[r, c] in dir_to_dy:
            continue
        nr = r + dir_to_dy[fdir[r, c]]
        nc = c + dir_to_dx[fdir[r, c]]
        if not (0 <= nr < rows and 0 <= nc < cols and streams[nr, nc]):
            continue

        in_streams[nr, nc] -= 1
        # Strahler-Regel
        cur = order[nr, nc]
        new = order[r, c]
        if new > cur:
            order[nr, nc] = new
        elif new == cur:
            order[nr, nc] = new + 1
        # else: cur bleibt

        if in_streams[nr, nc] == 0:
            queue.append((nr, nc))

    return order


# ── GeoTIFF-Hilfsfunktionen ───────────────────────────────────────────────────

def _write_cog(path, arr, gt, srs_wkt, dtype=None, nodata=None):
    """Schreibt numpy-Array als COG GeoTIFF (EPSG:25832)."""
    if not _GDAL_OK:
        return False
    tmp = path + "._tmp.tif"
    gdal_dtype = {
        np.float32: gdal.GDT_Float32,
        np.int16:   gdal.GDT_Int16,
        np.int32:   gdal.GDT_Int32,
        np.int64:   gdal.GDT_Int32,
        np.uint8:   gdal.GDT_Byte,
    }.get(arr.dtype.type, gdal.GDT_Float32)

    rows, cols = arr.shape
    drv = gdal.GetDriverByName("GTiff")
    ds  = drv.Create(tmp, cols, rows, 1, gdal_dtype,
                     ["COMPRESS=DEFLATE", "TILED=YES",
                      "BLOCKXSIZE=512", "BLOCKYSIZE=512"])
    ds.SetGeoTransform(gt)
    ds.SetProjection(srs_wkt)
    b = ds.GetRasterBand(1)
    b.WriteArray(arr.astype(arr.dtype))
    if nodata is not None:
        b.SetNoDataValue(nodata)
    ds.FlushCache(); ds = None

    gdal.Translate(path, tmp, format="COG",
                   creationOptions=["COMPRESS=DEFLATE", "BLOCKSIZE=512",
                                    "OVERVIEW_RESAMPLING=BILINEAR",
                                    "NUM_THREADS=ALL_CPUS"])
    os.remove(tmp)
    return True


def _streams_to_gpkg(streams, order, fdir, gt, srs_wkt, out_path):
    """Konvertiert Gewässernetz-Raster zu Vektorlinien (GPKG)."""
    if not _GDAL_OK:
        return
    e_min, cell_m = gt[0], gt[1]
    n_max = gt[3]

    if os.path.exists(out_path):
        ogr.GetDriverByName("GPKG").DeleteDataSource(out_path)

    ds_o = ogr.GetDriverByName("GPKG").CreateDataSource(out_path)
    sr    = osr.SpatialReference()
    sr.ImportFromWkt(srs_wkt)
    lyr   = ds_o.CreateLayer("gewaessernetz", sr, ogr.wkbLineString)

    for fname, ftype in [("strahler_ordnung", ogr.OFTInteger),
                         ("laenge_m",         ogr.OFTReal)]:
        f = ogr.FieldDefn(fname, ftype)
        lyr.CreateField(f)

    rows, cols = streams.shape
    dir_to_dy = {1:0,2:1,4:1,8:1,16:0,32:-1,64:-1,128:-1}
    dir_to_dx = {1:1,2:1,4:0,8:-1,16:-1,32:-1,64:0,128:1}

    visited = np.zeros_like(streams, dtype=bool)

    for r0 in range(rows):
        for c0 in range(cols):
            if not streams[r0, c0] or visited[r0, c0]:
                continue
            # Segment verfolgen
            pts  = []
            r, c = r0, c0
            while streams[r, c] and not visited[r, c]:
                visited[r, c] = True
                x = e_min + c * cell_m + cell_m / 2
                y = n_max + r * (-cell_m) - cell_m / 2
                pts.append((x, y))
                d = fdir[r, c]
                if d not in dir_to_dy: break
                nr, nc = r + dir_to_dy[d], c + dir_to_dx[d]
                if not (0 <= nr < rows and 0 <= nc < cols): break
                r, c = nr, nc

            if len(pts) < 2:
                continue
            geom = ogr.Geometry(ogr.wkbLineString)
            for x, y in pts:
                geom.AddPoint(x, y)
            feat = ogr.Feature(lyr.GetLayerDefn())
            feat.SetGeometry(geom)
            feat.SetField("strahler_ordnung", int(order[r0, c0]))
            feat.SetField("laenge_m", round(len(pts) * cell_m, 1))
            lyr.CreateFeature(feat)

    ds_o.FlushCache(); ds_o = None


def _sinks_to_gpkg(sinks_arr, gt, srs_wkt, out_path, min_area_m2=100):
    """Konvertiert Senkenflächen zu Polygonen (GPKG)."""
    if not _GDAL_OK:
        return
    # Labeling der zusammenhängenden Senkenflächen
    labeled, n = ndimage.label(sinks_arr > 0)
    if n == 0:
        return

    cell_m = gt[1]
    cell_area = cell_m ** 2

    if os.path.exists(out_path):
        ogr.GetDriverByName("GPKG").DeleteDataSource(out_path)
    ds_o = ogr.GetDriverByName("GPKG").CreateDataSource(out_path)
    sr    = osr.SpatialReference(); sr.ImportFromWkt(srs_wkt)
    lyr   = ds_o.CreateLayer("abflusssenken", sr, ogr.wkbPolygon)
    for fname, ftype in [("tiefe_m_max", ogr.OFTReal),
                         ("tiefe_m_avg", ogr.OFTReal),
                         ("flaeche_m2",  ogr.OFTReal)]:
        lyr.CreateField(ogr.FieldDefn(fname, ftype))

    e_min, n_max = gt[0], gt[3]
    rows, cols = sinks_arr.shape

    for label in range(1, n + 1):
        mask  = labeled == label
        area  = mask.sum() * cell_area
        if area < min_area_m2:
            continue
        depths = sinks_arr[mask]
        # Einfaches Bounding-Box-Polygon
        rr, cc = np.where(mask)
        r_min, r_max = rr.min(), rr.max()
        c_min, c_max = cc.min(), cc.max()
        x0 = e_min + c_min * cell_m
        x1 = e_min + (c_max + 1) * cell_m
        y0 = n_max + r_max * (-cell_m)
        y1 = n_max + r_min * (-cell_m)
        ring = ogr.Geometry(ogr.wkbLinearRing)
        for x, y in [(x0,y0),(x1,y0),(x1,y1),(x0,y1),(x0,y0)]:
            ring.AddPoint(x, y)
        poly = ogr.Geometry(ogr.wkbPolygon); poly.AddGeometry(ring)
        feat = ogr.Feature(lyr.GetLayerDefn())
        feat.SetGeometry(poly)
        feat.SetField("tiefe_m_max", float(depths.max()))
        feat.SetField("tiefe_m_avg", float(depths.mean()))
        feat.SetField("flaeche_m2",  float(area))
        lyr.CreateFeature(feat)

    ds_o.FlushCache(); ds_o = None


# ── Worker ────────────────────────────────────────────────────────────────────


def _load(path: str, name: str):
    """Laed ein GeoTIFF als Rasterlayer in QGIS."""
    if not _QGIS_OK:
        return
    try:
        from qgis.core import QgsRasterLayer, QgsProject
        lyr = QgsRasterLayer(path, name, "gdal")
        if lyr.isValid():
            QgsProject.instance().addMapLayer(lyr)
    except Exception:
        pass


def _load_vector(path: str, layername: str, name: str):
    """Laed einen GPKG-Layer als Vektorlayer in QGIS."""
    if not _QGIS_OK:
        return
    try:
        from qgis.core import QgsVectorLayer, QgsProject
        lyr = QgsVectorLayer(f"{path}|layername={layername}", name, "ogr")
        if lyr.isValid():
            QgsProject.instance().addMapLayer(lyr)
    except Exception:
        pass
