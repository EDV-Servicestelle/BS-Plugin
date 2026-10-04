"""
gispad_import_dialog.py - GISPAD-Export uebernehmen

Dialog fuer die Mitarbeitenden der Biologischen Stationen. Absicht: so wenig
Entscheidungen wie moeglich. Der Export wird gewaehlt, das Plugin sieht
selbst nach, was drinsteckt, und schlaegt die Vollsicherung vor.

Warum die Vollsicherung voreingestellt ist: GISPAD laesst sich nicht mehr
dauerhaft betreiben. Was jetzt nicht herausgeholt wird, ist spaeter nicht
mehr zugaenglich - deshalb ist der verlustfreie Weg der Normalfall und die
fachliche Auswahl die Zusatzoption, nicht umgekehrt.
"""
import os

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGroupBox,
    QLineEdit, QRadioButton, QComboBox, QProgressBar, QTextEdit, QCheckBox,
    QFileDialog, QMessageBox, QDialogButtonBox,
)
from qgis.core import QgsProject, QgsVectorLayer

try:
    from qgis_new_project_plugin.core.gispad_klassen import OBJEKTKLASSEN
    from qgis_new_project_plugin.workers.gispad_worker import GispadWorker
except ImportError:
    from .core.gispad_klassen import OBJEKTKLASSEN
    from .workers.gispad_worker import GispadWorker


class GispadImportDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GISPAD-Export übernehmen")
        self.resize(760, 620)
        self._worker = None
        self._analyse = None
        self._build_ui()

    # ── Oberfläche ──────────────────────────────────────────────────────────
    def _build_ui(self):
        lo = QVBoxLayout(self)

        hinweis = QLabel(
            "Übernimmt die Daten aus einem GISPAD-Export (File-Geodatabase) "
            "in ein GeoPackage.\nGISPAD selbst wird dafür nicht benötigt.")
        hinweis.setWordWrap(True)
        hinweis.setStyleSheet("color: #444;")
        lo.addWidget(hinweis)

        # 1 – Export wählen
        box1 = QGroupBox("1. GISPAD-Export wählen")
        l1 = QVBoxLayout(box1)
        z = QHBoxLayout()
        self.pfad_edit = QLineEdit()
        self.pfad_edit.setPlaceholderText(
            "Ordner des Exports (endet auf .gdb)")
        self.pfad_edit.setReadOnly(True)
        btn = QPushButton("Durchsuchen …")
        btn.clicked.connect(self._waehle_gdb)
        z.addWidget(self.pfad_edit, 1)
        z.addWidget(btn)
        l1.addLayout(z)
        self.befund_label = QLabel("Noch kein Export gewählt.")
        self.befund_label.setWordWrap(True)
        self.befund_label.setStyleSheet("color: #666;")
        l1.addWidget(self.befund_label)
        lo.addWidget(box1)

        # 2 – Was soll übernommen werden
        self.box2 = QGroupBox("2. Was soll übernommen werden?")
        self.box2.setEnabled(False)
        l2 = QVBoxLayout(self.box2)
        self.rb_alles = QRadioButton(
            "Alles sichern – jede Tabelle vollständig (empfohlen)")
        self.rb_alles.setChecked(True)
        erl = QLabel(
            "Nichts geht verloren. Die Datei enthält zusätzlich eine "
            "Übersicht, welche Tabelle an welcher hängt.")
        erl.setWordWrap(True)
        erl.setStyleSheet("color: #666; margin-left: 20px;")
        self.rb_fach = QRadioButton("Nur die Fachdaten einer Objektklasse:")
        zk = QHBoxLayout()
        zk.addSpacing(20)
        self.klasse_combo = QComboBox()
        self.klasse_combo.setEnabled(False)
        zk.addWidget(self.klasse_combo, 1)
        self.rb_fach.toggled.connect(self.klasse_combo.setEnabled)
        l2.addWidget(self.rb_alles)
        l2.addWidget(erl)
        l2.addWidget(self.rb_fach)
        l2.addLayout(zk)
        lo.addWidget(self.box2)

        # 3 – Ziel
        self.box3 = QGroupBox("3. Zieldatei")
        self.box3.setEnabled(False)
        l3 = QVBoxLayout(self.box3)
        z3 = QHBoxLayout()
        self.ziel_edit = QLineEdit()
        btn3 = QPushButton("…")
        btn3.setFixedWidth(34)
        btn3.clicked.connect(self._waehle_ziel)
        z3.addWidget(self.ziel_edit, 1)
        z3.addWidget(btn3)
        l3.addLayout(z3)
        self.laden_cb = QCheckBox("Ergebnis anschließend in QGIS laden")
        self.laden_cb.setChecked(True)
        l3.addWidget(self.laden_cb)
        lo.addWidget(self.box3)

        self.start_btn = QPushButton("Übernehmen")
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self._starte)
        lo.addWidget(self.start_btn)

        self.balken = QProgressBar()
        self.balken.setVisible(False)
        lo.addWidget(self.balken)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet("font-family: monospace; font-size: 11px;")
        lo.addWidget(self.log, 1)

        kn = QDialogButtonBox(QDialogButtonBox.Close)
        kn.rejected.connect(self.reject)
        lo.addWidget(kn)

    def _sage(self, text):
        self.log.append(text)
        self.log.ensureCursorVisible()

    # ── Schritt 1: Export wählen und sichten ────────────────────────────────
    def _waehle_gdb(self):
        pfad = QFileDialog.getExistingDirectory(
            self, "GISPAD-Export wählen (Ordner *.gdb)", "")
        if not pfad:
            return
        # Hat jemand IN den Ordner navigiert, ist der .gdb-Ordner gemeint.
        gdb = self._gdb_wurzel(pfad) or pfad
        if not gdb.lower().rstrip("/\\").endswith(".gdb"):
            QMessageBox.warning(
                self, "Kein GISPAD-Export",
                "Der gewählte Ordner endet nicht auf „.gdb“.\n\n"
                "Ein GISPAD-Export ist der Ordner selbst (z. B. "
                "„GispadExport.gdb“) – nicht der Ordner darüber.")
            return
        self.pfad_edit.setText(gdb)
        self.befund_label.setText("Sichte den Export …")
        self.box2.setEnabled(False)
        self.box3.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.log.clear()
        self._starte_worker("analyse", {"gdb": gdb})

    @staticmethod
    def _gdb_wurzel(pfad):
        """Oberster .gdb-Ordner im Pfad, oder None. Beide Trennzeichen."""
        if not pfad:
            return None
        teile = pfad.replace("\\", "/").split("/")
        for i, t in enumerate(teile):
            if t.lower().endswith(".gdb"):
                return pfad[:len("/".join(teile[:i + 1]))]
        return None

    def _zeige_analyse(self, erg):
        self._analyse = erg
        klassen = erg["klassen"]
        self.klasse_combo.clear()
        for kuerzel, info in sorted(klassen.items()):
            self.klasse_combo.addItem(
                f"{info['name']} ({kuerzel}) – {info['objekte']} Objekte",
                kuerzel)

        if klassen:
            teile = [f"{i['name']} ({k}): {i['objekte']} Objekte"
                     for k, i in sorted(klassen.items())]
            text = "Gefunden: " + " · ".join(teile)
        else:
            text = ("Keine der bekannten Objektklassen (BT, BK, MAS) "
                    "gefunden.")
        text += (f"\n{len(erg['gefuellt'])} gefüllte Tabellen insgesamt.")
        if erg["unbekannt"]:
            text += ("\nWeitere Objekte ohne eigenes Fachprofil: "
                     + ", ".join(erg["unbekannt"][:6])
                     + " – diese sind in der Vollsicherung enthalten.")
        self.befund_label.setText(text)

        self._sage("Inhalt des Exports")
        for name, n in sorted(erg["gefuellt"].items(),
                              key=lambda x: -x[1]):
            self._sage(f"   {name:24} {n:7}")
        self._sage("\nWie die Tabellen zusammenhängen")
        bez = erg["beziehungen"]
        for kind in sorted(bez):
            info = bez[kind]
            if info["sicher"]:
                self._sage(f"   {kind:24} → {info['eltern']}")
            else:
                self._sage(f"   {kind:24} → nicht eindeutig bestimmbar")
        unklar = [k for k in bez if not bez[k]["sicher"]]
        if unklar:
            self._sage(
                "\n   Hinweis: bei sehr kleinen Tabellen reichen die Daten "
                "nicht immer aus,\n   um die Zuordnung eindeutig zu "
                "bestimmen. Für die Vollsicherung ist das\n   ohne Belang – "
                "dort kommt alles mit.")

        self.rb_fach.setEnabled(bool(klassen))
        if not klassen:
            self.rb_alles.setChecked(True)
        self.box2.setEnabled(True)
        self.box3.setEnabled(True)
        self.start_btn.setEnabled(True)
        self._schlage_ziel_vor()

    def _schlage_ziel_vor(self):
        gdb = self.pfad_edit.text().strip()
        if not gdb:
            return
        ordner = os.path.dirname(gdb.rstrip("/\\"))
        name = os.path.splitext(os.path.basename(gdb.rstrip("/\\")))[0]
        zusatz = "Sicherung" if self.rb_alles.isChecked() else (
            self.klasse_combo.currentData() or "Fachdaten")
        self.ziel_edit.setText(os.path.join(ordner, f"{name}_{zusatz}.gpkg"))

    def _waehle_ziel(self):
        pfad, _ = QFileDialog.getSaveFileName(
            self, "Zieldatei", self.ziel_edit.text(), "GeoPackage (*.gpkg)")
        if pfad:
            if not pfad.lower().endswith(".gpkg"):
                pfad += ".gpkg"
            self.ziel_edit.setText(pfad)

    # ── Schritt 2: Übernehmen ───────────────────────────────────────────────
    def _starte(self):
        gdb = self.pfad_edit.text().strip()
        ziel = self.ziel_edit.text().strip()
        if not ziel:
            QMessageBox.warning(self, "Zieldatei",
                                "Bitte eine Zieldatei angeben.")
            return
        if os.path.exists(ziel):
            if QMessageBox.question(
                    self, "Datei überschreiben?",
                    f"„{os.path.basename(ziel)}“ gibt es schon.\n\n"
                    "Soll sie überschrieben werden?") != QMessageBox.Yes:
                return
        ordner = os.path.dirname(ziel)
        if ordner and not os.path.isdir(ordner):
            QMessageBox.warning(self, "Zielordner",
                                f"Der Ordner gibt es nicht:\n{ordner}")
            return

        self.log.clear()
        if self.rb_alles.isChecked():
            self._sage("Vollsicherung – alle Tabellen werden übernommen.\n")
            self._starte_worker("alles", {"gdb": gdb, "ziel": ziel})
        else:
            klasse = self.klasse_combo.currentData()
            self._sage(f"Fachdaten der Objektklasse {klasse} "
                       f"({OBJEKTKLASSEN[klasse]['name']}).\n")
            self._starte_worker("fachlich", {"gdb": gdb, "ziel": ziel,
                                             "klasse": klasse})

    def _starte_worker(self, auftrag, config):
        self.balken.setVisible(True)
        self.balken.setValue(0)
        self.start_btn.setEnabled(False)
        self._auftrag = auftrag
        self._ziel = config.get("ziel")
        self._worker = GispadWorker(auftrag, config, self)
        self._worker.fortschritt.connect(self._fortschritt)
        self._worker.fertig.connect(self._fertig)
        self._worker.start()

    def _fortschritt(self, prozent, text):
        if prozent >= 0:
            self.balken.setValue(prozent)
        if text:
            self.balken.setFormat(f"{text}  (%p%)")

    def _fertig(self, erfolg, fehler, ergebnis):
        self.balken.setVisible(False)
        self.start_btn.setEnabled(True)
        if not erfolg:
            self._sage("\nFehlgeschlagen:\n" + fehler)
            QMessageBox.critical(
                self, "Übernahme fehlgeschlagen",
                fehler.split("\n")[0] +
                "\n\nEinzelheiten stehen im Protokoll unten.")
            return

        if self._auftrag == "analyse":
            self._zeige_analyse(ergebnis)
            return

        geschrieben = ergebnis["geschrieben"]
        befunde = ergebnis["befunde"]
        gesamt = sum(geschrieben.values())
        self._sage("Geschrieben:")
        for name, n in geschrieben.items():
            self._sage(f"   {name:24} {n:7}")
        self._sage(f"\n{gesamt} Datensätze in {len(geschrieben)} Tabellen.")
        self._sage(f"Datei: {self._ziel}")

        if befunde:
            self._sage("\nHinweise:")
            for b in befunde:
                self._sage(f"   • {b}")

        if self.laden_cb.isChecked():
            self._lade_in_qgis(self._ziel, geschrieben)

        QMessageBox.information(
            self, "Fertig",
            f"{gesamt} Datensätze übernommen.\n\n{self._ziel}")

    def _lade_in_qgis(self, gpkg, geschrieben):
        """
        Nur die Layer mit Geometrie in die Karte, der Rest als Tabelle.
        Bei einer Vollsicherung waeren sonst auf einen Schlag 16 Eintraege
        in der Legende - unuebersichtlich und fuer die meisten ohne Nutzen.
        """
        projekt = QgsProject.instance()
        geladen = 0
        for name in geschrieben:
            lyr = QgsVectorLayer(f"{gpkg}|layername={name}", name, "ogr")
            if not lyr.isValid():
                self._sage(f"   ⚠ Layer nicht ladbar: {name}")
                continue
            if lyr.isSpatial():
                projekt.addMapLayer(lyr)
                geladen += 1
        if geladen:
            self._sage(f"\n{geladen} Kartenlayer in QGIS geladen.")
        else:
            self._sage("\nKeine Layer mit Geometrie zum Laden "
                       "(reine Sachtabellen).")
