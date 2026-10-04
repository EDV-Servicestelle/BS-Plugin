"""core/luftbild.py - NRW DOP WCS-Download und COG-Erstellung"""
import os, math, re, tempfile, shutil
try:
    import requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

try:
    from osgeo import gdal
    gdal.UseExceptions()
    _GDAL_OK = True
except ImportError:
    _GDAL_OK = False

try:
    from qgis.core import (QgsProject, QgsCoordinateReferenceSystem,
                           QgsCoordinateTransform, QgsCoordinateTransformContext,
                           QgsPointXY, QgsRasterLayer)
    _QGIS_OK = True
except ImportError:
    _QGIS_OK = False

WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")
UTM32 = QgsCoordinateReferenceSystem("EPSG:25832")

WCS_URL = "https://www.wcs.nrw.de/geobasis/wcs_nw_dop"

# Bekannte Coverage-Namen – werden der Reihe nach probiert
WCS_COVERAGE_CANDIDATES = [
    "nw_dop_rgb",
    "nw_dop",
    "nw_dop10_rgb",
    "nw_dop10",
    "WCS_NW_DOP",
    "dop_nw",
]

BLOCK_M  = 2000  # 2×2 km Blöcke → 4× weniger WCS-Requests als 1×1 km
BLOCK_PX = 2000  # px pro Block: 2km/2000px = 100cm/Pixel
DEFAULT_ZOOMS = [16, 18]


# ── Koordinaten ───────────────────────────────────────────────────────────────

def _wgs84_to_utm32(lon_min, lat_min, lon_max, lat_max):
    tr = QgsCoordinateTransform(WGS84, UTM32, QgsCoordinateTransformContext())
    sw = tr.transform(QgsPointXY(lon_min, lat_min))
    ne = tr.transform(QgsPointXY(lon_max, lat_max))
    return sw.x(), sw.y(), ne.x(), ne.y()


def _blocks(e_min, n_min, e_max, n_max, bm=BLOCK_M):
    e0 = int(e_min // bm) * bm
    n0 = int(n_min // bm) * bm
    result = []
    e = e0
    while e < e_max:
        n = n0
        while n < n_max:
            result.append((e, n, min(e+bm, e_max), min(n+bm, n_max)))
            n += bm
        e += bm
    return result


# ── Coverage-Autodiscovery ────────────────────────────────────────────────────

def _discover_coverage(wcs_url: str):
    """Fragt GetCapabilities ab. Gibt (coverage_name, format_string) zurueck."""
    if not _REQUESTS_OK:
        return (WCS_COVERAGE_CANDIDATES[0], "image/jpeg")
    try:
        r = requests.get(wcs_url, params={
            "SERVICE": "WCS", "VERSION": "1.0.0",
            "REQUEST": "GetCapabilities",
        }, timeout=20)
        if r.status_code != 200:
            return (WCS_COVERAGE_CANDIDATES[0], "image/jpeg")
        xml = r.text
        # Coverage-Name
        coverage = WCS_COVERAGE_CANDIDATES[0]
        for cand in WCS_COVERAGE_CANDIDATES:
            if cand in xml:
                coverage = cand
                break
        # Formate
        fmt_matches = []
        for pat in [r"<formats>([^<]+)</formats>",
                    r"<Format>([^<]+)</Format>",
                    r"<SupportedFormat[^>]*>([^<]+)</SupportedFormat>"]:
            fmt_matches += re.findall(pat, xml)
        fmt = "image/jpeg"
        for f in fmt_matches:
            fl = f.lower().strip()
            if "jpeg" in fl or "jpg" in fl:
                fmt = f.strip()
                break
        return (coverage, fmt)
    except Exception:
        pass
    return (WCS_COVERAGE_CANDIDATES[0], "image/jpeg")


# ── WCS-Download ──────────────────────────────────────────────────────────────

def _parse_wcs_error(xml_bytes: bytes) -> str:
    try:
        text = xml_bytes.decode("utf-8", errors="replace")
        m = re.search(r'<[^>]*ExceptionText[^>]*>([^<]+)<', text)
        if m: return m.group(1).strip()
        m = re.search(r'msWCS[^<]{0,200}', text)
        if m: return m.group(0)[:150]
        return text[200:400].strip()
    except Exception:
        return "(XML-Parse fehlgeschlagen)"



def _georeference_block(src_path: str,
                        e0, n0, e1, n1,
                        width: int, height: int) -> str:
    """
    Fügt einer heruntergeladenen Bilddatei (JPEG) die UTM32-Georeferenz hinzu.
    outputBounds: (ulx, uly, lrx, lry) = (xmin, ymax, xmax, ymin)
    """
    if not _GDAL_OK:
        return src_path

    from osgeo import gdal
    ds_src = gdal.Open(src_path)
    if ds_src is None:
        return src_path
    # Schon korrekt georeferenziert? (default geotransform = Identity)
    gt = ds_src.GetGeoTransform()
    already_georef = (gt[1] != 1.0 or gt[5] != 1.0)
    ds_src = None

    if already_georef:
        return src_path

    # Zieldatei: immer _geo.tif Suffix um .tif.tif zu vermeiden
    base = src_path.rsplit(".", 1)[0]
    geo_path = base + "_geo.tif"

    ds_out = gdal.Translate(
        geo_path, src_path,
        outputSRS="EPSG:25832",
        # GDAL: outputBounds = (ulx, uly, lrx, lry) = (xmin, ymax, xmax, ymin)
        outputBounds=[e0, n1, e1, n0],
        format="GTiff",
        creationOptions=["COMPRESS=JPEG", "JPEG_QUALITY=85",
                         "TILED=YES", "BLOCKXSIZE=512", "BLOCKYSIZE=512"],
    )
    if ds_out:
        ds_out.FlushCache(); ds_out = None
        return geo_path
    return src_path


def _fetch_wcs_block(e0, n0, e1, n1, tmp_dir,
                     coverage=None, wcs_format="image/jpeg",
                     px=BLOCK_PX, timeout=90):
    if coverage is None:
        coverage = WCS_COVERAGE_CANDIDATES[0]

    fname  = os.path.join(tmp_dir, f"block_{e0}_{n0}.tif")
    width  = px
    height = max(1, int((n1-n0)/(e1-e0)*px))
    res    = (e1-e0) / px

    variants = [
        # WCS 1.0.0 – GeoTIFF
        {
            "SERVICE":    "WCS", "VERSION":  "1.0.0",
            "REQUEST":    "GetCoverage",
            "COVERAGE":   coverage,
            "CRS":        "EPSG:25832",
            "BBOX":       f"{e0},{n0},{e1},{n1}",
            "WIDTH":      width, "HEIGHT": height,
            "FORMAT":     wcs_format,
        },
        # WCS 1.0.0 – image/tiff
        {
            "SERVICE":      "WCS", "VERSION":    "1.0.0",
            "REQUEST":      "GetCoverage",
            "COVERAGE":     coverage,
            "CRS":          "EPSG:25832",
            "RESPONSE_CRS": "EPSG:25832",
            "BBOX":         f"{e0},{n0},{e1},{n1}",
            "WIDTH":        width, "HEIGHT": height,
            "FORMAT":       "image/tiff",
        },
        # WCS 1.1.1
        {
            "SERVICE":     "WCS", "VERSION":   "1.1.1",
            "REQUEST":     "GetCoverage",
            "IDENTIFIER":  coverage,
            "FORMAT":      "image/tiff",
            "BOUNDINGBOX": f"{e0},{n0},{e1},{n1},urn:ogc:def:crs:EPSG::25832",
            "GRIDBASECRS": "urn:ogc:def:crs:EPSG::25832",
            "GRIDCS":      "urn:ogc:def:cs:OGC:0.0:Grid2dSquareCS",
            "GRIDTYPE":    "urn:ogc:def:method:WCS:1.1:2dGridIn2dCrs",
            "GRIDOFFSETS": f"{res},{res}",
            "GRIDORIGIN":  f"{e0},{n1}",
        },
    ]

    last_err = ""
    for params in variants:
        try:
            r = requests.get(WCS_URL, params=params, timeout=timeout)
            ct = r.headers.get("Content-Type", "")
            if r.status_code == 200 and ("tiff" in ct or "image" in ct
                                          or "octet" in ct):
                with open(fname, "wb") as f:
                    f.write(r.content)
                if os.path.getsize(fname) > 5_000:
                    # Georeferenzierung hinzufügen falls nötig (JPEG hat keine)
                    geo_fname = _georeference_block(
                        fname, e0, n0, e1, n1, px, height)
                    return geo_fname, None
                last_err = f"Antwort zu klein"
            elif "xml" in ct.lower() or b"xml" in r.content[:50].lower():
                last_err = f"WCS-Fehler: {_parse_wcs_error(r.content)[:120]}"
                break   # Gleicher Fehler für alle Varianten
            else:
                last_err = f"HTTP {r.status_code}, CT={ct[:40]}"
        except Exception as ex:
            last_err = str(ex)[:80]

    return None, f"Block {e0}/{n0}: {last_err}"


# ── Worker ────────────────────────────────────────────────────────────────────

