"""core/lidar.py - LiDAR-Kernalgorithmen (LAZ, Grid, IDW, COG)"""
import os, math, struct, tempfile, shutil, subprocess, sys
import numpy as np
_NUMPY_OK = True  # numpy immer in OSGeo4W verfügbar

# PDAL-Verfügbarkeit prüfen:
# 1. Python-pdal-Bindings (pdal.Pipeline)
# 2. pdal.exe im PATH oder in bekannten OSGeo4W-Pfaden
try:
    import pdal as _pdal_module
    _PDAL_OK        = True
    _PDAL_USE_PY    = True   # Python-Bindings verwenden
except ImportError:
    _PDAL_USE_PY = False
    # Suche pdal.exe: PATH + bekannte OSGeo4W-Pfade
    import subprocess as _sp_pdal, shutil as _sh_pdal
    _PDAL_EXE = _sh_pdal.which("pdal")
    if _PDAL_EXE is None:
        # Typische OSGeo4W-Installationspfade
        for _candidate in [
            r"C:\OSGeo4W\bin\pdal.exe",
            r"C:\OSGeo4W64\bin\pdal.exe",
            r"C:\Program Files\QGIS 3.44\bin\pdal.exe",
            r"C:\Program Files\QGIS 3.40\bin\pdal.exe",
            r"C:\Program Files\QGIS 3.36\bin\pdal.exe",
        ]:
            if _sh_pdal.os.path.isfile(_candidate):
                _PDAL_EXE = _candidate
                break
    try:
        _sp_pdal.run([_PDAL_EXE or "pdal", "--version"],
                     capture_output=True, timeout=5)
        _PDAL_OK = True
    except Exception:
        _PDAL_EXE = None
        _PDAL_OK  = False

try:
    import requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

try:
    import laspy
    _LASPY_OK = True
except ImportError:
    _LASPY_OK = False

try:
    from osgeo import gdal, osr, ogr
    gdal.UseExceptions()
    _GDAL_OK = True
except ImportError:
    _GDAL_OK = False

try:
    from qgis.core import (QgsProject, QgsVectorLayer, QgsRasterLayer,
                           QgsVectorFileWriter, QgsFields, QgsField,
                           QgsFeature, QgsGeometry, QgsWkbTypes,
                           QgsCoordinateReferenceSystem)
    from qgis.PyQt.QtCore import QVariant
    _QGIS_OK = True
except ImportError:
    _QGIS_OK = False

# ── Konstanten ─────────────────────────────────────────────────────────────────

WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")
UTM32 = QgsCoordinateReferenceSystem("EPSG:25832")

LAS_TILE_M   = 1000   # 1 km × 1 km Kacheln
GRID_M       = 1.0    # Zielauflösung 1 × 1 m

# OpenGeoData NRW – 3D-Messung (LAS/LAZ, Klassifizierung vorhanden)
LAS_URL = (
    "https://www.opengeodata.nrw.de/produkte/geobasis/hm/3dm_l_las/"
    "3dm_l_las/3dm_32_{e}_{n}_1_nw.laz"
)

# Klassifizierung nach LAS-Standard
try:
    from qgis.core import (QgsCoordinateReferenceSystem,
                           QgsCoordinateTransform,
                           QgsCoordinateTransformContext, QgsPointXY)
    WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")
    UTM32 = QgsCoordinateReferenceSystem("EPSG:25832")
except Exception:
    WGS84 = None; UTM32 = None
    from qgis.core import QgsCoordinateTransform, QgsCoordinateTransformContext, QgsPointXY

CLASS_GROUND   = 2    # Boden
CLASS_ALL      = None # alle Punkte (wenn kein Filter)


CLASS_GROUND   = 2    # Boden
CLASS_ALL      = None # alle Punkte (wenn kein Filter)


# ── Koordinaten-Hilfsfunktionen ───────────────────────────────────────────────

def _wgs84_to_utm32(lon_min, lat_min, lon_max, lat_max):
    tr = QgsCoordinateTransform(WGS84, UTM32, QgsCoordinateTransformContext())
    sw = tr.transform(QgsPointXY(lon_min, lat_min))
    ne = tr.transform(QgsPointXY(lon_max, lat_max))
    return sw.x(), sw.y(), ne.x(), ne.y()


def _las_tiles(e_min, n_min, e_max, n_max, tm=LAS_TILE_M):
    """Alle 1-km-LAS-Kacheln für den UTM32-Bereich."""
    e0 = int(e_min // tm) * tm
    n0 = int(n_min // tm) * tm
    tiles = []
    e = e0
    while e <= e_max:
        n = n0
        while n <= n_max:
            tiles.append((int(e // 1000), int(n // 1000)))  # in km für URL
            n += tm
        e += tm
    return tiles


# ── LAS/LAZ lesen (reines Python, kein laspy erforderlich) ───────────────────

def _read_las_points(path: str, class_filter: int = None) -> np.ndarray:
    """
    Liest X, Y, Z aus LAS/LAZ-Datei.
    Priorität: laspy → PDAL → eigener Parser (nur LAS, kein LAZ).
    """
    if _LASPY_OK:
        return _read_laspy(path, class_filter)  # fällt intern auf PDAL zurück
    if _PDAL_OK:
        return _read_pdal(path, class_filter)
    # Letzter Fallback: nur unkomprimiertes LAS
    if path.lower().endswith(".laz"):
        # Versuche laspy automatisch zu installieren
        try:
            import subprocess, sys
            subprocess.run(
                [sys.executable, "-m", "pip", "install",
                 "laspy[lazrs]", "--quiet"],
                timeout=60, check=True)
            import laspy
            return _read_laspy(path, class_filter)
        except Exception:
            pass
        raise RuntimeError(
            "LAZ-Datei: weder laspy noch PDAL verfügbar.\n"
            "Lösung A (empfohlen): OSGeo4W-Shell öffnen und eingeben:\n"
            "  pip install laspy[lazrs]\n"
            "  (Fallback falls kein Rust: pip install laspy laszip)\n"
            "Lösung B: QGIS → Erweiterungen → Python-Konsole:\n"
            "  import subprocess, sys\n"
            "  subprocess.run([sys.executable, '-m', 'pip', 'install',"
            "                 'laspy', 'lazrs-python'])")
    return _read_las_raw(path, class_filter)


def _read_laspy(path: str, class_filter: int = None) -> np.ndarray:
    """laspy-basierter Reader – fällt bei fehlendem LAZ-Backend auf PDAL zurück."""
    try:
        las = laspy.read(path)  # kein Context-Manager in laspy < 2.x
        if class_filter is not None:
            mask = (np.asarray(las.classification) == class_filter)
            x = np.asarray(las.x)[mask]
            y = np.asarray(las.y)[mask]
            z = np.asarray(las.z)[mask]
        else:
            x = np.asarray(las.x)
            y = np.asarray(las.y)
            z = np.asarray(las.z)
        return np.column_stack([x, y, z])
    except Exception as _laz_err:
        # "No LazBackend selected" → laspy ohne lazrs/laszip installiert
        # Fallback: PDAL-CLI (in OSGeo4W immer vorhanden)
        if "LazBackend" in str(_laz_err) or "decompress" in str(_laz_err):
            if _PDAL_OK:
                return _read_pdal(path, class_filter)
            # Letzter Ausweg: laspy ohne Komprimierung über temp-LAS
            raise RuntimeError(
                f"LAZ-Backend fehlt: {_laz_err}\n"
                "Lösung: In OSGeo4W-Shell ausführen:\n"
                "  pip install laspy[lazrs]\n"
                "  (Fallback: pip install laspy laszip)"
            )
        raise  # anderer Fehler → weiterwerfen


def _read_pdal(path: str, class_filter: int = None) -> np.ndarray:
    """
    Liest LAZ/LAS via PDAL.
    Priorität: Python-Bindings (import pdal) → pdal.exe CLI.
    """
    import subprocess, tempfile

    # Weg 1: Python-Bindings mit writers.las → temp LAS → eigener Parser
    # (writers.numpy fehlt in OSGeo4W-PDAL → writers.las als Fallback)
    if _PDAL_USE_PY:
        import pdal as _pdal
        import json, tempfile
        tmp_las = tempfile.mktemp(suffix=".las")
        try:
            pipeline_def = {
                "pipeline": [
                    {"type": "readers.las", "filename": path},
                ]
            }
            if class_filter is not None:
                pipeline_def["pipeline"].append({
                    "type": "filters.range",
                    "limits": f"Classification[{class_filter}:{class_filter}]"
                })
            pipeline_def["pipeline"].append({
                "type": "writers.las",
                "filename": tmp_las,
                "compression": "none"
            })
            p = _pdal.Pipeline(json.dumps(pipeline_def))
            p.execute()
            return _read_las_raw(tmp_las, class_filter)
        finally:
            if os.path.exists(tmp_las):
                os.remove(tmp_las)

    # Weg 2: pdal.exe CLI → LAZ → temp LAS → eigener Parser
    exe = _PDAL_EXE or "pdal"
    tmp_las = tempfile.mktemp(suffix=".las")
    try:
        cmd = [exe, "translate", path, tmp_las]
        if class_filter is not None:
            cmd += [
                "--filter", "filters.range",
                f"--filters.range.limits=Classification[{class_filter}:{class_filter}]",
            ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(result.stderr[:300])
        if not os.path.exists(tmp_las) or os.path.getsize(tmp_las) < 100:
            raise RuntimeError("pdal translate erzeugte keine Ausgabe")
        return _read_las_raw(tmp_las, class_filter)
    finally:
        if os.path.exists(tmp_las):
            os.remove(tmp_las)


def _read_las_raw(path: str, class_filter: int = None) -> np.ndarray:
    """
    Minimaler LAS 1.2–1.4 Parser ohne externe Bibliothek.
    Unterstützt nur unkomprimiertes LAS (nicht LAZ).
    """
    with open(path, "rb") as f:
        sig = f.read(4)
        if sig != b"LASF":
            raise ValueError(f"Kein LAS-Format: {path}")

        f.seek(24)
        ver_major, ver_minor = struct.unpack("BB", f.read(2))
        f.seek(94)
        header_size  = struct.unpack("H", f.read(2))[0]
        offset_data  = struct.unpack("I", f.read(4))[0]
        n_vlr        = struct.unpack("I", f.read(4))[0]
        fmt_id       = struct.unpack("B", f.read(1))[0]
        rec_length   = struct.unpack("H", f.read(2))[0]
        if ver_major == 1 and ver_minor >= 4:
            # LAS 1.4: n_point_records (uint64) liegt an Offset 247
            # Offset 107–110: legacy n_points (0 bei >2^32 Punkten)
            # Offset 111–130: legacy n_returns[5]
            # Offset 131–178: scale + offset
            # Offset 179–226: min/max XYZ
            # Offset 227–242: waveform + EVLR
            # Offset 243–246: n_EVLRs
            # Offset 247:     n_point_records (uint64) ← korrekt
            f.seek(247)
            n_points = struct.unpack("Q", f.read(8))[0]
        else:
            # LAS 1.0–1.3: n_points (uint32) an Offset 107
            f.seek(107)
            n_points = struct.unpack("I", f.read(4))[0]

        # Scale und Offset
        f.seek(131)
        sx, sy, sz = struct.unpack("ddd", f.read(24))
        ox, oy, oz = struct.unpack("ddd", f.read(24))

        # Klassifizierung Byte-Offset je nach Format
        cls_offset = {0:15,1:15,2:19,3:19,4:22,5:22,
                      6:16,7:16,8:16,9:19,10:21}.get(fmt_id, 15)

        f.seek(offset_data)
        data = f.read()

    pts = []
    for i in range(n_points):
        off  = i * rec_length
        xi   = struct.unpack_from("i", data, off)[0]
        yi   = struct.unpack_from("i", data, off+4)[0]
        zi   = struct.unpack_from("i", data, off+8)[0]
        if class_filter is not None:
            cls = data[off + cls_offset] & 0x1F
            if cls != class_filter:
                continue
        pts.append([xi*sx+ox, yi*sy+oy, zi*sz+oz])

    return np.array(pts) if pts else np.zeros((0, 3))


# ── Raster-Berechnung ─────────────────────────────────────────────────────────

def _points_to_grid(pts: np.ndarray,
                    e_min: float, n_min: float,
                    e_max: float, n_max: float,
                    cell_m: float = 1.0) -> dict:
    """
    Teilt Punktwolke in cell_m × cell_m Zellen auf.
    Gibt Dict {(col, row): [z_werte, ...]} zurück.
    """
    if pts.shape[0] == 0:
        return {}

    # Punkte im AOI filtern
    mask = ((pts[:,0] >= e_min) & (pts[:,0] <= e_max) &
            (pts[:,1] >= n_min) & (pts[:,1] <= n_max))
    pts  = pts[mask]
    if pts.shape[0] == 0:
        return {}

    cols = ((pts[:,0] - e_min) / cell_m).astype(int)
    rows = ((pts[:,1] - n_min) / cell_m).astype(int)

    grid = {}
    for col, row, z in zip(cols, rows, pts[:,2]):
        key = (int(col), int(row))
        if key not in grid:
            grid[key] = []
        grid[key].append(float(z))

    return grid








def _to_cog(gd, src_path: str):
    """Konvertiert einen GeoTIFF in-place zu COG (Cloud Optimized GeoTIFF)."""
    import os
    tmp = src_path + "._cog_tmp.tif"
    gd.Translate(tmp, src_path, format="COG",
                 creationOptions=[
                     "COMPRESS=DEFLATE", "PREDICTOR=2",
                     "BLOCKSIZE=512",
                     "OVERVIEW_RESAMPLING=BILINEAR",
                     "NUM_THREADS=ALL_CPUS",
                 ])
    os.remove(src_path)
    os.rename(tmp, src_path)



def _apply_water_polygons(sw_layer, arr, water_mask, water_elev,
                           e_min, n_max, cell_m, cols, rows, _np, _log):
    """
    Verarbeitet einen Polygon-Layer stehender Gewässer als Breaklines.

    Für jedes Polygon:
      1. Uferlinie → dichte Stützpunkte mit Höhe aus DTM (Constraint)
      2. Innenfläche → Maske mit konstantem mittleren Ufer-Höhenwert

    Gibt zurück: (extra_points, extra_z, water_mask, water_elev)
    """
    extra_pts = []
    extra_z   = []

    try:
        for feat in sw_layer.getFeatures():
            geom = feat.geometry()
            if geom is None or geom.isEmpty():
                continue

            # Alle Ringe des Polygons (Außenring + Löcher)
            poly = geom.asPolygon() if geom.isMultipart() is False else None
            polys = geom.asMultiPolygon() if geom.isMultipart() else [geom.asPolygon()]

            ring_elevs = []   # Höhen aller Uferpunkte dieses Gewässers

            for poly in polys:
                for ring in poly:
                    # Dichte Stützpunkte entlang der Uferlinie
                    for pt in ring:
                        e, n = pt.x(), pt.y()
                        col = int((e - e_min) / cell_m)
                        row = int((n_max - n) / cell_m)
                        if 0 <= col < cols and 0 <= row < rows:
                            z = float(arr[row, col])
                            if z > -9000:
                                extra_pts.append([e, n])
                                extra_z.append(z)
                                ring_elevs.append(z)

            if not ring_elevs:
                continue

            # Mittlere Uferhöhe = hydrostatischer Wasserstand
            mean_z = float(_np.median(ring_elevs))

            # Wasserflächen-Maske rasterisieren (Bounding-Box + Punkt-in-Polygon)
            # Schnell via GDAL-Rasterisierung über temporäres In-Memory-Dataset
            try:
                from osgeo import gdal as _gd2, ogr as _og2, osr as _os2
                import tempfile, os as _os_tmp

                # Temporäres 1-Band-Raster in Ausdehnung des Gewässers
                bb     = geom.boundingBox()
                c0     = max(0, int((bb.xMinimum() - e_min) / cell_m) - 1)
                c1     = min(cols-1, int((bb.xMaximum() - e_min) / cell_m) + 1)
                r0     = max(0, int((n_max - bb.yMaximum()) / cell_m) - 1)
                r1     = min(rows-1, int((n_max - bb.yMinimum()) / cell_m) + 1)
                w, h   = c1 - c0 + 1, r1 - r0 + 1
                if w < 1 or h < 1:
                    continue

                mem_ds = _gd2.GetDriverByName("MEM").Create("", w, h, 1, _gd2.GDT_Byte)
                mem_ds.SetGeoTransform((e_min + c0*cell_m, cell_m, 0,
                                        n_max - r0*cell_m, 0, -cell_m))
                sr2 = _os2.SpatialReference(); sr2.ImportFromEPSG(25832)
                mem_ds.SetProjection(sr2.ExportToWkt())
                mem_ds.GetRasterBand(1).Fill(0)

                # Polygon in OGR umwandeln
                mem_vec = _og2.GetDriverByName("Memory").CreateDataSource("")
                lyr_v   = mem_vec.CreateLayer("w", sr2, _og2.wkbPolygon)
                feat_v  = _og2.Feature(lyr_v.GetLayerDefn())
                feat_v.SetGeometry(_og2.CreateGeometryFromWkt(geom.asWkt()))
                lyr_v.CreateFeature(feat_v)

                _gd2.RasterizeLayer(mem_ds, [1], lyr_v, burn_values=[1])
                tile = mem_ds.GetRasterBand(1).ReadAsArray()
                mem_ds = None; mem_vec = None

                mask_tile = tile == 1
                water_mask[r0:r1+1, c0:c1+1] |= mask_tile
                water_elev[r0:r1+1, c0:c1+1][mask_tile] = mean_z

            except Exception as _e_rast:
                _log(f"  ⚠ Rasterisierung Gewässer-Polygon: {_e_rast}")

    except Exception as e:
        _log(f"  ⚠ Stehende Gewässer: {e}")

    if extra_pts:
        return (_np.array(extra_pts), _np.array(extra_z, dtype=_np.float32),
                water_mask, water_elev)
    return (_np.empty((0, 2)), _np.empty(0), water_mask, water_elev)


def _apply_river_lines(fw_layer, arr, e_min, n_max, cell_m, cols, rows, _np, _log):
    """
    Verarbeitet einen Linien-Layer (Fließgewässer-Mittelachsen) als Breaklines.

    Jeder Stützpunkt der Linie wird mit der DTM-Höhe an dieser Position
    als TIN-Constraint eingebracht.  Das sichert monoton fallendes Gefälle
    und verhindert Rückstau-Artefakte in der TIN-Interpolation.
    """
    pts = []
    z_v = []
    try:
        for feat in fw_layer.getFeatures():
            geom = feat.geometry()
            if geom is None or geom.isEmpty():
                continue
            lines = geom.asMultiPolyline() if geom.isMultipart() else [geom.asPolyline()]
            for line in lines:
                for pt in line:
                    e, n = pt.x(), pt.y()
                    col = int((e - e_min) / cell_m)
                    row = int((n_max - n) / cell_m)
                    if 0 <= col < cols and 0 <= row < rows:
                        z = float(arr[row, col])
                        if z > -9000:
                            pts.append([e, n])
                            z_v.append(z)
    except Exception as e:
        _log(f"  ⚠ Fließgewässer: {e}")

    if pts:
        return _np.array(pts), _np.array(z_v, dtype=_np.float32)
    return _np.empty((0, 2)), _np.empty(0)



def _apply_building_footprints(geb_layer, arr, e_min, n_max, cell_m,
                                cols, rows, _np, _og, _os, _gd, _log):
    """
    LOD-2-Gebäudegrundflächen als TIN-Breaklines:
      1. Randpunkte der Footprints mit DTM-Höhe → Constraints
      2. Innenpunkte aus dem Punktset entfernen
         → TIN interpoliert Gelände unter dem Gebäude
    """
    extra_pts = []; extra_z = []
    excl_mask = _np.zeros((rows, cols), dtype=bool)
    try:
        for feat in geb_layer.getFeatures():
            geom = feat.geometry()
            if geom is None or geom.isEmpty(): continue
            polys = geom.asMultiPolygon() if geom.isMultipart() else [geom.asPolygon()]
            for poly in polys:
                for ring in poly:
                    for pt in ring:
                        e, n = pt.x(), pt.y()
                        col = int((e - e_min) / cell_m)
                        row = int((n_max - n) / cell_m)
                        if 0 <= col < cols and 0 <= row < rows:
                            z = float(arr[row, col])
                            if z > -9000:
                                extra_pts.append([e, n]); extra_z.append(z)
            # Innenfläche rasterisieren
            try:
                bb = geom.boundingBox()
                c0 = max(0, int((bb.xMinimum()-e_min)/cell_m)-1)
                c1 = min(cols-1, int((bb.xMaximum()-e_min)/cell_m)+1)
                r0 = max(0, int((n_max-bb.yMaximum())/cell_m)-1)
                r1 = min(rows-1, int((n_max-bb.yMinimum())/cell_m)+1)
                w, h = c1-c0+1, r1-r0+1
                if w < 1 or h < 1: continue
                mem_ds = _gd.GetDriverByName("MEM").Create("", w, h, 1, _gd.GDT_Byte)
                mem_ds.SetGeoTransform((e_min+c0*cell_m, cell_m, 0, n_max-r0*cell_m, 0, -cell_m))
                sr2 = _os.SpatialReference(); sr2.ImportFromEPSG(25832)
                mem_ds.SetProjection(sr2.ExportToWkt())
                mem_ds.GetRasterBand(1).Fill(0)
                mem_vec = _og.GetDriverByName("Memory").CreateDataSource("")
                lv = mem_vec.CreateLayer("b", sr2, _og.wkbPolygon)
                fv = _og.Feature(lv.GetLayerDefn())
                fv.SetGeometry(_og.CreateGeometryFromWkt(geom.asWkt()))
                lv.CreateFeature(fv)
                _gd.RasterizeLayer(mem_ds, [1], lv, burn_values=[1])
                tile = mem_ds.GetRasterBand(1).ReadAsArray()
                mem_ds = None; mem_vec = None
                excl_mask[r0:r1+1, c0:c1+1] |= (tile == 1)
            except Exception as _er:
                _log(f"  ⚠ Gebäude-Rasterisierung: {_er}")
    except Exception as e:
        _log(f"  ⚠ Gebäude-Breaklines: {e}")
    if extra_pts:
        return _np.array(extra_pts), _np.array(extra_z, dtype=_np.float32), excl_mask
    return _np.empty((0,2)), _np.empty(0), excl_mask



def _apply_building_polygons(bld_layer, arr, e_min, n_max, cell_m, cols, rows, _np, _log):
    """
    Gebäude-Grundrisse als TIN-Elevation-Constraint.
    Dachhöhe = LiDAR-Grundhöhe + measuredHeight.
    Gebäudeumriss wird mit steiler Wand modelliert.
    """
    from qgis.core import QgsGeometry, QgsPointXY
    extra_pts = []; extra_z = []; n_bld = 0

    for feat in bld_layer.getFeatures():
        geom = feat.geometry()
        if not geom or geom.isEmpty(): continue
        try: h = float(feat["measuredHeight"] or 0)
        except: h = 0
        if h < 1.5: continue   # Nebengebäude überspringen

        bb = geom.boundingBox()
        c0 = max(0, int((bb.xMinimum() - e_min) / cell_m))
        c1 = min(cols-1, int((bb.xMaximum() - e_min) / cell_m))
        r0 = max(0, int((n_max - bb.yMaximum()) / cell_m))
        r1 = min(rows-1, int((n_max - bb.yMinimum()) / cell_m))

        inner_z = []
        for row in range(r0, r1+1):
            for col in range(c0, c1+1):
                z = arr[row, col]
                if z > -9000:
                    x = e_min + col * cell_m + cell_m/2
                    y = n_max - row * cell_m - cell_m/2
                    if geom.contains(QgsGeometry.fromPointXY(QgsPointXY(x, y))):
                        inner_z.append(z)
        if not inner_z: continue

        z_base = float(_np.median(inner_z))
        z_roof = z_base + h
        n_bld += 1

        # Dachkante: Gebäudeumriss mit Dachhöhe
        verts = list(geom.vertices())
        for vx in verts:
            extra_pts.append([vx.x(), vx.y()])
            extra_z.append(z_roof)
        # Geländeseite direkt am Gebäude: steile Wand
        for vx in verts:
            extra_pts.append([vx.x() + 0.15, vx.y() + 0.15])
            extra_z.append(z_base)

    if extra_pts:
        _log(f"  Gebäude: {n_bld} Gebäude → {len(extra_pts):,} TIN-Punkte (Dachhöhe + Wand)")
    return (_np.array(extra_pts), _np.array(extra_z)) if extra_pts            else (_np.zeros((0,2)), _np.zeros(0))

def _tin_from_grid(cfg, base_path, arr, cols, rows,
                   e_min, n_max, cell_m, _gd, _os, _np, _log, _load_raster,
                   sw_layer=None, fw_layer=None, bld_layer=None):
    """
    Baut ein TIN aus dem Höhenraster-Array und schreibt zwei COG-GeoTIFFs:
      _tin_analyse.tif  – rohes Raster (keine Glättung, für Analysen)
      _tin_anzeige.tif  – Gauß-geglättet (für Karten-Visualisierung)

    Workflow:
      1. Grid-Punkte (Zellmittelpunkte) → scipy.spatial.Delaunay → TIN
      2. Rasterisierung via barycentrische Interpolation
      3. Analyse-Output: ungeglättet
      4. Anzeige-Output: scipy.ndimage.gaussian_filter(sigma = kernel/3)
    """
    import os as _osp
    try:
        from scipy.spatial import Delaunay as _Del
        from scipy.ndimage import gaussian_filter as _gauss
        from scipy.interpolate import LinearNDInterpolator as _LinNDI
    except ImportError:
        _log("  ⚠ scipy fehlt – TIN nicht möglich (pip install scipy)")
        return

    kernel = int(cfg.get("tin_gauss_kernel", 3))
    sigma  = max(0.1, kernel / 3.0)   # Gauß-Sigma aus Kernel-Größe

    _log(f"  TIN aufbauen ({cols}×{rows} Zellen, Gauß-Kernel={kernel}) …")

    # ── Punkt-Koordinaten aus Grid ─────────────────────────────────────────
    valid_mask = arr > -9000
    ys, xs     = _np.where(valid_mask)
    if len(xs) < 4:
        _log("  ⚠ TIN: zu wenige Punkte (< 4)")
        return

    # Pixel-Koordinaten → UTM (Zellmittelpunkte)
    e_coords = e_min + (xs + 0.5) * cell_m
    n_coords = n_max - (ys + 0.5) * cell_m
    z_vals   = arr[ys, xs]
    points   = _np.column_stack([e_coords, n_coords])

    # ── Breaklines: Stehende Gewässer → Uferpunkte + konstante Fläche ──────
    water_mask = _np.zeros((rows, cols), dtype=bool)   # True = Wasserfläche
    water_elev = _np.full((rows, cols), _np.nan, dtype=_np.float32)

    if sw_layer is not None:
        _log("  Breaklines: stehende Gewässer einlesen …")
        extra_pts, extra_z, water_mask, water_elev = _apply_water_polygons(
            sw_layer, arr, water_mask, water_elev,
            e_min, n_max, cell_m, cols, rows, _np, _log)
        if len(extra_pts) > 0:
            points = _np.vstack([points, extra_pts])
            z_vals = _np.concatenate([z_vals, extra_z])
            _log(f"  + {len(extra_pts)} Uferpunkte als TIN-Constraints")

    if fw_layer is not None:
        _log("  Breaklines: Fließgewässer einlesen …")
        fw_pts, fw_z = _apply_river_lines(
            fw_layer, arr, e_min, n_max, cell_m, cols, rows, _np, _log)
        if len(fw_pts) > 0:
            points = _np.vstack([points, fw_pts])
            z_vals = _np.concatenate([z_vals, fw_z])
            _log(f"  + {len(fw_pts)} Flusslinienpunkte als TIN-Constraints")

    if bld_layer is not None:
        _log("  Breaklines: Gebäude-Grundrisse einlesen …")
        bld_pts, bld_z = _apply_building_polygons(
            bld_layer, arr, e_min, n_max, cell_m, cols, rows, _np, _log)
        if len(bld_pts) > 0:
            points = _np.vstack([points, bld_pts])
            z_vals = _np.concatenate([z_vals, bld_z])

    geb_layer = cfg.get("tin_geb_layer")
    if geb_layer is not None:
        _log("  Breaklines: Gebäude-Footprints (LOD-2) …")
        try:
            from osgeo import ogr as _og2, osr as _os2
            geb_pts, geb_z, excl_mask = _apply_building_footprints(
                geb_layer, arr, e_min, n_max, cell_m,
                cols, rows, _np, _og2, _os2, _gd, _log)
            if excl_mask.any():
                keep = ~excl_mask[ys, xs]
                points = points[keep]; z_vals = z_vals[keep]
                _log(f"  - {(~keep).sum()} Punkte unter Gebäuden entfernt")
            if len(geb_pts) > 0:
                points = _np.vstack([points, geb_pts])
                z_vals = _np.concatenate([z_vals, geb_z])
                _log(f"  + {len(geb_pts)} Gebäude-Randpunkte als Constraints")
        except Exception as _eg:
            _log(f"  ⚠ Gebäude: {_eg}")

    # ── TIN via Delaunay-Triangulation + Barizentrische Interpolation ──────
    _log("  Delaunay-Triangulation …")
    interp = _LinNDI(points, z_vals)   # scipy baut intern Delaunay auf

    # Interpolationsgitter (alle Pixelzentren)
    grid_xs = e_min + (_np.arange(cols) + 0.5) * cell_m
    grid_ns = n_max - (_np.arange(rows) + 0.5) * cell_m
    gx, gn  = _np.meshgrid(grid_xs, grid_ns)
    query_pts = _np.column_stack([gx.ravel(), gn.ravel()])

    _log("  Rasterisierung (barizentrisch) …")
    tin_arr = interp(query_pts).reshape(rows, cols).astype(_np.float32)
    # NaN-Bereiche (außerhalb der konvexen Hülle des TIN) mit -9999 füllen
    nodata_mask = _np.isnan(tin_arr)
    tin_arr[nodata_mask] = -9999.0

    # ── Wasserflächen: konstante Höhe aufprägen ────────────────────────────
    if water_mask.any():
        tin_arr[water_mask]      = water_elev[water_mask]
        _log(f"  ✓ {water_mask.sum()} Pixel mit konstanter Gewässerhöhe gefüllt")

    def _write_cog(out_path, data, label):
        tmp = out_path + ".tmp.tif"
        ds  = _gd.GetDriverByName("GTiff").Create(
            tmp, cols, rows, 1, _gd.GDT_Float32,
            ["COMPRESS=DEFLATE", "PREDICTOR=3",
             "TILED=YES", "BLOCKXSIZE=512", "BLOCKYSIZE=512"])
        ds.SetGeoTransform((e_min, cell_m, 0, n_max, 0, -cell_m))
        sr = _os.SpatialReference(); sr.ImportFromEPSG(25832)
        ds.SetProjection(sr.ExportToWkt())
        b = ds.GetRasterBand(1)
        b.WriteArray(data); b.SetNoDataValue(-9999.0)
        ds.FlushCache(); ds = None
        _gd.Translate(out_path, tmp, format="COG",
                      creationOptions=["COMPRESS=DEFLATE", "PREDICTOR=3",
                                       "BLOCKSIZE=512",
                                       "OVERVIEW_RESAMPLING=BILINEAR",
                                       "NUM_THREADS=ALL_CPUS"])
        _osp.remove(tmp)
        _log(f"  ✓ {label} → {out_path}")
        _load_raster(out_path, label)

    # ── Analyse-Output: ungeglättet ────────────────────────────────────────
    out_analyse = base_path + "_tin_analyse.tif"
    _write_cog(out_analyse, tin_arr.copy(), "TIN Analyse")

    # ── Anzeige-Output: Gauß-geglättet ────────────────────────────────────
    out_anzeige = base_path + "_tin_anzeige.tif"
    # Temporär NaN für Gauß-Filterung (scipy filtert NoData sonst mit ein)
    anzeige_arr = tin_arr.copy()
    anzeige_arr[nodata_mask] = _np.nan
    # Gauß-Filter: NaN-Ränder ignorieren via Normalisierungsmaske
    valid_f    = _np.where(nodata_mask, 0.0, 1.0)
    filled     = _np.where(nodata_mask, 0.0, anzeige_arr)
    blurred    = _gauss(filled,  sigma=sigma, mode="reflect")
    weights    = _gauss(valid_f, sigma=sigma, mode="reflect")
    smoothed   = _np.where(weights > 0, blurred / weights, -9999.0).astype(_np.float32)
    smoothed[nodata_mask] = -9999.0
    _write_cog(out_anzeige, smoothed, f"TIN Anzeige (σ={sigma:.1f})")


def _derive_products(cfg, base_path, grid,

                     e_min, n_min, e_max, n_max, cell_m, worker=None):
    """
    Erzeugt aus dem Höhenraster-Grid:
      - DTM          (_dtm.tif,           COG GeoTIFF, EPSG:25832)
      - Schummerung  (_schummerung.tif,   COG GeoTIFF, EPSG:25832)
      - Neigung      (_neigung.tif,       COG GeoTIFF, EPSG:25832)
      - Höhenlinien  (_hoehenlinien.gpkg, Vektorlayer)
    """
    def _log(msg):
        if worker: worker.progress.emit(-1, msg)

    def _load_raster(path, name):
        try:
            from qgis.core import QgsRasterLayer, QgsProject
            lyr = QgsRasterLayer(path, name, "gdal")
            if lyr.isValid():
                QgsProject.instance().addMapLayer(lyr)
        except Exception:
            pass

    try:
        import numpy as _np
        import os as _osp
        from osgeo import gdal as _gd, osr as _os, ogr as _og
    except ImportError:
        _log("⚠ GDAL/numpy fehlt – keine Ableitungen möglich.")
        return

    # ── 1. Zwischen-GeoTIFF aus Grid ─────────────────────────────────────────
    cols = int((e_max - e_min) / cell_m) + 1
    rows = int((n_max - n_min) / cell_m) + 1
    arr  = _np.full((rows, cols), -9999.0, dtype=_np.float32)
    for (col, row), zvals in grid.items():
        if zvals and 0 <= row < rows and 0 <= col < cols:
            arr[rows - 1 - row, col] = float(_np.mean(zvals))

    # Erst als normalen GeoTIFF schreiben (wird für DEMProcessing benötigt)
    tmp_tif = base_path + "_dtm_tmp.tif"
    ds = _gd.GetDriverByName("GTiff").Create(
        tmp_tif, cols, rows, 1, _gd.GDT_Float32,
        ["COMPRESS=DEFLATE", "PREDICTOR=3",
         "TILED=YES", "BLOCKXSIZE=512", "BLOCKYSIZE=512"])
    ds.SetGeoTransform((e_min, cell_m, 0, n_max, 0, -cell_m))
    sr = _os.SpatialReference(); sr.ImportFromEPSG(25832)
    ds.SetProjection(sr.ExportToWkt())
    b = ds.GetRasterBand(1)
    b.WriteArray(arr); b.SetNoDataValue(-9999.0)
    ds.FlushCache(); ds = None

    # Dann zu COG konvertieren (mit Overviews)
    tif = base_path + "_dtm.tif"
    _gd.Translate(tif, tmp_tif, format="COG",
                  creationOptions=[
                      "COMPRESS=DEFLATE", "PREDICTOR=3",
                      "BLOCKSIZE=512",
                      "OVERVIEW_RESAMPLING=BILINEAR",
                      "NUM_THREADS=ALL_CPUS",
                  ])
    import os as _osp
    _osp.remove(tmp_tif)
    _log(f"  ✓ DTM COG → {tif}")

    # ── 2. TIN zuerst – damit Schummerung/Neigung/Höhenlinien lückenlos ──────
    tin_anzeige_tif = None
    if cfg.get("out_tin", False):
        _tin_from_grid(cfg, base_path, arr, cols, rows,
                       e_min, n_max, cell_m, _gd, _os, _np, _log, _load_raster,
                       sw_layer=cfg.get("tin_sw_layer"),
                       fw_layer=cfg.get("tin_fw_layer"),
                       bld_layer=cfg.get("tin_bld_layer"))
        _candidate = base_path + "_tin_anzeige.tif"
        if _osp.path.exists(_candidate):
            tin_anzeige_tif = _candidate
            _log("  → Schummerung/Neigung/Höhenlinien nutzen TIN-Anzeige-Raster")

    # Basis für alle Ableitungen: TIN-Anzeige wenn vorhanden, sonst DTM
    base_tif = tin_anzeige_tif if tin_anzeige_tif else tif

    # Höhenraster-Export: wenn TIN aktiv → analyse-Raster statt lückenhaftem DTM
    if cfg.get("out_hoehenraster") and tin_anzeige_tif:
        tin_analyse_tif = base_path + "_tin_analyse.tif"
        if _osp.path.exists(tin_analyse_tif):
            _load_raster(tin_analyse_tif, "Höhenraster (TIN Analyse)")
            _log("  → Höhenraster aus TIN-Analyse (lückenlos, kein separater Export nötig)")
            # DTM-Export überspringen – TIN ist qualitativ besser
            cfg = dict(cfg); cfg["out_hoehenraster"] = False

    # ── 3. Schummerung ────────────────────────────────────────────────────────
    if cfg.get("out_schummerung", True):
        out = base_path + "_schummerung.tif"
        _log("  Schummerung (315°/45°) → COG …")
        try:
            _gd.DEMProcessing(out + ".tmp.tif", base_tif, "hillshade",
                              azimuth=315, altitude=45, scale=1.0,
                              format="GTiff",
                              creationOptions=["COMPRESS=DEFLATE", "TILED=YES",
                                               "BLOCKXSIZE=512", "BLOCKYSIZE=512"])
            _gd.Translate(out, out + ".tmp.tif", format="COG",
                          creationOptions=["COMPRESS=DEFLATE", "BLOCKSIZE=512",
                                           "OVERVIEW_RESAMPLING=BILINEAR",
                                           "NUM_THREADS=ALL_CPUS"])
            _osp.remove(out + ".tmp.tif")
            _log(f"  ✓ Schummerung COG → {out}")
        except Exception as e:
            _log(f"  ✗ Schummerung: {e}")

    # ── 4. Neigung ─────────────────────────────────────────────────────────────
    if cfg.get("out_neigung", False):
        out = base_path + "_neigung.tif"
        _log("  Neigung (Grad) → COG …")
        try:
            _gd.DEMProcessing(out + ".tmp.tif", base_tif, "slope",
                              scale=1.0, format="GTiff",
                              creationOptions=["COMPRESS=DEFLATE", "TILED=YES",
                                               "BLOCKXSIZE=512", "BLOCKYSIZE=512"])
            _gd.Translate(out, out + ".tmp.tif", format="COG",
                          creationOptions=["COMPRESS=DEFLATE", "BLOCKSIZE=512",
                                           "OVERVIEW_RESAMPLING=BILINEAR",
                                           "NUM_THREADS=ALL_CPUS"])
            _osp.remove(out + ".tmp.tif")
            _log(f"  ✓ Neigung COG → {out}")
        except Exception as e:
            _log(f"  ✗ Neigung: {e}")

    # ── 5. Höhenlinien (aus base_tif) ─────────────────────────────────────────
    if cfg.get("out_hoehenlinien", True):
        eq  = float(cfg.get("equidistanz", 1.0))
        out = base_path + "_hoehenlinien.gpkg"
        _log(f"  Höhenlinien ({eq} m Äquidistanz) …")
        try:
            if _osp.path.exists(out):
                _og.GetDriverByName("GPKG").DeleteDataSource(out)
            ds_o = _og.GetDriverByName("GPKG").CreateDataSource(out)
            sr2  = _os.SpatialReference(); sr2.ImportFromEPSG(25832)
            lyr  = ds_o.CreateLayer(
                "hoehenlinien", sr2, _og.wkbLineString25D)
            fld = _og.FieldDefn("hoehe_m", _og.OFTReal)
            fld.SetWidth(10); fld.SetPrecision(2)
            lyr.CreateField(fld)
            ds_s = _gd.Open(base_tif)
            _gd.ContourGenerate(
                ds_s.GetRasterBand(1),
                eq, 0, [], 1, -9999.0,
                lyr, -1, 0)
            ds_s = None
            ds_o.FlushCache(); ds_o = None
            _log(f"  ✓ Höhenlinien → {out}")
            try:
                from qgis.core import QgsVectorLayer, QgsProject
                l2 = QgsVectorLayer(
                    f"{out}|layername=hoehenlinien",
                    f"Höhenlinien {eq}m (LiDAR)", "ogr")
                if l2.isValid():
                    QgsProject.instance().addMapLayer(l2)
            except Exception:
                pass
        except Exception as e:
            _log(f"  ✗ Höhenlinien: {e}")


def _aggregate_grid(grid: dict,
                    src_cell_m: float,
                    agg_cell_m: float,
                    agg_func:   str = "mean") -> dict:
    """
    Aggregiert ein feines Grid (src_cell_m) auf ein gröberes (agg_cell_m).
    Mehrere Quelll-Zellen werden zu einer Ziel-Zelle zusammengefasst.
    agg_func: 'mean' | 'min' | 'max' | 'median' | 'count' | 'std'
    """
    if agg_cell_m <= src_cell_m:
        return grid
    factor = agg_cell_m / src_cell_m
    raw: dict = {}
    for (col, row), zvals in grid.items():
        if not zvals:
            continue
        key = (int(col / factor), int(row / factor))
        if key not in raw:
            raw[key] = []
        raw[key].extend(zvals)
    result = {}
    for key, zvals in raw.items():
        arr = np.array(zvals, dtype=np.float64)
        if   agg_func == "mean":   v = float(arr.mean())
        elif agg_func == "min":    v = float(arr.min())
        elif agg_func == "max":    v = float(arr.max())
        elif agg_func == "median": v = float(np.median(arr))
        elif agg_func == "count":  v = float(len(arr))
        elif agg_func == "std":    v = float(arr.std())
        else:                      v = float(arr.mean())
        result[key] = [v]
    return result

def _fill_gaps(grid: dict,
               e_min: float, n_min: float,
               e_max: float, n_max: float,
               cell_m: float = 1.0,
               max_search: int = 5) -> dict:
    """
    Füllt leere Zellen per Nearest-Neighbour + IDW aus vorhandenen Nachbarn.
    max_search: maximale Suchradius in Zellen (Standard: 5 m bei 1m-Raster).
    Gibt das ergänzte Grid-Dict zurück.
    """
    if not grid:
        return grid

    # Bounding Box in Zellen
    cols = int((e_max - e_min) / cell_m) + 1
    rows = int((n_max - n_min) / cell_m) + 1

    # Vorhanden-Maske: (col, row) → mittlerer Z-Wert
    known = {key: float(np.mean(zvals))
             for key, zvals in grid.items() if zvals}

    filled = dict(grid)   # Kopie
    n_filled = 0

    for col in range(cols):
        for row in range(rows):
            if (col, row) in known:
                continue   # Bereits vorhanden

            # Nachbarn im Suchradius suchen
            sum_w = 0.0
            sum_wz = 0.0
            for dc in range(-max_search, max_search + 1):
                for dr in range(-max_search, max_search + 1):
                    if dc == 0 and dr == 0:
                        continue
                    nb = (col + dc, row + dr)
                    if nb in known:
                        dist = math.sqrt(dc*dc + dr*dr)
                        w    = 1.0 / (dist * dist)   # IDW: 1/d²
                        sum_w  += w
                        sum_wz += w * known[nb]

            if sum_w > 0:
                z_interp = sum_wz / sum_w
                filled[(col, row)] = [z_interp]
                known[(col, row)]  = z_interp   # für weitere Iterationen
                n_filled += 1

    return filled, n_filled

def _grid_to_features(grid: dict,
                       e_min: float, n_min: float,
                       cell_m: float = 1.0) -> list:
    """
    Wandelt Grid-Dict in Feature-Liste um.
    Jedes Feature: (wkt_polygon, avg, min, max, count)
    """
    features = []
    for (col, row), zvals in grid.items():
        if not zvals:
            continue
        x0 = e_min + col * cell_m
        y0 = n_min + row * cell_m
        x1, y1 = x0 + cell_m, y0 + cell_m
        wkt = (f"POLYGON(({x0} {y0},{x1} {y0},"
               f"{x1} {y1},{x0} {y1},{x0} {y0}))")
        avg  = sum(zvals) / len(zvals)
        zmin = min(zvals)
        zmax = max(zvals)
        features.append((wkt, round(avg, 3), round(zmin, 3),
                          round(zmax, 3), len(zvals)))
    return features


def _grid_to_features_numpy(grid: dict,
                              e_min: float, n_min: float,
                              cell_m: float = 1.0) -> list:
    """Schnellere numpy-Variante."""
    features = []
    for (col, row), zvals in grid.items():
        if not zvals:
            continue
        z    = np.array(zvals)
        x0   = e_min + col * cell_m
        y0   = n_min + row * cell_m
        x1, y1 = x0 + cell_m, y0 + cell_m
        wkt  = (f"POLYGON(({x0} {y0},{x1} {y0},"
                f"{x1} {y1},{x0} {y1},{x0} {y0}))")
        features.append((wkt, round(float(z.mean()), 3),
                          round(float(z.min()), 3),
                          round(float(z.max()), 3), len(z)))
    return features


# ── Worker ────────────────────────────────────────────────────────────────────

