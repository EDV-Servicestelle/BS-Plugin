"""
Schritt 1: Layer als GeoPackage exportieren (Vektor + Referenzlisten)
Schritt 2: QGIS-Projekt speichern (referenziert GPKG, ValueRelations umpfaden)
Schritt 3: Projekt zu QFieldCloud hochladen
"""

import os
import shutil
from qgis.PyQt.QtCore import QThread, pyqtSignal
from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsVectorFileWriter,
    QgsCoordinateTransformContext,
    QgsEditorWidgetSetup,
)


# ════════════════════════════════════════════════════════════════════════════
# Schritt 1 – GeoPackage-Export
# ════════════════════════════════════════════════════════════════════════════

def export_layers_to_gpkg(
    layers: list,
    gpkg_path: str,
    progress_cb=None,
) -> dict:
    """
    Exportiert alle Vektor-Layer in ein GeoPackage.
    Gibt {layer_name: neue QgsVectorLayer auf GPKG} zurück.
    """
    result_layers = {}

    for i, layer in enumerate(layers):
        if progress_cb:
            progress_cb(i, f"Exportiere {layer.name()} …")

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName           = "GPKG"
        options.layerName            = layer.name()
        options.fileEncoding         = "UTF-8"
        options.actionOnExistingFile = (
            QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
        )

        error, msg, _, _ = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer,
            gpkg_path,
            QgsCoordinateTransformContext(),
            options,
        )

        if error != QgsVectorFileWriter.WriterError.NoError:
            raise RuntimeError(
                f"GPKG-Export '{layer.name()}' fehlgeschlagen: {msg}"
            )

        gpkg_uri  = f"{gpkg_path}|layername={layer.name()}"
        new_layer = QgsVectorLayer(gpkg_uri, layer.name(), "ogr")

        if layer.renderer():
            new_layer.setRenderer(layer.renderer().clone())
        if layer.labeling():
            new_layer.setLabeling(layer.labeling().clone())

        # EditWidget-Konfiguration übertragen (inkl. ValueRelation-Typ,
        # Pfade werden in save_project() auf GPKG umgebogen)
        for idx in range(layer.fields().count()):
            setup = layer.editorWidgetSetup(idx)
            new_layer.setEditorWidgetSetup(idx, setup)

        result_layers[layer.name()] = new_layer

    if progress_cb:
        progress_cb(len(layers), "GeoPackage fertig.")

    return result_layers


# ════════════════════════════════════════════════════════════════════════════
# Schritt 1b – Quell-GPKGs in Projektordner kopieren
# ════════════════════════════════════════════════════════════════════════════

def collect_and_copy_geopackages(
    project: "QgsProject",
    dest_dir: str,
    progress_cb=None,
) -> dict:
    """
    Sammelt alle einzigartigen GPKG-Quelldateien aller Vektor-Layer im Projekt,
    kopiert sie in dest_dir und gibt {alter_pfad: neuer_pfad} zurück.

    Dieser Ansatz vermeidet OGR-Dateisperr-Probleme beim Layer-für-Layer-Export
    und ist konsistent mit dem QFieldSync-Workflow.
    """
    # Mögliche Basispfade für relative Pfad-Auflösung:
    # 1. Projektordner (wenn Projekt schon gespeichert)
    # 2. Plugin-Verzeichnis (Layer direkt aus Plugin-Data geladen)
    # 3. aktuelles Arbeitsverzeichnis
    search_roots = []
    if project.fileName():
        search_roots.append(os.path.dirname(project.fileName()))
    # Plugin-eigene data/-Verzeichnisse (Layer werden aus Plugin-Dir geladen)
    try:
        from qgis.core import QgsApplication
        import glob
        plugin_paths = QgsApplication.pluginPath().split(";")
        for pp in plugin_paths:
            for data_dir in glob.glob(os.path.join(pp, "*/data/**"), recursive=False):
                if os.path.isdir(data_dir):
                    search_roots.append(data_dir)
            # Direkt: plugins/qgis_new_project_plugin_v152/data/
            candidate = os.path.join(pp, "qgis_new_project_plugin_v152", "data")
            if os.path.isdir(candidate):
                search_roots.append(candidate)
    except Exception:
        pass
    search_roots.append(os.getcwd())

    def _resolve(path: str) -> str:
        """Löst relativen oder absoluten Pfad auf; gibt existierenden abs. Pfad zurück."""
        if os.path.isabs(path) and os.path.isfile(path):
            return path
        for root in search_roots:
            candidate = os.path.normpath(os.path.join(root, path))
            if os.path.isfile(candidate):
                return candidate
        return path   # unverändert zurück (isfile-Check schlägt dann fehl)

    # Quell-GPKGs ermitteln
    gpkg_sources = {}   # abspfad → set(layer_names)
    for layer in project.mapLayers().values():
        if not isinstance(layer, QgsVectorLayer):
            continue
        source = layer.source()
        if "|layername=" not in source:
            continue
        raw_path = source.split("|layername=")[0]
        gpkg_path = _resolve(raw_path)
        if not os.path.isfile(gpkg_path):
            if progress_cb:
                progress_cb(-1, f"  ⚠ nicht gefunden: {raw_path}")
            continue
        if gpkg_path not in gpkg_sources:
            gpkg_sources[gpkg_path] = set()
        gpkg_sources[gpkg_path].add(layer.name())

    copied = {}
    for i, (src_path, layer_names) in enumerate(gpkg_sources.items()):
        filename = os.path.basename(src_path)
        dst_path = os.path.join(dest_dir, filename)

        # Liegt die Quelle bereits im Zielordner (z. B. Grundlagen.gpkg, das
        # direkt in den Projektordner geschrieben wurde), darf nicht auf sich
        # selbst kopiert werden - shutil wirft sonst SameFileError.
        if os.path.abspath(src_path) == os.path.abspath(dst_path):
            if progress_cb:
                progress_cb(i, f"  {filename} liegt bereits im Projektordner")
            copied[src_path] = dst_path
            continue

        if progress_cb:
            progress_cb(i, f"Kopiere {filename} …")

        shutil.copy2(src_path, dst_path)
        copied[src_path] = dst_path

    if progress_cb:
        progress_cb(len(gpkg_sources), f"{len(gpkg_sources)} GPKG(s) kopiert.")

    return copied


def relink_project_to_local_geopackages(
    project: "QgsProject",
    path_map: dict,
    project_path: str,
):
    """
    Aktualisiert alle Layer-Quellen im Projekt auf die kopierten lokalen GPKGs
    und schreibt das Projekt.
    path_map: {alter_absoluter_gpkg_pfad: neuer_absoluter_gpkg_pfad}
    """
    # Normalisiere path_map-Keys für Windows/Linux-Vergleich
    norm_map = {os.path.normpath(k): v for k, v in path_map.items()}

    for layer in project.mapLayers().values():
        if not isinstance(layer, QgsVectorLayer):
            continue
        source = layer.source()
        if "|layername=" not in source:
            continue
        old_gpkg      = source.split("|layername=")[0]
        old_gpkg_norm = os.path.normpath(old_gpkg)
        new_gpkg      = norm_map.get(old_gpkg_norm)
        if new_gpkg:
            new_source = source.replace(old_gpkg, new_gpkg, 1)
            layer.setDataSource(
                new_source, layer.name(), layer.providerType()
            )
            # ValueRelation-Quellen aktualisieren
            fields = layer.fields()
            for idx in range(fields.count()):
                setup = layer.editorWidgetSetup(idx)
                if setup.type() != "ValueRelation":
                    continue
                cfg = dict(setup.config())
                src = cfg.get("LayerSource", "")
                if src and "|layername=" in src:
                    ref_raw  = src.split("|layername=")[0]
                    ref_norm = os.path.normpath(ref_raw)
                    ref_new  = norm_map.get(ref_norm)
                    if ref_new:
                        cfg["LayerSource"] = src.replace(ref_raw, ref_new, 1)
                        layer.setEditorWidgetSetup(
                            idx, QgsEditorWidgetSetup("ValueRelation", cfg)
                        )

    # Relative Pfade erzwingen: QField braucht ./datei.gpkg, nicht C:\...
    dest_dir = os.path.dirname(project_path)
    try:
        from qgis.core import Qgis
        project.setHomePath(dest_dir)
        project.setFilePathStorage(Qgis.FilePathType.Relative)
    except Exception:
        pass   # Ältere QGIS-Version ohne FilePathType
    project.write(project_path)


# ════════════════════════════════════════════════════════════════════════════
# Schritt 2 – Projekt speichern + ValueRelations auf GPKG umpfaden
# ════════════════════════════════════════════════════════════════════════════

def save_project(
    project: QgsProject,
    project_path: str,
    gpkg_layers: dict,
):
    """
    Tauscht PostGIS-Layer gegen GPKG-Layer aus,
    pfadet ValueRelation-Layer-IDs auf die neuen GPKG-Layer um
    und speichert das Projekt.
    """
    root    = project.layerTreeRoot()
    old_ids = list(project.mapLayers().keys())

    # Layer-Name → neue Layer-ID (für ValueRelation-Umpfadung)
    new_id_map = {}

    # Alte Vektor-Layer entfernen, neue GPKG-Layer einsetzen
    for lid in old_ids:
        old = project.mapLayer(lid)
        if old and isinstance(old, QgsVectorLayer):
            new_id_map[old.name()] = None   # Platzhalter
            project.removeMapLayer(lid)

    for name, layer in gpkg_layers.items():
        project.addMapLayer(layer, addToLegend=False)
        root.addLayer(layer)
        new_id_map[name] = layer.id()

    # ValueRelations umpfaden: Layer-ID der Referenztabelle aktualisieren
    for name, layer in gpkg_layers.items():
        fields = layer.fields()
        changed = False
        for idx in range(fields.count()):
            setup = layer.editorWidgetSetup(idx)
            if setup.type() != "ValueRelation":
                continue
            cfg = dict(setup.config())
            old_layer_name = cfg.get("LayerName", "")
            new_id = new_id_map.get(old_layer_name)
            if new_id and cfg.get("Layer") != new_id:
                cfg["Layer"] = new_id
                # Quelle auf GPKG aktualisieren
                ref_layer = project.mapLayer(new_id)
                if ref_layer:
                    cfg["LayerSource"]       = ref_layer.source()
                    cfg["LayerProviderName"] = "ogr"
                layer.setEditorWidgetSetup(idx, QgsEditorWidgetSetup("ValueRelation", cfg))
                changed = True

    project.write(project_path)


# ════════════════════════════════════════════════════════════════════════════
# Schritt 3 – QFieldCloud-Upload (Worker-Thread)
# ════════════════════════════════════════════════════════════════════════════

class QFieldCloudUploader(QThread):
    progress    = pyqtSignal(int, str)
    finished_ok = pyqtSignal(str)
    error       = pyqtSignal(str)

    CLOUD_URL = "https://app.qfield.cloud/api/v1"

    def __init__(self, username, password, project_name, project_path,
                 upload_files=None, organization="", parent=None):
        super().__init__(parent)
        self.username     = username
        self.password     = password
        self.project_name = project_name
        self.project_path = project_path
        # upload_files: Liste aller hochzuladenden Dateien (Projekt + GPKGs)
        # Deduplizieren, Projekt zuerst
        seen = set()
        files = []
        for f in ([project_path] + (upload_files or [])):
            if f not in seen and os.path.isfile(f):
                seen.add(f)
                files.append(f)
        self.upload_files = files
        self.organization = organization

    def run(self):
        try:
            import requests

            # 1. Login: User/Passwort → Token
            self.progress.emit(3, "Anmelden …")
            token = self._login(requests)
            headers = {"Authorization": f"Token {token}"}

            # 2. Cloud-Projekt anlegen/ermitteln
            self.progress.emit(5, "Prüfe Cloud-Projekt …")
            cloud_id = self._ensure_project(headers, requests)

            # 3. Dateien hochladen
            files = self.upload_files
            for i, fp in enumerate(files):
                self.progress.emit(
                    int(10 + i / max(len(files), 1) * 70),
                    f"Lade hoch: {os.path.basename(fp)} ({i+1}/{len(files)})"
                )
                self._upload_file(headers, cloud_id, fp, requests)

            self.progress.emit(90, "Synchronisiere …")
            self._trigger_package(headers, cloud_id, requests)

            url = f"https://app.qfield.cloud/projects/{cloud_id}"
            self.progress.emit(100, "Fertig.")
            self.finished_ok.emit(url)

        except Exception as exc:
            self.error.emit(str(exc))

    def _login(self, requests) -> str:
        """Authentifiziert mit Benutzername + Passwort, gibt Token zurück."""
        resp = requests.post(
            f"{self.CLOUD_URL}/auth/token/",
            json={"username": self.username, "password": self.password},
            timeout=15,
        )
        if resp.status_code == 400:
            raise RuntimeError("Anmeldung fehlgeschlagen: "
                               "Benutzername oder Passwort falsch.")
        resp.raise_for_status()
        data = resp.json()
        token = data.get("token") or data.get("auth_token") or data.get("key")
        if not token:
            raise RuntimeError(f"Kein Token in der Antwort: {data}")
        return token

    def _ensure_project(self, headers, requests):
        # Eigenen Benutzernamen für Owner-Vergleich ermitteln
        me_resp = requests.get(f"{self.CLOUD_URL}/auth/user/",
                               headers=headers, timeout=15)
        me_resp.raise_for_status()
        me = me_resp.json().get("username", self.username)

        # Gültiger Owner: eigener Account ODER angegebene Organisation
        valid_owners = {me}
        if self.organization:
            valid_owners.add(self.organization)

        # Existierendes EIGENES Projekt suchen (paginiert)
        url = f"{self.CLOUD_URL}/projects/"
        while url:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            # API gibt Liste oder paginiertes Objekt zurück
            items = data if isinstance(data, list) else data.get("results", [])
            for p in items:
                # owner kann String (username) ODER Dict {"username":...} sein
                raw_owner = p.get("owner") or ""
                if isinstance(raw_owner, dict):
                    owner = raw_owner.get("username", "")
                else:
                    owner = str(raw_owner)
                if p.get("name") == self.project_name and owner in valid_owners:
                    return p["id"]
            url = None if isinstance(data, list) else data.get("next")

        # Neues Projekt anlegen
        payload = {"name": self.project_name,
                   "description": "Erstellt via QGIS-Plugin",
                   "is_public": False}
        if self.organization:
            payload["owner"] = self.organization
        resp = requests.post(f"{self.CLOUD_URL}/projects/",
                             headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        return resp.json()["id"]

    def _upload_file(self, headers, project_id, filepath, requests):
        filename = os.path.basename(filepath)
        url = f"{self.CLOUD_URL}/files/{project_id}/{filename}/"
        with open(filepath, "rb") as fh:
            resp = requests.post(
                url, headers=headers,
                files={"file": (filename, fh, "application/octet-stream")},
                timeout=120,
            )
        if resp.status_code == 403:
            raise RuntimeError(
                f"Keine Schreibberechtigung für Projekt {project_id}.\n"
                "Prüfen Sie: Ist die angegebene Organisation korrekt? "
                "Haben Sie Eigentümer-Rechte auf dieses Cloud-Projekt?"
            )
        resp.raise_for_status()

    def _trigger_package(self, headers, project_id, requests):
        resp = requests.post(
            f"{self.CLOUD_URL}/jobs/",
            headers=headers,
            json={"type": "package", "project_id": project_id},
            timeout=30,
        )
        if resp.status_code not in (200, 201):
            resp.raise_for_status()
