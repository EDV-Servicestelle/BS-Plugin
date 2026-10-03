import os
import tempfile

from qgis.PyQt.QtWidgets import QWizard
from qgis.core import (
    QgsProject,
    QgsCoordinateReferenceSystem,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsDataSourceUri,
    QgsEditorWidgetSetup,
    QgsExpressionContextUtils,
    QgsDefaultValue,
    QgsRelation,
    QgsFeature,
    QgsGeometry,
    QgsWkbTypes,
    QgsVectorFileWriter,
    QgsCoordinateTransform,
    QgsCoordinateTransformContext,
)

from .wizard_pages import (
    PageProjectInfo,
    PageCrsExtent,
    PageUntersuchungsgebiet,
    PagePostGISLayers,
    PageGrundlagen,
    PageSummary,
    PageExportAndUpload,
)
from .fachschalen_config import NRW_WMS_LAYERS
_PLUGIN_DIR = os.path.dirname(__file__)


class NewProjectWizard(QWizard):
    PAGE_INFO    = 0
    PAGE_CRS     = 1
    PAGE_UG      = 2
    PAGE_POSTGIS = 3
    PAGE_GRUNDLAGEN = 4
    PAGE_SUMMARY = 5
    PAGE_EXPORT  = 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Neues QGIS-Projekt anlegen")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.resize(760, 580)

        self.setPage(self.PAGE_INFO,    PageProjectInfo(self))
        self.setPage(self.PAGE_CRS,     PageCrsExtent(self))
        self.setPage(self.PAGE_UG,      PageUntersuchungsgebiet(self))
        self.setPage(self.PAGE_POSTGIS, PagePostGISLayers(self))
        self.setPage(self.PAGE_GRUNDLAGEN, PageGrundlagen(self))
        self.setPage(self.PAGE_SUMMARY, PageSummary(self))
        self.setPage(self.PAGE_EXPORT,  PageExportAndUpload(self))

        # _build_project läuft in PageExportAndUpload.initializePage()


    # ── Projektaufbau ─────────────────────────────────────────────────────────
    def _build_project(self):
        from .debug_log import log, log_exc
        log("_build_project START", context="Wizard")
        pg_page     = self.page(self.PAGE_POSTGIS)
        layers      = pg_page.selected_layers()
        apply_style = pg_page.apply_style()
        conn_params = pg_page._conn_params()
        crs_str     = self.property("_crsAuthId") or "EPSG:25832"
        fachschale  = self.property("_fachschale")
        offline     = self.property("_offlineMode") or False

        project = QgsProject.instance()
        # UG-Quelle (Datei ODER vorhandener Layer) abgreifen, BEVOR project.clear()
        # den ggf. gewählten Quell-Layer aus dem Projekt entfernt.
        _captured_ug = self._capture_ug_source()
        project.clear()
        project.setCrs(QgsCoordinateReferenceSystem(crs_str))
        project.setTitle(self.field("projectName"))

        # ── Projektvariablen ─────────────────────────────────────────────────
        kartierer   = self.field("varKartierer") or ""
        institution = self.field("varInstitution") or ""
        # Nur den kurzname-Teil speichern (vor " – "), falls vorhanden
        def _extract_kurzname(text: str) -> str:
            return text.split(" – ")[0].strip() if " – " in text else text.strip()
        kartierer_val   = _extract_kurzname(kartierer)
        institution_val = _extract_kurzname(institution)
        if kartierer_val and not kartierer_val.startswith("—"):
            QgsExpressionContextUtils.setProjectVariable(project, "kartierer",   kartierer_val)
        if institution_val and not institution_val.startswith("—"):
            QgsExpressionContextUtils.setProjectVariable(project, "institution", institution_val)
        if fachschale:
            QgsExpressionContextUtils.setProjectVariable(project, "fachschale",      fachschale["code"])
            QgsExpressionContextUtils.setProjectVariable(project, "fachschale_name", fachschale["bezeichnung"])
        # Landkreis wird (falls Landnutzung geladen wird) aus dem UG abgeleitet,
        # siehe _detect_landkreis – keine manuelle Auswahl auf Seite 1 mehr.

        root = project.layerTreeRoot()

        # ── Offline-Modus: GeoPackage-Daten direkt aus dem Plugin laden ───────
        gpkg_data = fachschale.get("gpkg_data") if fachschale else None
        if offline and gpkg_data:
            log("Modus: GPKG (offline)", context="Wizard")
            self._build_project_gpkg(project, root, fachschale, gpkg_data)
        else:
            log(f"Modus: PostGIS ({len(layers)} Layer)", context="Wizard")
            # ── PostGIS-Modus ─────────────────────────────────────────────────
            ref_rows  = [r for r in layers if     r["is_ref"]]
            geo_rows  = [r for r in layers if not r["is_ref"]]

            ref_layer_map = {}
            ref_group = root.addGroup("Referenzlisten")
            for r in ref_rows:
                lyr = self._load_postgis_layer(r, conn_params, apply_style)
                if lyr:
                    project.addMapLayer(lyr, addToLegend=False)
                    ref_group.addLayer(lyr)
                    ref_layer_map[r["table"]]             = lyr
                    ref_layer_map[r["table"].capitalize()] = lyr

            fach_group = root.addGroup(
                fachschale["bezeichnung"] if fachschale else "Fachschale"
            )
            for r in geo_rows:
                # Style erst NACH addMapLayer laden (ValueRelation braucht Layer-Registry)
                lyr = self._load_postgis_layer(r, conn_params, False)  # kein Style
                if lyr and lyr.isValid():
                    project.addMapLayer(lyr, addToLegend=False)
                    fach_group.addLayer(lyr)
                    log(f"Layer: {lyr.name()} ({lyr.featureCount()} ft)", context="Wizard")
                    # Jetzt Style laden – Layer ist im Registry
                    if apply_style and r.get("style_qml"):
                        try:
                            import tempfile as _tf
                            with _tf.NamedTemporaryFile(
                                suffix=".qml", mode="w",
                                delete=False, encoding="utf-8"
                            ) as _f:
                                _f.write(r["style_qml"]); _tmp = _f.name
                            lyr.loadNamedStyle(_tmp)
                            try: os.unlink(_tmp)
                            except: pass
                        except Exception: pass
                    # ValueRelations + Defaults NACH Style setzen
                    self._apply_value_relations(lyr, r, ref_layer_map)
                    self._apply_default_values(lyr, r)
                    self._apply_extra_widgets(lyr, r)

            # ── Grenzen-Layer der Fachschale (read-only) ──────────────────────
            # Hinweis: Fachschalen bringen KEIN Untersuchungsgebiet mehr mit –
            # ein UG wird ausschließlich aus der Wizard-Seite erzeugt
            # (siehe _create_ug_layer weiter unten). UG-Template-Einträge
            # (is_ug) werden daher übersprungen, sonst entstünde ein leerer
            # Untersuchungsgebiet-Layer.
            gpkg_data = fachschale.get("gpkg_data") if fachschale else None
            border_entries = [e for e in (gpkg_data or {}).get("border_layers", [])
                              if not e.get("is_ug")]
            if border_entries:
                grenzen_group = root.addGroup("Grenzen")
                for entry in border_entries:
                    lyr = self._load_gpkg_layer(entry)
                    if lyr:
                        lyr.setReadOnly(True)
                        project.addMapLayer(lyr, addToLegend=False)
                        grenzen_group.addLayer(lyr)

            # ── Früher Extent aus einem ggf. bereits in der DB liegenden UG ────
            # (Der vom Nutzer gewählte UG wird unten in _create_ug_layer erzeugt
            #  und überschreibt diesen Extent.)
            if not self.property("_ugExtent"):
                for _l2 in project.mapLayers().values():
                    if "untersuchungsgebiet" in _l2.name().lower():
                        _e2 = _l2.extent()
                        if _e2 and not _e2.isEmpty():
                            self.setProperty("_ugExtent", _e2)
                            break
            # Kein UG definiert → kein Grundlagenabruf (Canvas-Extent wäre zu ungenau)

        # ── Untersuchungsgebiet als eigenen, projektlokalen Layer anlegen ─────
        # Quelle: Datei ODER Layer von der Wizard-Seite (Fachschalen bringen
        # selbst KEIN UG mehr mit). Schreibt ein GeoPackage in den Projekt-
        # ordner, hängt den Layer in den Baum und setzt _ugExtent.
        self._create_ug_layer(project, root, _captured_ug)

        # ── WMS/WMTS-Hintergrundkarten ────────────────────────────────────────
        wms_group = root.addGroup("WMS")
        for wms in NRW_WMS_LAYERS:
            wms_lyr = self._build_wms_layer(wms)
            if wms_lyr and wms_lyr.isValid():
                project.addMapLayer(wms_lyr, addToLegend=False)
                wms_group.addLayer(wms_lyr)

        # ── Grundlagenabruf für UG: FFH, NSG, LSG ────────────────────────────
        ug_extent = self.property("_ugExtent")   # QgsRectangle in EPSG:25832
        if not ug_extent or ug_extent.isEmpty():
            ug_extent = self.property("_projectExtent")
        log(f"UG-Extent: {ug_extent}", context="Wizard")
        if ug_extent and not ug_extent.isEmpty():
            if project.fileName():
                try: project.write()
                except: pass
            gl_page    = self.page(self.PAGE_GRUNDLAGEN)
            selected   = gl_page.selected_dienste() if gl_page else []
            gdb_params = gl_page.conn_params()      if gl_page else None
            log(f"Grundlagen selected={selected} ug_empty={not ug_extent or ug_extent.isEmpty()}", context="Wizard")
            if not selected:
                log("Kein Abruf: keine Dienste gewaehlt", "WARN", context="Wizard")
            elif not ug_extent or ug_extent.isEmpty():
                log("Kein Abruf: UG-Extent fehlt", "WARN", context="Wizard")
            if selected and ug_extent and not ug_extent.isEmpty():
                if gdb_params and gdb_params.get("host"):
                    log("Grundlagen-Pfad: DB (+WFS für DVG)", context="Wizard")
                    self._load_from_grundlagen_db(
                        project, root, ug_extent, gdb_params, selected)
                else:
                    log("Grundlagen-Pfad: WFS", context="Wizard")
                    self._trigger_grundlagen_nrw(
                        project, root, ug_extent, selected)

        # Landnutzung: Landkreis aus UG ableiten
        if ug_extent and not ug_extent.isEmpty():
            kreis_info = self._detect_landkreis(ug_extent, project)
            if kreis_info:
                QgsExpressionContextUtils.setProjectVariable(
                    project, "landkreis",     kreis_info[0])
                QgsExpressionContextUtils.setProjectVariable(
                    project, "landkreis_ags", kreis_info[1])
                self._trigger_nutzung_download(
                    project, root, (kreis_info[1], kreis_info[2]))

    def _detect_landkreis(self, extent, project):
        """Landkreis aus dem UG-Schwerpunkt ableiten (per WFS AX_Kreis)."""
        # Landkreis ausschließlich aus dem UG ableiten (keine manuelle Auswahl mehr).
        if extent is None or extent.isEmpty(): return None
        from qgis.core import (QgsPointXY, QgsCoordinateReferenceSystem,
                               QgsCoordinateTransform)
        pt = QgsCoordinateTransform(
            QgsCoordinateReferenceSystem("EPSG:25832"),
            QgsCoordinateReferenceSystem("EPSG:4326"), project
        ).transform(QgsPointXY(extent.center().x(), extent.center().y()))
        lon, lat = pt.x(), pt.y()
        if not (5.8 <= lon <= 9.5 and 50.3 <= lat <= 52.6): return None
        try:
            import urllib.request, xml.etree.ElementTree as ET
            url = (
                "https://www.wfs.nrw.de/geobasis/wfs_nw_atkis-basis-dlm_aaa-modell-basiert"
                "?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature"
                "&TYPENAMES=adv:AX_Kreis"
                f"&BBOX={lon-0.01},{lat-0.01},{lon+0.01},{lat+0.01},EPSG:4326&COUNT=1"
            )
            root_el = ET.fromstring(urllib.request.urlopen(url, timeout=8).read())
            NS = "http://www.adv-online.de/namespaces/adv/gid/6.0"
            for el in root_el.iter(f"{{{NS}}}schluesselGesamt"):
                ags5 = (el.text or "").strip()
                from .fachschalen_config import get_kreis_by_ags
            result = get_kreis_by_ags(ags5)
            if result: return result
        except Exception: pass
        return None

    def _trigger_grundlagen_nrw(self, project, root, extent, selected=None):
        """
        Startet den Grundlagendaten-Worker asynchron für NSG, LSG, FFH, FFH-LRT.
        Nutzt denselben _GrundlagenWorker wie der manuelle Dialog.
        Layer werden nach Abschluss in die Gruppe Grundlagendaten geladen.
        'selected' (optional) schränkt die abgerufenen Dienste ein.
        """
        from .core.grundlagen import DIENSTE
        from qgis.core import (QgsCoordinateReferenceSystem,
                                QgsCoordinateTransform, QgsVectorLayer)

        ABRUF_DIENSTE = [k for k in (selected or ["nsg", "lsg", "ffh", "ffh_lrt"])
                         if k in DIENSTE]

        # extent → WGS84
        crs_src = QgsCoordinateReferenceSystem("EPSG:25832")
        crs_wgs = QgsCoordinateReferenceSystem("EPSG:4326")
        tr      = QgsCoordinateTransform(crs_src, crs_wgs, project)
        ext_wgs = tr.transformBoundingBox(extent)
        bbox_wgs84 = (ext_wgs.xMinimum(), ext_wgs.yMinimum(),
                      ext_wgs.xMaximum(), ext_wgs.yMaximum())

        # Projektordner aus Wizard-Feld (Export-Seite) oder absolutePath
        # field("gpkgPath") = Exportordner aus letzter Wizard-Seite
        # field("projectFolder") = Projektordner aus erster Seite
        # Denselben Pfad wie der DB-Zweig verwenden, damit WFS- und
        # DB-Grundlagen in einer Datei landen und nur einmal je Lauf
        # zurueckgesetzt wird.
        gpkg_path = self._grundlagen_gpkg_pfad(project)

        grp = root.findGroup("Grundlagendaten") or root.addGroup("Grundlagendaten")

        # Worker konfigurieren – exakt wie GrundlagenDialog
        aktiv = {k: (k in ABRUF_DIENSTE) for k in DIENSTE}

        cfg = {
            "gpkg_path": gpkg_path,
            "bbox_4326": bbox_wgs84,   # Worker erwartet bbox_4326
            "aktiv":     aktiv,
            "timeout":   90,
            # UG-Polygon (EPSG:25832) für ug_filter-Dienste (z. B. DVG)
            "ug_wkt_25832": self.property("_ugWkt25832") or "",
        }

        try:
            from .workers.grundlagen_worker import _GrundlagenWorker
            self._grundlagen_worker = _GrundlagenWorker(cfg)
            # An mainWindow binden damit Worker Wizard-Lebenszyklus ueberlebt
            try:
                from qgis.utils import iface as _ifc
                if _ifc: self._grundlagen_worker.setParent(_ifc.mainWindow())
            except: pass

            def _on_done(ok, msg):
                if not ok:
                    return
                from qgis.core import QgsProject as _QP
                from qgis.utils import iface as _iface
                _proj = _QP.instance()
                _root = _proj.layerTreeRoot()
                _grp  = _root.findGroup("Grundlagendaten") or _root.addGroup("Grundlagendaten")
                for key in ABRUF_DIENSTE:
                    if key not in DIENSTE:
                        continue
                    lbl = DIENSTE[key]["label"]
                    try:
                        lyr = QgsVectorLayer(
                            f"{gpkg_path}|layername={key}", lbl, "ogr")
                        if lyr and lyr.isValid() and lyr.featureCount() > 0:
                            # Zielgruppe: Verwaltungsgrenzen → "Grenzen",
                            # sonst "Grundlagendaten"
                            _gname = DIENSTE[key].get("layer_group") or "Grundlagendaten"
                            _tgt = (_root.findGroup(_gname)
                                    or _root.addGroup(_gname))
                            _proj.addMapLayer(lyr, addToLegend=False)
                            _tgt.addLayer(lyr)
                    except Exception:
                        pass
                _proj.setDirty(True)
                if _proj.fileName():
                    try: _proj.write()
                    except: pass

            from qgis.core import QgsMessageLog as _QML_p
            def _log_progress(_pct, _txt):
                if _txt:
                    _QML_p.logMessage(str(_txt), "NRW Naturschutz", 0)
            self._grundlagen_worker.progress.connect(_log_progress)
            self._grundlagen_worker.finished.connect(_on_done)
            self._grundlagen_worker.finished.connect(
                lambda ok, msg: _QML_p.logMessage(f"fertig: {msg}",
                                                  "NRW Naturschutz", 0))
            _QML_p.logMessage(
                f"WFS-Worker wird gestartet für: {ABRUF_DIENSTE} "
                f"(gpkg={gpkg_path})", "NRW Naturschutz", 0)
            self._grundlagen_worker.start()   # asynchron!

        except Exception as _e:
            from qgis.core import QgsMessageLog
            QgsMessageLog.logMessage(
                f"Grundlagenabruf: {_e}", "NRW Naturschutz", 2)

    def _trigger_nutzung_download(self, project, root, kreis_data: tuple):
        """
        Lädt die aktuelle vereinfachte Landnutzung für den gewählten Landkreis
        von opengeodata.nrw.de und fügt sie als Layer ins Projekt ein.
        URL: .../YYYYMM_gru_vereinf_<AGS>_<name>_epsg25832.gpkg
        Die aktuelle Monatsdatei wird über Listing ermittelt.
        """
        from qgis.core import QgsVectorLayer, QgsMessageLog
        import tempfile, datetime

        ags, kname = kreis_data  # z.B. ("05170040", "wesel")

        base = (
            "https://www.opengeodata.nrw.de/produkte/geobasis/lk/akt/"
            "nutzung_vereinfacht/nutzung_vereinfacht/"
        )

        def _fetch_and_load():
            import urllib.request, os as _os
            # Versuche die letzten 6 Monate (aktuellste verfügbare Datei)
            now = datetime.datetime.now()
            for months_back in range(0, 7):
                dt     = now - datetime.timedelta(days=30 * months_back)
                prefix = dt.strftime("%Y%m")
                fname  = f"{prefix}_gru_vereinf_{ags}_{kname}_epsg25832.gpkg"
                url    = base + fname
                tmp    = _os.path.join(tempfile.gettempdir(), fname)
                try:
                    req = urllib.request.urlopen(url, timeout=60)
                    if req.status == 200:
                        with open(tmp, "wb") as fh:
                            fh.write(req.read())
                        return tmp, fname
                except Exception:
                    continue
            return None, None

        class _NutzungWorker(__import__("qgis.PyQt.QtCore", fromlist=["QThread"]).QThread):
            done = __import__("qgis.PyQt.QtCore", fromlist=["pyqtSignal"]).pyqtSignal(str, str)

            def __init__(self): super().__init__()
            def run(self):
                tmp, fname = _fetch_and_load()
                self.done.emit(tmp or "", fname or "")

        def _on_nutzung_done(tmp_path: str, fname: str):
            if not tmp_path:
                QgsMessageLog.logMessage(
                    "Nutzungsdaten: kein Download verfügbar", "NRW Naturschutz", 1)
                return
            from qgis.core import QgsProject as _QP
            _proj = _QP.instance()
            _root = _proj.layerTreeRoot()
            try:
                import sqlite3 as _sq
                con = _sq.connect(tmp_path)
                tbls = [r[0] for r in con.execute(
                    "SELECT table_name FROM gpkg_geometry_columns"
                ).fetchall()]
                con.close()
                nutz_grp = (_root.findGroup("Landnutzung")
                            or _root.addGroup("Landnutzung"))
                for tbl in tbls:
                    try:
                        lyr = QgsVectorLayer(
                            f"{tmp_path}|layername={tbl}",
                            f"{tbl} ({fname[:6]})", "ogr")
                        if lyr and lyr.isValid():
                            _proj.addMapLayer(lyr, addToLegend=False)
                            nutz_grp.addLayer(lyr)
                    except Exception:
                        pass
                _proj.setDirty(True)
                QgsMessageLog.logMessage(
                    f"Landnutzung geladen: {fname}", "NRW Naturschutz", 0)
            except Exception as _e:
                QgsMessageLog.logMessage(
                    f"Nutzungsdaten Fehler: {_e}", "NRW Naturschutz", 2)

        self._nutzung_worker = _NutzungWorker()
        try:
            from qgis.utils import iface as _ifc2
            if _ifc2: self._nutzung_worker.setParent(_ifc2.mainWindow())
        except: pass
        self._nutzung_worker.done.connect(_on_nutzung_done)
        self._nutzung_worker.start()

    def _grundlagen_gpkg_pfad(self, project) -> str:
        """
        Pfad fuer Grundlagen.gpkg im Projektordner.

        Beim ersten Aufruf je Projektlauf wird eine vorhandene Datei entfernt,
        damit sich Grundlagen aufeinanderfolgender Laeufe nicht aufsummieren
        (_write_to_gpkg haengt an bestehende Layer an).
        """
        proj_path = (self.field("gpkgPath") or
                     self.field("projectFolder") or "").strip()
        if not proj_path:
            proj_path = project.absolutePath()
        if not proj_path:
            import tempfile
            proj_path = tempfile.mkdtemp(prefix="naturschutz_")
        os.makedirs(proj_path, exist_ok=True)
        pfad = os.path.join(proj_path, "Grundlagen.gpkg")

        if not self.property("_grundlagenGpkgFrisch"):
            if os.path.exists(pfad):
                try:
                    os.remove(pfad)
                except OSError:
                    pass          # in Benutzung: dann wird angehaengt
            self.setProperty("_grundlagenGpkgFrisch", True)
        return pfad

    def _load_from_grundlagen_db(self, project, root, extent, conn_params: dict, selected=None):
        """Lädt Schutzgebiete + ATKIS aus zentraler Grundlagen-DB per ST_Intersects."""
        from .grundlagen_db_dialog import fetch_from_grundlagen_db, GRUNDLAGEN_DIENSTE
        from .core.grundlagen import DIENSTE, _write_to_gpkg
        from qgis.core import QgsVectorLayer, QgsCoordinateReferenceSystem
        from .debug_log import log
        import tempfile

        ABRUF = selected if selected else [
            "nsg", "lsg", "ffh",
            "atkis_gewaesserachse", "atkis_gewaesser_fliessend", "atkis_wald"
        ]

        # Dienste aufteilen: in der Grundlagen-DB vorhanden vs. WFS-only
        # (z. B. DVG-Verwaltungsgrenzen liegen nicht in der DB).
        db_keys  = [k for k in ABRUF if k in GRUNDLAGEN_DIENSTE]
        wfs_only = [k for k in ABRUF if k not in GRUNDLAGEN_DIENSTE and k in DIENSTE]

        # UG-Polygon (EPSG:25832) – falls vorhanden, werden die DB-Grundlagen
        # serverseitig darauf geclippt (statt nur per Bounding-Box gefiltert).
        ug_wkt = self.property("_ugWkt25832") or None
        if ug_wkt and db_keys:
            log("Grundlagen werden auf UG-Polygon geclippt", context="Wizard")
        feats_by_key = (fetch_from_grundlagen_db(conn_params, extent, db_keys,
                                                 ug_wkt=ug_wkt)
                        if db_keys else {})

        # WFS-Abruf bestimmen: immer die WFS-only-Dienste (DVG); zusätzlich die
        # DB-Dienste, falls die DB nichts geliefert hat. _trigger_grundlagen_nrw
        # nur EINMAL aufrufen (sonst überschreibt sich der Worker).
        wfs_keys = list(wfs_only)
        if db_keys and not any(feats_by_key.values()):
            wfs_keys += [k for k in db_keys if k in DIENSTE]
        if wfs_keys:
            self._trigger_grundlagen_nrw(project, root, extent, wfs_keys)

        if not any(feats_by_key.values()):
            return

        crs = QgsCoordinateReferenceSystem("EPSG:25832")
        # Grundlagen in den PROJEKTORDNER schreiben, nicht in das gemeinsame
        # Temp-Verzeichnis: _write_to_gpkg haengt an vorhandene Layer an, sodass
        # sich in einer geteilten Temp-Datei die Grundlagen mehrerer Projekte
        # aufsummieren. Ausserdem wird die Datei nur so zuverlaessig mit in das
        # Projektpaket bzw. zu QFieldCloud uebernommen.
        gpkg = self._grundlagen_gpkg_pfad(project)
        grp  = root.findGroup("Grundlagendaten") or root.addGroup("Grundlagendaten")

        for key, feats in feats_by_key.items():
            if not feats or key not in DIENSTE:
                continue
            try:
                _write_to_gpkg(gpkg, key, feats, DIENSTE[key], crs, append=True)
                lbl = DIENSTE[key]["label"]
                lyr = QgsVectorLayer(f"{gpkg}|layername={key}", lbl, "ogr")
                if lyr.isValid() and lyr.featureCount() > 0:
                    project.addMapLayer(lyr, addToLegend=False)
                    grp.addLayer(lyr)
            except Exception:
                pass

    # ── Offline-Projektaufbau aus mitgelieferten GeoPackages ─────────────────
    def _build_project_gpkg(self, project, root, fachschale, gpkg_data):
        """
        Baut das Projekt vollständig aus den im Plugin enthaltenen GeoPackages auf.
        Keine Datenbankverbindung erforderlich.
        Struktur: <Fachschale> | Grenzen | Referenzlisten
        """

        # 1. Referenzlisten (müssen zuerst geladen werden für ValueRelations)
        ref_layer_map = {}  # layername → QgsVectorLayer
        ref_group = root.addGroup("Referenzlisten")
        for entry in gpkg_data.get("ref_layers", []):
            lyr = self._load_gpkg_layer(entry)
            if lyr:
                project.addMapLayer(lyr, addToLegend=False)
                ref_group.addLayer(lyr)
                ref_layer_map[entry["layername"]] = lyr

        # 2. Erfassungs-/Geo-Layer (mit ValueRelation-Widgets)
        fach_group = root.addGroup(fachschale.get("bezeichnung", "Fachschale"))
        for entry in gpkg_data.get("geo_layers", []):
            lyr = self._load_gpkg_layer(entry)
            if lyr:
                # ValueRelations aus der Fachschalen-Konfiguration anwenden
                matching_row = next(
                    (gl for gl in fachschale.get("geo_layers", [])
                     if gl["table"].lower() == entry["layername"].lower()),
                    None,
                )
                if matching_row:
                    self._apply_value_relations(lyr, matching_row, ref_layer_map)
                    self._apply_default_values(lyr, matching_row)
                    self._apply_extra_widgets(lyr, matching_row)
                project.addMapLayer(lyr, addToLegend=False)
                fach_group.addLayer(lyr)

        # 3. Grenzen-Layer (schreibgeschützt, eigene Gruppe)
        #    UG-Template-Einträge (is_ug) überspringen – das UG kommt aus
        #    _create_ug_layer; sonst entstünde ein leerer UG-Layer.
        border_layers = [e for e in gpkg_data.get("border_layers", [])
                         if not e.get("is_ug")]
        if border_layers:
            grenzen_group = root.addGroup("Grenzen")
            for entry in border_layers:
                lyr = self._load_gpkg_layer(entry)
                if lyr:
                    lyr.setReadOnly(True)
                    project.addMapLayer(lyr, addToLegend=False)
                    grenzen_group.addLayer(lyr)

        # 4. QGIS-Relationen registrieren
        # Beziehungen aus GPKG-Daten ODER aus Fachschalen-Config
        relations = []
        if gpkg_data:
            relations = gpkg_data.get("relations", [])
        if fachschale and not relations:
            relations = fachschale.get("layer_relations", [])
        if relations:
            all_layers = {**ref_layer_map}
            for node in root.findLayers():
                lyr = node.layer()
                if lyr:
                    all_layers[lyr.name()]        = lyr
                    all_layers[lyr.name().lower()] = lyr
            self._apply_relations(project, all_layers, relations)
            log(f"{len(relations)} Beziehung(en) registriert", context="Wizard")

        # Hinweis: Das Untersuchungsgebiet wird NICHT mehr hier behandelt –
        # es wird zentral in _build_project via _create_ug_layer() als eigener,
        # projektlokaler Layer erzeugt (Quelle: Wizard-Seite, Datei ODER Layer).

    # ── Einzelnen GeoPackage-Layer laden ─────────────────────────────────────
    def _load_gpkg_layer(self, entry: dict) -> QgsVectorLayer | None:
        """
        Lädt einen Layer aus einem GeoPackage, das relativ zum Plugin-Verzeichnis liegt.

        entry-Keys:
            gpkg       – Pfad relativ zu _PLUGIN_DIR  (z. B. 'data/biotopbaum/Erfassung.gpkg')
            layername  – Tabellenname im GeoPackage
            display    – Anzeigename im Layer-Panel (optional, Fallback: layername)
        """
        gpkg_rel  = entry["gpkg"]
        layername = entry["layername"]
        display   = entry.get("display", layername)

        gpkg_abs = os.path.join(_PLUGIN_DIR, gpkg_rel)
        if not os.path.isfile(gpkg_abs):
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage(
                f"GPKG fehlt: {gpkg_abs}",
                "NRW Naturschutz-Toolbox", Qgis.MessageLevel.Warning)
            return None

        uri = f"{gpkg_abs}|layername={layername}"
        lyr = QgsVectorLayer(uri, display, "ogr")
        if not lyr.isValid():
            return None
        # Lädt den als default markierten Stil aus der layer_styles-Tabelle im GPKG
        lyr.loadDefaultStyle()
        return lyr

    # ── Layer aus PostGIS laden ───────────────────────────────────────────────
    def _load_postgis_layer(self, r: dict, conn_params: dict,
                             apply_style: bool):
        uri = QgsDataSourceUri()
        uri.setConnection(
            conn_params["host"],
            str(conn_params["port"]),
            conn_params["dbname"],
            conn_params["user"],
            conn_params["password"],
        )
        geom_col = r.get("geom_col") or ""
        # PostgreSQL speichert ohne Quotes als lowercase (ogr2ogr -nln lowercase)
        # PostgreSQL-Tabellen werden von ogr2ogr lowercase geschrieben
        uri.setDataSource(r["schema"], r["table"].lower(), geom_col)

        # Anzeigename: ursprünglicher CamelCase-Name
        layer = QgsVectorLayer(uri.uri(False), r.get("label", r["table"]), "postgres")
        if not layer.isValid():
            return None

        return layer

    # ── ValueRelation-Widgets setzen ─────────────────────────────────────────
    def _apply_value_relations(self, layer: QgsVectorLayer,
                                row: dict, ref_layer_map: dict):
        """
        Setzt ValueRelation-EditWidgets für alle konfigurierten Felder.
        Erhält dabei kaskadierende Filter (z. B. Artname → Artengruppe).
        Funktioniert für PostGIS- und GeoPackage-Layer gleichermaßen,
        da ref_layer_map in beiden Fällen layername → QgsVectorLayer enthält.
        """
        vr_config = row.get("value_relations", {})
        if not vr_config:
            return

        fields = layer.fields()
        for field_name, cfg in vr_config.items():
            idx = fields.indexFromName(field_name)
            if idx < 0:
                continue

            ref_table = cfg["ref_table"]
            ref_layer = (ref_layer_map.get(ref_table)
                         or ref_layer_map.get(ref_table.lower())
                         or next((v for k,v in ref_layer_map.items()
                                  if k.lower() == ref_table.lower()), None))
            if ref_layer is None:
                continue

            # Alle Werte müssen valide sein – None crasht QVariant-Konversion in C++
            widget_config = {
                "Layer":               ref_layer.id(),
                "LayerName":           ref_layer.name(),
                "LayerSource":         ref_layer.source(),
                "LayerProviderName":   ref_layer.providerType(),
                "Key":                 cfg.get("key", ""),
                "Value":               cfg.get("value", ""),
                "AllowMulti":          bool(cfg.get("allow_multi", False)),
                "AllowNull":           bool(cfg.get("allow_null", True)),
                "FilterExpression":    cfg.get("filter", "") or "",
                "OrderByValue":        bool(cfg.get("order_by_value", False)),
                "UseCompleter":        bool(cfg.get("use_completer", False)),
                "CompleterMatchFlags": int(cfg.get("completer_match_flags", 2)),
                "NofColumns":          int(cfg.get("nof_columns", 1)),
                "DisplayGroupName":    False,
            }
            try:
                setup = QgsEditorWidgetSetup("ValueRelation", widget_config)
                layer.setEditorWidgetSetup(idx, setup)
            except Exception as _vr_e:
                from wizard_pages import WizardBuildLog
                WizardBuildLog.add(f"ValueRelation {field_name}: {_vr_e}", "WARN")

    # ── Default-Werte für Felder setzen ──────────────────────────────────────
    @staticmethod
    def _schuetze_fid(layer: QgsVectorLayer):
        """
        Setzt das Feld fid schreibgeschuetzt und blendet es im Formular aus.

        Ein versehentlich geaenderter Primaerschluessel zerreisst die
        Verknuepfung zu Anhaengen, Relationen und Altdatenbezuegen; der Wert
        wird ausschliesslich von der Datenbank vergeben.
        """
        try:
            idx = layer.fields().indexFromName("fid")
            if idx < 0:
                return
            cfg = layer.editFormConfig()
            cfg.setReadOnly(idx, True)
            layer.setEditFormConfig(cfg)
            layer.setEditorWidgetSetup(idx, QgsEditorWidgetSetup("Hidden", {}))
        except Exception:
            pass          # Schutz ist optional, darf den Projektbau nie stoppen

    def _apply_default_values(self, layer: QgsVectorLayer, row: dict):
        """
        Setzt Default-Expressions für Felder eines Layers.
        Koordinatenfelder (Utm_east/Utm_north bzw. x/y) werden automatisch
        aus der Geometrie befüllt. apply_on_update=True stellt sicher, dass
        die Werte bei jeder Geometrieänderung neu berechnet werden.
        """
        # Primaerschluessel gegen versehentliches Bearbeiten schuetzen -
        # unabhaengig davon, ob der Layer eine Stildatei mitbringt.
        self._schuetze_fid(layer)

        defaults = row.get("default_values", {})
        if not defaults:
            return
        fields = layer.fields()
        for field_name, cfg in defaults.items():
            idx = fields.indexFromName(field_name)
            if idx < 0:
                continue
            dv = QgsDefaultValue(
                cfg["expression"],
                cfg.get("apply_on_update", False),
            )
            layer.setDefaultValueDefinition(idx, dv)

    # ── UG-Quelle abgreifen (VOR project.clear) ──────────────────────────────
    def _capture_ug_source(self):
        """
        Liest die UG-Quelle von der Wizard-Seite (Datei ODER vorhandener Layer)
        und kopiert deren Geometrien in einen projektunabhängigen Memory-Layer.
        Muss vor project.clear() laufen, da ein gewählter Quell-Layer sonst
        bereits aus dem Projekt entfernt wäre.
        Rückgabe: (memory_layer | None, kennung)
        """
        from .debug_log import log
        ug_page = self.page(self.PAGE_UG)
        if not ug_page or not hasattr(ug_page, "ug_source"):
            return None, ""
        kind, src, kennung = ug_page.ug_source()
        if kind is None:
            log("UG: keine Quelle angegeben", context="Wizard")
            return None, kennung

        if kind == "file":
            src_layer = QgsVectorLayer(src, "ug_src", "ogr")
        else:  # "layer"
            src_layer = src
        if (src_layer is None or not src_layer.isValid()
                or src_layer.featureCount() == 0):
            log(f"UG-Quelle ungültig oder leer ({kind})", "WARN", context="Wizard")
            return None, kennung

        src_crs = src_layer.crs().authid() or "EPSG:25832"
        wkb     = QgsWkbTypes.displayString(src_layer.wkbType()) or "Polygon"
        mem = QgsVectorLayer(
            f"{wkb}?crs={src_crs}&field=KENNUNG:string(80)",
            "Untersuchungsgebiet", "memory")
        if not mem.isValid():
            log(f"UG-Memory-Layer ungültig (wkb={wkb})", "WARN", context="Wizard")
            return None, kennung
        dp   = mem.dataProvider()
        kidx = mem.fields().indexFromName("KENNUNG")
        out  = []
        for f in src_layer.getFeatures():
            nf = QgsFeature(mem.fields())
            nf.setGeometry(f.geometry())
            if kidx >= 0 and kennung:
                nf.setAttribute(kidx, kennung)
            out.append(nf)
        dp.addFeatures(out)
        mem.updateExtents()
        log(f"UG-Quelle abgegriffen: {kind}, {mem.featureCount()} Feature(s), "
            f"CRS {src_crs}", context="Wizard")
        return mem, kennung

    # ── UG als projektlokalen GPKG-Layer erzeugen + in Baum hängen ────────────
    def _create_ug_layer(self, project, root, captured):
        """
        Schreibt die abgegriffene UG-Geometrie als eigenes GeoPackage in den
        Projektordner (Reprojektion ins Projekt-KRS), lädt sie als Layer
        'Untersuchungsgebiet', hängt sie in die Gruppe 'Grenzen' und merkt sich
        Extent + GPKG-Pfad (Letzteres für den QFieldCloud-Upload).
        """
        from .debug_log import log
        mem, _kennung = (captured if captured else (None, ""))
        if mem is None or not mem.isValid() or mem.featureCount() == 0:
            return

        proj_path = (self.field("gpkgPath") or
                     self.field("projectFolder") or "").strip()
        if not proj_path:
            proj_path = project.absolutePath()
        if not proj_path:
            proj_path = tempfile.mkdtemp(prefix="naturschutz_")
        try:
            os.makedirs(proj_path, exist_ok=True)
        except Exception:
            pass
        gpkg_path = os.path.join(proj_path, "Untersuchungsgebiet.gpkg")

        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName   = "GPKG"
        opts.layerName    = "Untersuchungsgebiet"
        opts.fileEncoding = "UTF-8"
        opts.actionOnExistingFile = (
            QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile)
        if mem.crs() != project.crs():
            opts.ct = QgsCoordinateTransform(mem.crs(), project.crs(), project)

        res = QgsVectorFileWriter.writeAsVectorFormatV3(
            mem, gpkg_path, project.transformContext(), opts)
        err = res[0] if isinstance(res, (tuple, list)) else res
        if err != QgsVectorFileWriter.WriterError.NoError:
            msg = res[1] if isinstance(res, (tuple, list)) and len(res) > 1 else err
            log(f"UG-GPKG schreiben fehlgeschlagen: {msg}", "WARN", context="Wizard")
            return

        ug = QgsVectorLayer(f"{gpkg_path}|layername=Untersuchungsgebiet",
                            "Untersuchungsgebiet", "ogr")
        if not ug.isValid():
            log("UG-Layer nach Schreiben ungültig", "WARN", context="Wizard")
            return
        ug.setReadOnly(True)
        project.addMapLayer(ug, addToLegend=False)
        grp = root.findGroup("Grenzen") or root.addGroup("Grenzen")
        grp.insertLayer(0, ug)

        ext = ug.extent()
        if ext and not ext.isEmpty():
            self.setProperty("_ugExtent", ext)
        self.setProperty("_ugGpkgPath", gpkg_path)

        # UG-Polygon (vereinigt) in EPSG:25832 für das Clipping der
        # Grundlagendaten merken (siehe _load_from_grundlagen_db).
        try:
            geoms = [f.geometry() for f in ug.getFeatures() if f.hasGeometry()]
            if geoms:
                dissolved = QgsGeometry.unaryUnion(geoms)
                crs_25832 = QgsCoordinateReferenceSystem("EPSG:25832")
                if ug.crs() != crs_25832:
                    dissolved.transform(
                        QgsCoordinateTransform(ug.crs(), crs_25832, project))
                if dissolved and not dissolved.isEmpty():
                    self.setProperty("_ugWkt25832", dissolved.asWkt())
        except Exception as _e:
            log(f"UG-WKT (25832) konnte nicht erzeugt werden: {_e}",
                "WARN", context="Wizard")

        log(f"UG-Layer erstellt: {gpkg_path} ({ug.featureCount()} Feature(s))",
            context="Wizard")

        # ── QGIS-Relationen (Beziehungsmanager) setzen ───────────────────────────
    def _apply_relations(self, project: QgsProject, layer_map: dict, relations: list):
        """
        Registriert QGIS-Relationen im Projektrelationsmanager.

        layer_map: layername -> QgsVectorLayer (alle geladenen Layer).
        Als Fallback wird QgsProject.mapLayersByName() verwendet, damit
        Layer auch dann gefunden werden wenn der Anzeigename vom table-Namen
        abweicht.

        strength  'Composition' = Eltern-Kind (z. B. Ortsbewegungen, Simultanmarker)
                  'Association' = lose FK-Verknüpfung (Standard)
        """
        rel_mgr = project.relationManager()

        strength_map = {
            "Composition": QgsRelation.RelationStrength.Composition,
            "Association": QgsRelation.RelationStrength.Association,
        }

        for rel_def in relations:
            # Layer zuerst aus übergebenem layer_map, dann aus Projektregistry
            def _find(name):
                lyr = layer_map.get(name)
                if lyr and lyr.isValid():
                    return lyr
                candidates = project.mapLayersByName(name)
                return candidates[0] if candidates else None

            ref_ing = _find(rel_def["referencing_layer"])
            ref_ed  = _find(rel_def["referenced_layer"])
            if ref_ing is None or ref_ed is None:
                continue

            rel = QgsRelation()
            rel.setId(rel_def["id"])
            rel.setName(rel_def["name"])
            rel.setReferencingLayer(ref_ing.id())
            rel.setReferencedLayer(ref_ed.id())
            rel.addFieldPair(rel_def["referencing_field"], rel_def["referenced_field"])

            strength_key = rel_def.get("strength", "Association")
            rel.setStrength(strength_map.get(strength_key,
                            QgsRelation.RelationStrength.Association))

            # Relation immer hinzufügen; isValid() wird als Warnung geloggt
            rel_mgr.addRelation(rel)

            # ── Relation-Editor-Widget auf dem referenzierten (Eltern-)Layer ──
            # Composition-Relationen brauchen ein RelationReference-Widget auf
            # dem referencing (Kind-)Layer damit das Beobachtungsformular
            # direkt verknüpfte Einträge anlegen kann.
            if not rel.isValid():
                continue

            # 1. RelationReference-Widget auf dem Kind-Layer (referencing)
            #    → zeigt die verknüpfte Beobachtung im Formular des Markers
            ref_ing_fields = ref_ing.fields()
            fk_idx = ref_ing_fields.indexFromName(rel_def["referencing_field"])
            if fk_idx >= 0:
                # Association (Artname, Kartiergang): editierbar
                # Composition (FK auf Elternobjekt): read-only
                _is_comp = (strength_key == "Composition")
                ref_widget_cfg = {
                    "Relation":            rel.id(),
                    "ReferencedLayerId":   ref_ed.id(),
                    "AllowNULL":           True,
                    "ReadOnly":            _is_comp,
                    "AllowAddFeatures":    False,
                    "ShowOpenFormButton":  not _is_comp,
                    "MapIdentification":   False,
                    "OrderByValue":        True,
                    "FilterExpression":    "",
                    "FilterFields":        [],
                }
                ref_ing.setEditorWidgetSetup(
                    fk_idx,
                    QgsEditorWidgetSetup("RelationReference", ref_widget_cfg)
                )

            # 2. RelationEditor-Widget auf dem Eltern-Layer (referenced)
            #    → zeigt verknüpfte Kind-Features editierbar im Elternformular
            #    Nur für Composition (strenge Eltern-Kind-Beziehung)
            if strength_key == "Composition":
                # Feld "uuid" / vb_uuid am Eltern-Layer
                pk_idx = ref_ed.fields().indexFromName(rel_def["referenced_field"])
                if pk_idx >= 0:
                    editor_cfg = {
                        "relation":                 rel.id(),
                        "nm-rel":                   "",
                        "one_to_one":               False,
                        "allow_add_child_feature":  True,
                        "allow_duplicate_child_feature": False,
                        "allow_delete_child_feature": True,
                        "link_existing_features":   False,
                        "show_save_child_edits_button": True,
                        "force_suppress_popup":     False,
                    }
                    # Widget auf dem Eltern-Layer-Feld setzen
                    ref_ed.setEditorWidgetSetup(
                        pk_idx,
                        QgsEditorWidgetSetup("RelationEditor", editor_cfg)
                    )
                    # Außerdem: Tabs im Elternformular aktivieren damit
                    # der Relation-Editor als Tab erscheint
                    try:
                        ec = ref_ed.editFormConfig()
                        ec.setLayout(
                            ec.EditorLayout.TabLayout
                            if hasattr(ec, "TabLayout")
                            else 1  # TabLayout = 1
                        )
                        ref_ed.setEditFormConfig(ec)
                    except Exception:
                        pass

    # ── Zusätzliche Widget-Typen setzen (Range, CheckBox …) ─────────────────
    def _apply_extra_widgets(self, layer: QgsVectorLayer, row: dict):
        """
        Setzt Widget-Typen wie Range (Spinner) oder CheckBox aus extra_widgets-Config.
        """
        extra = row.get("extra_widgets", {})
        if not extra:
            return
        fields = layer.fields()
        for field_name, cfg in extra.items():
            idx = fields.indexFromName(field_name)
            if idx < 0:
                continue
            wtype = cfg.get("type", "")
            if wtype == "Range":
                widget_config = {
                    "Min":              cfg.get("min", 0),
                    "Max":              cfg.get("max", 2147483647),
                    "Step":             cfg.get("step", 1),
                    "AllowNull":        True,
                    "Suffix":           "",
                    "Style":            "SpinBox",
                }
                layer.setEditorWidgetSetup(
                    idx, QgsEditorWidgetSetup("Range", widget_config)
                )
            elif wtype == "CheckBox":
                widget_config = {
                    "CheckedState":   str(cfg.get("checked",   True)),
                    "UncheckedState": str(cfg.get("unchecked", False)),
                    "TextDisplayMethod": 0,
                }
                layer.setEditorWidgetSetup(
                    idx, QgsEditorWidgetSetup("CheckBox", widget_config)
                )

        # ── WMS/WMTS-Layer aufbauen ───────────────────────────────────────────────
    def _build_wms_layer(self, cfg: dict):
        if cfg["type"] == "wmts":
            uri = (
                f"crs={cfg['crs']}"
                f"&dpiMode=7"
                f"&featureCount=10"
                f"&format={cfg['format']}"
                f"&layers={cfg['layer']}"
                f"&styles={cfg.get('style','default')}"
                f"&tileMatrixSet={cfg.get('tilematrixset','EPSG_25832_16')}"
                f"&tilePixelRatio=0"
                f"&url={cfg['url']}"
            )
            return QgsRasterLayer(uri, cfg["name"], "wms")
        else:
            # WMS
            uri = (
                f"crs={cfg['crs']}"
                f"&dpiMode=7"
                f"&featureCount=10"
                f"&format={cfg['format']}"
                f"&layers={cfg['layer']}"
                f"&styles"
                f"&url={cfg['url']}"
            )
            return QgsRasterLayer(uri, cfg["name"], "wms")
