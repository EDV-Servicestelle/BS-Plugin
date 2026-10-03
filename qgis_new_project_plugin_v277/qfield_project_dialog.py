"""
QField-Projekt erstellen
========================
Erzeugt ein QField-optimiertes QGIS-Projekt für eine Fachschale.

Optimierungen:
  • Tab-Layout pro Layer: „Schnell" (Pflichtfelder) + „Details" + Auto-Felder
  • Auto-Felder (UUID, Koordinaten, Zeitstempel) ausgeblendet – werden per
    Default-Expression gefüllt
  • QFieldSync-Metadaten gesetzt (offline / no_action pro Layer)
  • WMS-Layer als Hintergrund markiert (no_action = kein Offline-Download)
"""

import os
import shutil

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QGroupBox,
    QTextEdit, QDialogButtonBox, QFileDialog, QCheckBox,
)
from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsCoordinateReferenceSystem,
    QgsEditFormConfig,
    QgsAttributeEditorContainer,
    QgsAttributeEditorField,
    QgsEditorWidgetSetup,
    QgsDefaultValue,
    QgsRelation,
    QgsExpressionContextUtils,
)

_PLUGIN_DIR = os.path.dirname(__file__)

# ── Formular-Layout-Definitionen je Fachschale + Layer ───────────────────────
# Felder die NICHT aufgeführt sind werden als "Auto" behandelt (unsichtbar)

FORM_LAYOUTS = {
    "fundpunkte_tiere": {
        "Fund": {
            "tabs": [
                {
                    "name":   "Pflichtangaben",
                    "fields": ["Artengruppe", "Artname", "Artname_deutsch",
                               "Artname_wiss", "Beobachtungsdatum"],
                },
                {
                    "name":   "Optionalen Angaben",
                    "fields": ["Anzahl", "Zaehleinheit", "Status",
                               "Stadium", "Geschlecht", "Fundort", "Bemerkung"],
                },
                {
                    "name":   "Stammdaten",
                    "fields": ["Kartierer", "Institution"],
                },
                {
                    "name":   "Systemdaten",
                    "fields": ["Kennung", "Eingabedatum", "Aenderungsdatum",
                               "Utm_east", "Utm_north"],
                },
            ],
            "hidden":   ["fid"],
            # fid zusaetzlich schreibgeschuetzt: 'hidden' entfernt das Feld nur
            # aus dem Formular, in der Attributtabelle waere es sonst weiterhin
            # editierbar - ein versehentlich geaenderter Primaerschluessel
            # zerreisst die Verknuepfung zu Anhaengen und Altdatenbezuegen.
            "readonly": ["fid", "Artname_deutsch", "Artname_wiss",
                         "Kennung", "Utm_east", "Utm_north",
                         "Eingabedatum", "Aenderungsdatum"],
        },
    },
    "biotopbaum": {
        "Baueme": {
            "tabs": [
                {
                    "name":   "Baum",
                    "fields": ["baumart", "baumtyp", "bhd", "hoehe", "K_Datum"],
                },
                {
                    "name":   "Zustand",
                    "fields": ["Besonnung", "vitalitaet", "zersetzung",
                               "Baumpilze", "baumhoehlen", "anz_baumhoehlen"],
                },
                {
                    "name":   "Lage",
                    "fields": ["posi_Lage", "standort\n"],
                },
                {
                    "name":   "Details",
                    "fields": ["sonderstruk", "bem_sonderstruk", "foerderung",
                               "markierung", "markierung_bem\n", "besitzart",
                               "adrolle", "terminart",
                               "Verkehrssicherungspflicht",
                               "Kartierer", "Institution", "allg_bem\n"],
                },
            ],
            "hidden": ["fid", "Objektid", "x", "y",
                       "Aenderungsdatum", "akkumulat"],
        },
    },
    "brutvogel": {
        "Vogelbeobachtungen": {
            "tabs": [
                {
                    "name":   "Beobachtung",
                    "fields": ["Vogel_Art", "Anzahl", "Verhalten",
                               "Stadium_Geschlecht",
                               "Zeitstempel_Beobachtung"],
                },
                {
                    "name":   "Details",
                    "fields": ["Brutzeitcode", "Brutstatus", "Bemerkung",
                               "Genauigkeit", "kartiergang",
                               "nachtraeglich_erfasst"],
                },
            ],
            "hidden": ["fid", "vb_uuid", "Zeitstempel_Digitalisierung",
                       "Zeitstempel_letzteAenderung",
                       "BearbeiterIn_letzteAenderung",
                       "geometry_type", "anzeigename"],
        },
        "Begehungsliste": {
            "tabs": [
                {
                    "name":   "Begehung",
                    "fields": ["Kartiergang", "Erfasser", "Witterung",
                               "Zeitstempel_Start", "Zeitstempel_Ende"],
                },
                {
                    "name":   "Details",
                    "fields": ["Kartierer", "Institution"],
                },
            ],
            "hidden": ["fid", "uuid", "Datum", "anzeigename",
                       "zeit_plausi"],
        },
        "Ortsbewegungen": {
            "tabs": [
                {
                    "name":   "Erfassung",
                    "fields": ["vb_uuid", "Bewegung_Art", "Bemerkung"],
                },
            ],
            "hidden": ["fid", "ob_uuid", "Zeitstempel_Digitalisierung",
                       "Zeitstempel_Beobachtung", "Vogel_Art_1"],
        },
        "Simultanmarker": {
            "tabs": [
                {
                    "name":   "Erfassung",
                    "fields": ["vb_uuid", "vb2_uuid", "Simultan_Art",
                               "Bemerkung"],
                },
            ],
            "hidden": ["fid", "sim_uuid", "vb2_Vogel_Art",
                       "Vogel_Art_1", "Zeitstempel_Digitalisierung",
                       "Zeitstempel_Beobachtung"],
        },
    },
}

# QFieldSync-Aktionen pro Layer-Typ
# "offline"   = Layer wird für Offline-Bearbeitung kopiert
# "no_action" = Layer bleibt online (WMS/WMTS, Grenzen)
QFIELD_ACTIONS = {
    "editable":   "offline",
    "reference":  "offline",   # Ref-Listen auch offline für ValueRelation
    "border":     "no_action",
    "wms":        "no_action",
}


# ── Hilfsfunktion: Form-Layout setzen ────────────────────────────────────────

def apply_form_layout(layer: QgsVectorLayer, layout_def: dict):
    """
    Setzt ein Tab-basiertes Formular-Layout auf einen Layer.
    Felder in 'hidden' werden vollständig aus dem Formular entfernt.
    """
    config = layer.editFormConfig()
    config.setLayout(QgsEditFormConfig.EditorLayout.TabLayout)
    root = config.invisibleRootContainer()
    root.clear()

    fields      = layer.fields()
    hidden_set  = {f.strip().lower() for f in layout_def.get("hidden", [])}
    tabs_def    = layout_def.get("tabs", [])

    # Alle Felder die in Tabs auftauchen sammeln
    in_tabs = set()
    for tab_def in tabs_def:
        for fname in tab_def.get("fields", []):
            in_tabs.add(fname.strip().lower())

    for tab_def in tabs_def:
        tab = QgsAttributeEditorContainer(tab_def["name"], root)
        tab.setIsGroupBox(False)   # False = Tab, True = Groupbox
        tab.setColumnCount(1)

        for fname in tab_def.get("fields", []):
            fname_clean = fname.strip()
            idx = fields.indexFromName(fname_clean)
            if idx < 0:
                # Felder mit Zeilenumbrüchen im Namen (BT-GPKG-Bug)
                for i in range(fields.count()):
                    if fields.field(i).name().strip() == fname_clean:
                        idx = i
                        break
            if idx >= 0:
                elem = QgsAttributeEditorField(fname_clean, idx, tab)
                tab.addChildElement(elem)

        root.addChildElement(tab)

    # Felder die weder in Tabs noch in hidden sind → eigener Tab "Weitere"
    remaining = []
    for i in range(fields.count()):
        fn = fields.field(i).name().strip().lower()
        if fn not in in_tabs and fn not in hidden_set and fn != "fid":
            remaining.append(fields.field(i).name())

    if remaining:
        tab_more = QgsAttributeEditorContainer("Weitere", root)
        tab_more.setIsGroupBox(False)
        tab_more.setColumnCount(1)
        for fname in remaining:
            idx = fields.indexFromName(fname)
            if idx >= 0:
                elem = QgsAttributeEditorField(fname, idx, tab_more)
                tab_more.addChildElement(elem)
        root.addChildElement(tab_more)

    # Auto-Felder als schreibgeschützt markieren (werden per Expression befüllt)
    readonly_fields = list(layout_def.get("readonly", []))
    # Der Primaerschluessel wird in JEDER Fachschale schreibgeschuetzt:
    # 'hidden' blendet fid nur im Formular aus, in der Attributtabelle bliebe
    # es sonst editierbar.
    if "fid" not in [f.lower() for f in readonly_fields]:
        readonly_fields.append("fid")

    fields_obj = layer.fields()
    for fname in readonly_fields:
        idx = fields_obj.indexFromName(fname)
        if idx >= 0:
            config.setReadOnly(idx, True)

    layer.setEditFormConfig(config)


# ── Dialog ────────────────────────────────────────────────────────────────────

class QFieldProjectDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("QField-Projekt erstellen")
        self.setMinimumWidth(500)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # ── Fachschale ────────────────────────────────────────────────────────
        fach_box = QGroupBox("Fachschale")
        fach_form = QFormLayout()
        self.fach_combo = QComboBox()
        from .fachschalen_config import FACHSCHALEN
        for f in FACHSCHALEN:
            self.fach_combo.addItem(f["bezeichnung"], f)
        fach_form.addRow("Fachschale:", self.fach_combo)
        fach_box.setLayout(fach_form)

        # ── Projekt ───────────────────────────────────────────────────────────
        proj_box = QGroupBox("Projekt")
        proj_form = QFormLayout()

        self.name_edit = QLineEdit("QField_Erfassung")
        proj_form.addRow("Projektname:", self.name_edit)

        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Ausgabe-Ordner …")
        browse_btn = QPushButton("…")
        browse_btn.setFixedWidth(30)
        browse_btn.clicked.connect(self._browse)
        folder_row.addWidget(self.folder_edit)
        folder_row.addWidget(browse_btn)
        proj_form.addRow("Ordner:", folder_row)

        self.wms_check = QCheckBox("WMS-Hintergrundkarten einbinden")
        self.wms_check.setChecked(True)
        proj_form.addRow("", self.wms_check)

        self.plugin_check = QCheckBox("QField-Plugin (Artsuche) einbinden")
        self.plugin_check.setChecked(True)
        self.plugin_check.setToolTip(
            "Kopiert das passende Artsuche-Plugin neben die Projektdatei.\n"
            "Aktiviert sich in QField automatisch beim Öffnen des Projekts.")
        proj_form.addRow("", self.plugin_check)

        proj_box.setLayout(proj_form)

        # ── Log ───────────────────────────────────────────────────────────────
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFixedHeight(140)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_box = QDialogButtonBox()
        self.run_btn   = btn_box.addButton("Projekt erstellen",
                                           QDialogButtonBox.ButtonRole.AcceptRole)
        self.close_btn = btn_box.addButton("Schließen",
                                           QDialogButtonBox.ButtonRole.RejectRole)
        self.run_btn.clicked.connect(self._run)
        self.close_btn.clicked.connect(self.reject)

        layout.addWidget(fach_box)
        layout.addWidget(proj_box)
        layout.addWidget(self.log)
        layout.addWidget(btn_box)

    def _log(self, msg):
        self.log.append(msg)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Ausgabe-Ordner wählen")
        if folder:
            self.folder_edit.setText(folder)

    # ── Projekt bauen ─────────────────────────────────────────────────────────
    def _run(self):
        fach       = self.fach_combo.currentData()
        name       = self.name_edit.text().strip() or "QField_Erfassung"
        out_folder = self.folder_edit.text().strip()

        if not out_folder or not os.path.isdir(out_folder):
            self._log("⚠ Bitte gültigen Ausgabe-Ordner wählen.")
            return

        self.run_btn.setEnabled(False)
        try:
            self._build(fach, name, out_folder)
        except Exception as e:
            self._log(f"✗ Fehler: {e}")
            import traceback
            self._log(traceback.format_exc())
        finally:
            self.run_btn.setEnabled(True)

    def _build(self, fach, name, out_folder):
        from .fachschalen_config import NRW_WMS_LAYERS
        from .new_project_wizard import _PLUGIN_DIR as PLUG_DIR

        code      = fach["code"]
        gpkg_data = fach.get("gpkg_data", {})
        project   = QgsProject.instance()
        project.clear()
        project.setCrs(QgsCoordinateReferenceSystem("EPSG:25832"))
        project.setTitle(name)

        # QField-spezifische Projektoptionen
        project.writeEntry("QField", "autoSave", "true")
        project.writeEntry("QField", "maxImageSize", "1024")

        root = project.layerTreeRoot()
        layer_map = {}   # name → QgsVectorLayer

        # 1. Referenzlisten zuerst (für ValueRelation)
        ref_group = root.addGroup("Referenzlisten")
        ref_group.setItemVisibilityChecked(False)   # standardmäßig eingeklappt
        for entry in gpkg_data.get("ref_layers", []):
            lyr = self._load_gpkg(entry)
            if lyr:
                lyr.setReadOnly(True)
                lyr.setCustomProperty("QFieldSync/action",
                                      QFIELD_ACTIONS["reference"])
                project.addMapLayer(lyr, addToLegend=False)
                ref_group.addLayer(lyr)
                layer_map[entry["layername"]] = lyr
                self._log(f"  ✓ Ref: {entry['layername']}")

        # 2. Erfassungs-Layer mit Formular-Layout
        fach_group = root.addGroup(fach["bezeichnung"])
        form_defs  = FORM_LAYOUTS.get(code, {})
        for entry in gpkg_data.get("geo_layers", []):
            lyr = self._load_gpkg(entry)
            if not lyr:
                continue
            lyr.setCustomProperty("QFieldSync/action",
                                  QFIELD_ACTIONS["editable"])

            # ValueRelations + Defaults aus Fachschalen-Config anwenden
            matching = next(
                (gl for gl in fach.get("geo_layers", [])
                 if gl["table"] == entry["layername"]),
                None,
            )
            if matching:
                self._apply_value_relations(lyr, matching, layer_map)
                self._apply_default_values(lyr, matching)

            # QField Formular-Layout
            layout_def = form_defs.get(entry["layername"])
            if layout_def:
                apply_form_layout(lyr, layout_def)
                self._log(f"  ✓ Form-Layout: {entry['layername']}")

            project.addMapLayer(lyr, addToLegend=False)
            fach_group.addLayer(lyr)
            layer_map[entry["layername"]] = lyr
            self._log(f"  ✓ Layer: {entry['layername']}")

        # 3. Grenzen / Untersuchungsgebiet
        border_layers = gpkg_data.get("border_layers", [])
        if border_layers:
            grenzen_group = root.addGroup("Grenzen")
            for entry in border_layers:
                lyr = self._load_gpkg(entry)
                if lyr:
                    lyr.setReadOnly(True)
                    lyr.setCustomProperty("QFieldSync/action",
                                          QFIELD_ACTIONS["border"])
                    project.addMapLayer(lyr, addToLegend=False)
                    grenzen_group.addLayer(lyr)
                    self._log(f"  ✓ Grenze: {entry['display']}")

        # 4. Relationen registrieren (Brutvögel)
        relations = gpkg_data.get("relations", [])
        if relations:
            self._apply_relations(project, layer_map, relations)
            self._log(f"  ✓ {len(relations)} Relationen gesetzt")

        # 5. WMS (optional)
        if self.wms_check.isChecked():
            wms_group = root.addGroup("Hintergrund")
            wms_group.setItemVisibilityChecked(False)
            for wms in NRW_WMS_LAYERS:
                wms_lyr = self._build_wms(wms)
                if wms_lyr and wms_lyr.isValid():
                    wms_lyr.setCustomProperty("QFieldSync/action",
                                              QFIELD_ACTIONS["wms"])
                    project.addMapLayer(wms_lyr, addToLegend=False)
                    wms_group.addLayer(wms_lyr)
            self._log("  ✓ WMS-Hintergrundkarten (no_action)")

        # 6. Projekt speichern
        qgs_path = os.path.join(out_folder, f"{name}.qgs")
        project.write(qgs_path)
        self._log(f"\n✓ Projekt gespeichert: {qgs_path}")

        # 7. QField-Plugin kopieren (optional)
        if self.plugin_check.isChecked():
            self._deploy_qfield_plugin(code, name, out_folder)

        self._log("  → Ordner in QFieldSync öffnen und auf Gerät übertragen.")

    # ── Hilfsmethoden (aus new_project_wizard übernommen) ─────────────────────

    def _load_gpkg(self, entry: dict):
        gpkg_abs  = os.path.join(_PLUGIN_DIR, entry["gpkg"])
        layername = entry["layername"]
        display   = entry.get("display", layername)
        if not os.path.isfile(gpkg_abs):
            self._log(f"  ⚠ GPKG nicht gefunden: {gpkg_abs}")
            return None
        lyr = QgsVectorLayer(f"{gpkg_abs}|layername={layername}", display, "ogr")
        if not lyr.isValid():
            self._log(f"  ⚠ Layer ungültig: {layername}")
            return None
        lyr.loadDefaultStyle()
        return lyr

    def _apply_value_relations(self, layer, row, ref_map):
        from qgis.core import QgsEditorWidgetSetup
        vr = row.get("value_relations", {})
        fields = layer.fields()
        for fname, cfg in vr.items():
            idx = fields.indexFromName(fname)
            if idx < 0:
                continue
            ref = ref_map.get(cfg["ref_table"])
            if ref is None:
                continue
            wc = {
                "Layer":               ref.id(),
                "LayerName":           cfg["ref_table"],
                "LayerSource":         ref.source(),
                "LayerProviderName":   ref.providerType(),
                "Key":                 cfg["key"],
                "Value":               cfg["value"],
                "AllowMulti":          False,
                "AllowNull":           True,
                "FilterExpression":    cfg.get("filter", ""),
                "OrderByValue":        True,
                "UseCompleter":        cfg.get("use_completer", True),
                "CompleterMatchFlags": cfg.get("completer_match_flags", 0),
            }
            layer.setEditorWidgetSetup(
                idx, QgsEditorWidgetSetup("ValueRelation", wc)
            )

    def _apply_default_values(self, layer, row):
        defaults = row.get("default_values", {})
        fields   = layer.fields()
        for fname, cfg in defaults.items():
            idx = fields.indexFromName(fname)
            if idx < 0:
                continue
            layer.setDefaultValueDefinition(
                idx, QgsDefaultValue(cfg["expression"],
                                     cfg.get("apply_on_update", False))
            )

    def _apply_relations(self, project, layer_map, relations):
        rel_mgr  = project.relationManager()
        strength_map = {
            "Composition": QgsRelation.RelationStrength.Composition,
            "Association": QgsRelation.RelationStrength.Association,
        }
        for rd in relations:
            ri  = layer_map.get(rd["referencing_layer"])
            re  = layer_map.get(rd["referenced_layer"])
            if ri is None or re is None:
                continue
            rel = QgsRelation()
            rel.setId(rd["id"])
            rel.setName(rd["name"])
            rel.setReferencingLayer(ri.id())
            rel.setReferencedLayer(re.id())
            rel.addFieldPair(rd["referencing_field"], rd["referenced_field"])
            rel.setStrength(strength_map.get(rd.get("strength", "Association"),
                            QgsRelation.RelationStrength.Association))
            rel_mgr.addRelation(rel)

    # ── QField-Plugin deployen ─────────────────────────────────────────────

    # Plugin-Verzeichnisse relativ zum Plugin-Root
    _PLUGIN_MAP = {
        "fundpunkte_tiere": "qfield_plugins/fundpunkte",
        "brutvogel":        "qfield_plugins/brutvogel",
    }

    def _deploy_qfield_plugin(self, fach_code: str, proj_name: str,
                              out_folder: str):
        """
        Kopiert das zum Fachschalen-Code passende QField-Plugin
        neben die Projektdatei (main.qml → <proj_name>.qml, search.qml).
        QField aktiviert das Plugin automatisch da es gleichnamig ist.
        """
        rel_dir = self._PLUGIN_MAP.get(fach_code)
        if rel_dir is None:
            self._log(f"  ℹ Kein QField-Plugin für Fachschale '{fach_code}'")
            return

        src_dir = os.path.join(_PLUGIN_DIR, rel_dir)
        if not os.path.isdir(src_dir):
            self._log(f"  ⚠ Plugin-Quellordner nicht gefunden: {src_dir}")
            return

        # main.qml → <projektname>.qml (QField-Konvention)
        main_src = os.path.join(src_dir, "main.qml")
        main_dst = os.path.join(out_folder, f"{proj_name}.qml")
        if os.path.isfile(main_src):
            shutil.copy2(main_src, main_dst)
            self._log(f"  ✓ Plugin: {proj_name}.qml")

        # Alle weiteren .qml und Ressourcen-Dateien
        for fname in os.listdir(src_dir):
            if fname == "main.qml":
                continue   # bereits als <name>.qml kopiert
            src_f = os.path.join(src_dir, fname)
            dst_f = os.path.join(out_folder, fname)
            if os.path.isfile(src_f):
                shutil.copy2(src_f, dst_f)
                self._log(f"  ✓ Plugin: {fname}")

        self._log("  → Plugin aktiviert sich automatisch beim Öffnen in QField.")

    def _build_wms(self, cfg: dict):
        if cfg["type"] == "wmts":
            uri = (f"crs={cfg['crs']}&dpiMode=7&featureCount=10"
                   f"&format={cfg['format']}&layers={cfg['layer']}"
                   f"&styles={cfg.get('style','default')}"
                   f"&tileMatrixSet={cfg.get('tilematrixset','EPSG_25832_16')}"
                   f"&tilePixelRatio=0&url={cfg['url']}")
        else:
            uri = (f"crs={cfg['crs']}&dpiMode=7&featureCount=10"
                   f"&format={cfg['format']}&layers={cfg['layer']}"
                   f"&styles&url={cfg['url']}")
        return QgsRasterLayer(uri, cfg["name"], "wms")
