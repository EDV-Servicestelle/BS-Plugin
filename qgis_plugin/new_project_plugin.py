"""
NRW Naturschutz-Toolbox – Plugin-Hauptdatei
============================================
Registriert alle Menüeinträge und verwaltet den Plugin-Lebenszyklus.
Alle Imports sind lazy (erst beim Klick), damit QGIS schnell startet.
"""

from qgis.PyQt.QtWidgets import QAction
from .papierreviere_export_dialog import PapierreviereExportDialog
from .fundpunkte_export_dialog    import FundpunkteExportDialog


class NewProjectPlugin:
    """Plugin-Klasse – wird von QGIS beim Laden instanziiert."""

    MENU = "&NRW Naturschutz-Toolbox"

    def __init__(self, iface):
        self.iface = iface
        # Alte .pyc-Caches loeschen damit Aenderungen sofort wirken
        import shutil, os as _os
        _plug_dir = _os.path.dirname(__file__)
        for _root, _dirs, _files in _os.walk(_plug_dir):
            if "__pycache__" in _root:
                try: shutil.rmtree(_root)
                except: pass
        self._actions = []

    # ── Lebenszyklus ──────────────────────────────────────────────────────────

    def initGui(self):
        # Logging-Session starten
        try:
            from .debug_log import start_session
            import configparser as _cp
            _meta = _cp.ConfigParser()
            _meta.read(__file__.replace("new_project_plugin.py", "metadata.txt"))
            start_session(_meta.get("general", "version", fallback="?"))
        except Exception:
            pass
        """Menüeinträge registrieren."""
        entries = [
            ("Fachschalen-Wizard …",          self._wizard),
            ("QField-Export …",               self._qfield),
            ("─────────────────────────",     None),           # Trenner
            ("Fundpunkte – Altdaten importieren …", self._import),
            ("Fundpunkte – Zeitreihen-Diagramm …", self._trend),
            ("Fundpunkte – Papierreviere → Fundpunkte …", self._papierreviere_export),
            ("Fundpunkte – Export (CSV/XLSX/GPKG) …",   self._fundpunkte_export),
            ("─────────────────────────",     None),
            ("GISPAD-Export übernehmen …",     self._gispad),
            ("─────────────────────────",     None),
            ("NRW Luftbild → COG …",           self._luftbild),
            ("NRW LiDAR-Analyse …",            self._lidar),
            ("Hydrologische Analyse …",        self._hydro),
            ("NRW Grundlagendaten abrufen …",  self._grundlagen),
            ("─────────────────────────",     None),
            ("GBIF Artvorkommen …",            self._gbif),
            ("Ornitho.de Import …",             self._ornitho),
            ("─────────────────────────",         None),
            ("PostGIS-Datenbank einrichten …",    self._postgis_setup),
            ("─────────────────────────",         None),
            ("Grundlagen-DB verwalten …",         self._grundlagen_db),
        ]
        for label, slot in entries:
            act = QAction(label, self.iface.mainWindow())
            if slot is None:
                act.setSeparator(True)
            else:
                act.triggered.connect(slot)
            self.iface.addPluginToMenu(self.MENU, act)
            self._actions.append(act)

    def _gispad(self):
        from .gispad_import_dialog import GispadImportDialog
        GispadImportDialog(self.iface.mainWindow()).exec()

    def _papierreviere_export(self):
        dlg = PapierreviereExportDialog(self.iface.mainWindow())
        dlg.exec()

    def _fundpunkte_export(self):
        dlg = FundpunkteExportDialog(self.iface.mainWindow())
        dlg.exec()

    def unload(self):
        for act in self._actions:
            self.iface.removePluginMenu(self.MENU, act)
        self._actions.clear()

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _wizard(self):
        from .new_project_wizard import NewProjectWizard
        wiz = NewProjectWizard(self.iface.mainWindow())
        if wiz.exec():
            from .debug_log import log, log_exc
            from .wizard_pages import WizardBuildLog
            WizardBuildLog.clear()
            log("_build_project starten", context="Wizard")
            try:
                wiz._build_project()
                log("_build_project OK", context="Wizard")
            except Exception:
                log_exc("Wizard._build_project")
                WizardBuildLog.add_exception("_build_project")
            WizardBuildLog.show_if_errors(self.iface.mainWindow())

    def _qfield(self):
        from .qfield_project_dialog import QFieldProjectDialog
        QFieldProjectDialog(self.iface.mainWindow()).exec()

    def _import(self):
        from .fundpunkte_import_dialog import FundpunkteImportDialog
        FundpunkteImportDialog(self.iface.mainWindow()).exec()

    def _trend(self):
        from .fundpunkte_trend_dialog import FundpunkteTrendDialog
        FundpunkteTrendDialog(self.iface.mainWindow()).exec()

    def _luftbild(self):
        from .luftbild_dialog import LuftbildDialog
        LuftbildDialog(self.iface.mainWindow()).exec()

    def _lidar(self):
        from .lidar_dialog import LidarDialog
        LidarDialog(self.iface.mainWindow()).exec()

    def _gbif(self):
        from .gbif_dialog import GbifDialog
        GbifDialog(self.iface.mainWindow()).exec()

    def _ornitho(self):
        from .ornitho_import_dialog import OrnithoImportDialog
        OrnithoImportDialog(self.iface.mainWindow()).exec()

    def _postgis_setup(self):
        from .postgis_setup_dialog import PostgisSetupDialog
        PostgisSetupDialog(self.iface.mainWindow()).exec()

    def _grundlagen_db(self):
        from .grundlagen_db_dialog import GrundlagenDbDialog
        GrundlagenDbDialog(self.iface.mainWindow()).exec()

    def _hydro(self):
        from .hydro_dialog import HydroDialog
        HydroDialog(self.iface.mainWindow()).exec()

    def _grundlagen(self):
        from .grundlagen_dialog import GrundlagenDialog
        GrundlagenDialog(self.iface.mainWindow()).exec()
