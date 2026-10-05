"""
workers/gispad_worker.py - GispadWorker QThread

Laeuft im Hintergrund, damit QGIS waehrend der Uebernahme bedienbar bleibt.
Eine grosse Kartierung bringt schnell zehntausende Zeilen mit; im
Vordergrund wuerde das Fenster einfrieren und wie ein Absturz wirken.
"""
from qgis.PyQt.QtCore import QThread, pyqtSignal

try:
    from qgis_new_project_plugin.core.gispad_klassen import (
        analysiere, exportiere_alles, exportiere_fachlich)
    from qgis_new_project_plugin.core.gispad import erschliesse
except ImportError:
    from ..core.gispad_klassen import (
        analysiere, exportiere_alles, exportiere_fachlich)
    from ..core.gispad import erschliesse


class GispadWorker(QThread):
    """auftrag: 'erschliessen' | 'analyse' | 'alles' | 'fachlich'"""

    fortschritt = pyqtSignal(int, str)
    fertig = pyqtSignal(bool, str, object)

    def __init__(self, auftrag, config, parent=None):
        super().__init__(parent)
        self.auftrag = auftrag
        self.config = config

    def run(self):
        try:
            melde = self.fortschritt.emit
            cfg = self.config
            if self.auftrag == "erschliessen":
                # Gepackte Exporte werden hier ausgepackt. Das kann bei
                # einer grossen Kartierung dauern - deshalb im Hintergrund
                # und nicht schon beim Klick im Dateidialog.
                gdbs, temp = erschliesse(cfg["quelle"], melde)
                self.fertig.emit(True, "", {"gdbs": gdbs, "temp": temp})
            elif self.auftrag == "analyse":
                ergebnis = analysiere(cfg["gdb"], melde)
                self.fertig.emit(True, "", ergebnis)
            elif self.auftrag == "alles":
                befunde = []
                geschrieben = exportiere_alles(cfg["gdb"], cfg["ziel"], melde,
                                               befunde=befunde)
                self.fertig.emit(True, "", {"geschrieben": geschrieben,
                                            "befunde": befunde})
            else:
                geschrieben, befunde = exportiere_fachlich(
                    cfg["gdb"], cfg["klasse"], cfg["ziel"], melde=melde)
                self.fertig.emit(True, "", {"geschrieben": geschrieben,
                                            "befunde": befunde})
        except Exception as e:
            import traceback
            self.fertig.emit(
                False, f"{e}\n\n{traceback.format_exc()[:1200]}", None)
