"""
workers/grundlagen_worker.py - GrundlagenWorker QThread
"""
from qgis.PyQt.QtCore import QThread, pyqtSignal
from qgis.core import (
    QgsCoordinateReferenceSystem, QgsVectorLayer, QgsProject,
    QgsVectorFileWriter, QgsFields, QgsField, QgsFeature,
    QgsGeometry, QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant
try:
    from qgis_new_project_plugin.core.grundlagen import (DIENSTE, _REQUESTS_OK, _GDAL_OK, _QGIS_OK, _fetch_wfs, _fetch_ogcapi, _fetch_ffh_lrt, _fetch_atkis_wfs, _fetch_dvg_geojson, _fetch_lod2_ogcapi, _write_to_gpkg, _fetch_lod2)
except ImportError:
    from ..core.grundlagen import (DIENSTE, _REQUESTS_OK, _GDAL_OK, _QGIS_OK, _fetch_wfs, _fetch_ogcapi, _fetch_ffh_lrt, _fetch_atkis_wfs, _fetch_dvg_geojson, _fetch_lod2_ogcapi, _write_to_gpkg, _fetch_lod2, _compute_missing_centerlines)
# noop — *

class _GrundlagenWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._abort = False

    def abort(self): self._abort = True

    def run(self):
        try:
            self._fetch()
        except Exception as e:
            import traceback
            self.finished.emit(False, f"✗ {e}\n{traceback.format_exc()[:600]}")

    def _fetch(self):
        cfg        = self.config
        gpkg_path  = cfg["gpkg_path"]
        bbox_wgs84 = cfg["bbox_4326"]
        aktiv      = cfg["aktiv"]     # {"schutzgebiete": True, ...}
        timeout    = cfg.get("timeout", 60)
        crs        = QgsCoordinateReferenceSystem("EPSG:25832")

        # UG-Polygon (EPSG:25832) für ug_filter-Dienste (z. B. DVG):
        # nur Objekte behalten, die das UG tatsächlich schneiden.
        ug_wkt  = cfg.get("ug_wkt_25832", "") or ""
        ug_geom = QgsGeometry.fromWkt(ug_wkt) if ug_wkt else None
        if ug_geom is not None and ug_geom.isEmpty():
            ug_geom = None

        # Direktes Log (umgeht das progress-Signal, das via lokalem Slot
        # ggf. nicht zuverlässig verbunden ist).
        from qgis.core import QgsMessageLog as _QML
        def _ml(_m, _lvl=0):
            try: _QML.logMessage(str(_m), "NRW Naturschutz", _lvl)
            except Exception: pass
        _ml(f"Worker START – aktive Dienste: "
            f"{[k for k, v in aktiv.items() if v]}; "
            f"UG-Polygon: {'ja' if ug_geom is not None else 'nein'}")

        n_dienste = sum(1 for k, v in aktiv.items() if v)
        done = 0
        self._fliess_feats = []
        self._sw_feats     = []
        self._achse_feats  = []   # leer wenn Achse nicht aktiv

        for dienst_key, dienst_cfg in DIENSTE.items():
            if not aktiv.get(dienst_key, False):
                continue
            if self._abort:
                self.finished.emit(False, "Abgebrochen."); return

            self.progress.emit(
                int(done / n_dienste * 90),
                f"► {dienst_cfg['label']} …")

            try:
                typ = dienst_cfg["typ"]
                if typ == "ffh_lrt":
                    features = _fetch_ffh_lrt(dienst_cfg, bbox_wgs84, timeout)
                elif typ == "wfs":
                    features = _fetch_wfs(dienst_cfg, bbox_wgs84, timeout)
                elif typ in ("atkis_wfs", "atkis_wfs_multi"):
                    features = _fetch_atkis_wfs(dienst_cfg, bbox_wgs84, timeout)
                elif typ == "dvg_geojson":
                    features = _fetch_dvg_geojson(dienst_cfg, bbox_wgs84, timeout)
                elif typ == "lod2_ogcapi":
                    features = _fetch_lod2_ogcapi(dienst_cfg, bbox_wgs84, timeout)
                elif typ == "lod2":
                    n = _fetch_lod2(dienst_cfg, bbox_wgs84, gpkg_path, self)
                    self.progress.emit(-1, f"  ✓ {n} Gebäude (CityGML)")
                    continue
                else:
                    features = _fetch_ogcapi(dienst_cfg, bbox_wgs84, timeout)

                # UG-Filter: nur Objekte behalten, die das UG mit nennenswerter
                # Fläche schneiden. Schwelle = Anteil der KLEINEREN Fläche
                # (UG vs. Objekt): für DVG (Kreis ≫ UG) bleibt es ≈ %-UG, für
                # ATKIS-Objekte (≪ UG) greift der Objekt-Anteil → kein
                # fälschliches Verwerfen kleiner Flächen; Splitter fallen raus.
                if dienst_cfg.get("ug_filter") and ug_geom is not None and features:
                    _before  = len(features)
                    _ug_area = ug_geom.area() or 0.0
                    _min_frac = 0.01
                    _kept = []
                    for _ft in features:
                        _g = QgsGeometry.fromWkt(_ft.get("wkt", ""))
                        if not _g or _g.isEmpty() or not _g.intersects(ug_geom):
                            continue
                        _keep = True
                        if _ug_area > 0 and _g.type() == QgsWkbTypes.PolygonGeometry:
                            try:
                                _feat_area = _g.area() or 0.0
                                _ref = min(_ug_area, _feat_area) if _feat_area > 0 else _ug_area
                                _inter = ug_geom.intersection(_g)
                                _a = _inter.area() if _inter and not _inter.isEmpty() else 0.0
                                _keep = (_a >= _min_frac * _ref)
                            except Exception:
                                _keep = True
                        if _keep:
                            _kept.append(_ft)
                    # Fail-Safe: Entfernt der Filter ALLE Objekte (obwohl welche
                    # da waren), liegt fast sicher eine Geometrie-/CRS-Abweichung
                    # vor (Objekte landen außerhalb des UG). Dann lieber
                    # ungefiltert behalten als nichts anzeigen.
                    if _before > 0 and len(_kept) == 0:
                        _ml(f"{dienst_key}: UG-Filter hätte alle {_before} entfernt "
                            f"→ behalte ungefiltert (CRS/Geometrie prüfen)", 1)
                        self.progress.emit(-1,
                            f"  UG-Filter übersprungen ({_before} behalten, 0 Treffer)")
                    else:
                        features = _kept
                        self.progress.emit(-1,
                            f"  UG-Filter: {len(features)}/{_before} behalten")

                self.progress.emit(-1,
                    f"  {len(features)} Features empfangen")

                # Diagnose: tatsächlich gefundene Attributnamen protokollieren
                if features and (dienst_cfg.get("felder_all") or dienst_cfg.get("debug_fields")):
                    _keys = list((features[0].get("props", {}) or {}).keys())
                    self.progress.emit(-1,
                        f"  Attribute: {', '.join(_keys) if _keys else '(keine gefunden)'}")
                _ml(f"{dienst_key}: {len(features)} Features; Attribute="
                    f"{list((features[0].get('props', {}) or {}).keys()) if features else []}")

                n = _write_to_gpkg(
                    gpkg_path, dienst_key,
                    features, dienst_cfg, crs)
                role = dienst_cfg.get("breakline_role", "")
                # Gewässerachse separat: für Centerline-Berechnung
                if dienst_key == "atkis_gewaesserachse":
                    self._achse_feats = features
                    # Achse auch als Fließgewässer-Breakline
                    self._fliess_feats.extend(features)
                elif role == "fliessgewaesser":
                    self._fliess_feats.extend(features)
                elif role == "stehendes_gewaesser":
                    self._sw_feats.extend(features)  # alle stehenden inkl. Hafenbecken
                if dienst_key == "atkis_gewaesserachse": self._achse_feats = features

                self.progress.emit(-1,
                    f"  ✓ {n} Features → {dienst_key}")

                # Layer in QGIS laden
                uri = f"{gpkg_path}|layername={dienst_key}"
                lyr = QgsVectorLayer(uri, dienst_cfg["label"], "ogr")
                if lyr.isValid():
                    QgsProject.instance().addMapLayer(lyr)
                _ml(f"{dienst_key}: ✓ {n} Features geschrieben, "
                    f"Layer gültig={lyr.isValid()}")

            except Exception as e:
                import traceback
                self.progress.emit(-1, f"  ✗ {dienst_cfg['label']}: {e}")
                self.progress.emit(-1, f"    {traceback.format_exc().splitlines()[-1]}")
                _ml(f"✗ {dienst_cfg.get('label', dienst_key)}: {e} | "
                    f"{traceback.format_exc().splitlines()[-1]}", 2)

            done += 1
        _ml(f"Worker FERTIG → {gpkg_path}")

        # Centerlines für breite Fließgewässer ohne Mittelachse
        if self._fliess_feats:
            self.progress.emit(95, "Berechne Centerlines (Rhein etc.) …")
            try:
                cl_feats = _compute_missing_centerlines(
                    self._fliess_feats, self._achse_feats)
            except Exception as _ce:
                cl_feats = []
                self.progress.emit(96, f"  ⚠ Centerline-Fehler: {_ce}")
            if cl_feats:
                # Eigener Layer für berechnete Mittelachsen
                cl_cfg = dict(DIENSTE["atkis_gewaesserachse"])
                cl_cfg["label"] = "ATKIS – Berechnete Gewässermittelachsen"
                _write_to_gpkg(gpkg_path, "atkis_gewaessermittelachse",
                               cl_feats, cl_cfg, crs, append=False)
                self.progress.emit(97, f"  + {len(cl_feats)} Centerlines → atkis_gewaessermittelachse")
        self.progress.emit(100, "")
        self.finished.emit(True,
            f"✓ Grundlagendaten gespeichert → {gpkg_path}")


# ── Dialog ────────────────────────────────────────────────────────────────────

