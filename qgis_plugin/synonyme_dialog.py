# -*- coding: utf-8 -*-
"""
Synonyme verwalten – Dialog.
============================

Drei Arbeitsbereiche:

* **Hinzufügen** – Zielart suchen, ein oder mehrere Synonyme dazu erfassen.
* **Import** – CSV/XLSX mit Suchbegriff + Zielart, mit Trockenlauf vor dem Schreiben.
* **Bestand & Prüfung** – Bestand anzeigen, Fehler finden, Gruppen reparieren.

Ziel ist wahlweise das geladene Projekt (GeoPackage **oder** PostGIS) oder eine
GeoPackage-Datei, z. B. die Vorlage im Plugin-Ordner.
"""
import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
                                 QLabel, QLineEdit, QPushButton, QComboBox,
                                 QListWidget, QListWidgetItem, QPlainTextEdit,
                                 QTabWidget, QWidget, QTableWidget,
                                 QTableWidgetItem, QTextEdit, QFileDialog,
                                 QMessageBox, QGroupBox, QHeaderView)

from . import synonyme_manager as sm


class SynonymeDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Synonyme verwalten – Fundpunkte Tiere")
        self.resize(820, 640)
        self._ref = self._syn = self._ag = None
        self._cands = []
        self._ready = []

        root = QVBoxLayout(self)

        # ── Ziel ────────────────────────────────────────────────────────────
        box = QGroupBox("Ziel der Änderungen")
        bv = QVBoxLayout(box)
        h = QHBoxLayout()
        self.target = QComboBox()
        self.target.addItem("Geladenes Projekt (Layer)", "project")
        self.target.addItem("GeoPackage-Datei …", "file")
        self.target.currentIndexChanged.connect(self._target_changed)
        self.path = QLineEdit()
        self.path.setPlaceholderText("Pfad zu Referenzen.gpkg")
        self.path.setEnabled(False)
        self.browse = QPushButton("…")
        self.browse.setFixedWidth(32)
        self.browse.setEnabled(False)
        self.browse.clicked.connect(self._pick)
        h.addWidget(self.target)
        h.addWidget(self.path, 1)
        h.addWidget(self.browse)
        self.status = QLabel("–")
        h.addWidget(self.status)
        bv.addLayout(h)

        h2 = QHBoxLayout()
        h2.addWidget(QLabel("Bearbeiter/in:"))
        self.bearbeiter = QLineEdit(sm.current_user())
        self.bearbeiter.setToolTip(
            "Wird zusammen mit dem Datum als Nachweis gespeichert "
            "(Felder erfasst_von / erfasst_am).")
        h2.addWidget(self.bearbeiter, 1)
        bv.addLayout(h2)
        root.addWidget(box)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self.tabs.addTab(self._tab_add(), "Hinzufügen")
        self.tabs.addTab(self._tab_import(), "Import (CSV/XLSX)")
        self.tabs.addTab(self._tab_sync(), "Abgleich")
        self.tabs.addTab(self._tab_check(), "Bestand && Prüfung")

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(120)
        root.addWidget(QLabel("Protokoll:"))
        root.addWidget(self.log)

        close = QPushButton("Schließen")
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        root.addLayout(row)

        self._load_layers()

    # ── Tabs ────────────────────────────────────────────────────────────────
    def _tab_add(self):
        w = QWidget()
        v = QVBoxLayout(w)
        f = QFormLayout()
        self.q = QLineEdit()
        self.q.setPlaceholderText("Zielart suchen (Name, wiss. Name oder entityid) …")
        self.q.textEdited.connect(self._search)
        f.addRow("Zielart:", self.q)
        v.addLayout(f)
        self.hits = QListWidget()
        self.hits.setMaximumHeight(180)
        v.addWidget(QLabel("Treffer (nur Arten mit gültiger Artengruppe):"))
        v.addWidget(self.hits)
        v.addWidget(QLabel("Synonyme – ein Begriff je Zeile:"))
        self.terms = QPlainTextEdit()
        self.terms.setPlaceholderText("z. B.\nZiegenmelker\nNachtschwalbe (alt)")
        v.addWidget(self.terms, 1)
        b = QPushButton("Synonyme hinzufügen")
        b.clicked.connect(self._add)
        v.addWidget(b)
        return w

    def _tab_import(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel(
            "Datei mit zwei Spalten: <b>Suchbegriff</b> und <b>Zielart</b> "
            "(wissenschaftlicher/deutscher Name oder entityid). Kopfzeile optional."))
        h = QHBoxLayout()
        self.imp_path = QLineEdit()
        self.imp_path.setPlaceholderText("CSV- oder XLSX-Datei …")
        pick = QPushButton("…")
        pick.setFixedWidth(32)
        pick.clicked.connect(self._pick_import)
        chk = QPushButton("Prüfen (Trockenlauf)")
        chk.clicked.connect(self._dry_run)
        h.addWidget(self.imp_path, 1)
        h.addWidget(pick)
        h.addWidget(chk)
        v.addLayout(h)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Suchbegriff", "Zielart", "Artengruppe", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        v.addWidget(self.table, 1)
        self.apply_btn = QPushButton("Übernehmen")
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self._apply_import)
        v.addWidget(self.apply_btn)
        return w

    def _tab_sync(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel(
            "Arbeitsbestand (oben gewählt) mit einem zweiten Bestand vergleichen – "
            "z. B. Projekt gegen die Vorlage im Plugin-Ordner. "
            "Der Nachweis (wer/wann) wird beim Übertragen mitgenommen."))
        h = QHBoxLayout()
        self.cmp_path = QLineEdit()
        self.cmp_path.setPlaceholderText("Vergleichs-GeoPackage (Referenzen.gpkg) …")
        pick = QPushButton("…")
        pick.setFixedWidth(32)
        pick.clicked.connect(self._pick_compare)
        cmp_btn = QPushButton("Vergleichen")
        cmp_btn.clicked.connect(self._compare)
        h.addWidget(self.cmp_path, 1)
        h.addWidget(pick)
        h.addWidget(cmp_btn)
        v.addLayout(h)

        self.cmp_table = QTableWidget(0, 5)
        self.cmp_table.setHorizontalHeaderLabels(
            ["Suchbegriff", "Zielart", "Status", "erfasst von", "erfasst am"])
        self.cmp_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.cmp_table.setSelectionBehavior(QTableWidget.SelectRows)
        v.addWidget(self.cmp_table, 1)

        row = QHBoxLayout()
        self.to_there = QPushButton("Fehlende → Vergleichsdatei übertragen")
        self.to_there.clicked.connect(lambda: self._transfer("hier"))
        self.to_here = QPushButton("Fehlende ← übernehmen")
        self.to_here.clicked.connect(lambda: self._transfer("dort"))
        row.addWidget(self.to_there)
        row.addWidget(self.to_here)
        v.addLayout(row)
        return w

    def _pick_compare(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "Vergleichs-GeoPackage wählen", "", "GeoPackage (*.gpkg)")
        if p:
            self.cmp_path.setText(p)

    def _compare(self):
        if not self._ok():
            return
        p = self.cmp_path.text().strip()
        if not os.path.isfile(p):
            QMessageBox.warning(self, "Datei", "Bitte eine gültige Datei wählen.")
            return
        ref2, syn2, _ag2 = sm.layers_from_gpkg(p)
        if syn2 is None:
            QMessageBox.warning(self, "Datei",
                                "In der Datei fehlt die Tabelle 'Arten_Synonyme'.")
            return
        self._cmp = sm.compare(self._syn, syn2, self._ref)
        self._cmp_target = syn2
        self.cmp_table.setRowCount(0)
        for e in self._cmp["nur_hier"]:
            self._crow(e["term"], e["ziel"], "nur hier", e["erfasst_von"], e["erfasst_am"])
        for e in self._cmp["nur_dort"]:
            self._crow(e["term"], e["ziel"], "nur in Datei", e["erfasst_von"], e["erfasst_am"])
        for e in self._cmp["abweichend"]:
            self._crow(e["term"], "%s  ↔  %s" % (e.get("ziel_hier", ""),
                                                 e.get("ziel_dort", "")),
                       "abweichend", "", "")
        self._say("Abgleich: %d nur hier, %d nur in Datei, %d abweichend."
                  % (len(self._cmp["nur_hier"]), len(self._cmp["nur_dort"]),
                     len(self._cmp["abweichend"])))
        if self._cmp["abweichend"]:
            self._say("  Abweichende Einträge werden NICHT automatisch übertragen "
                      "– bitte fachlich klären.")

    def _crow(self, *vals):
        r = self.cmp_table.rowCount()
        self.cmp_table.insertRow(r)
        for i, v in enumerate(vals):
            self.cmp_table.setItem(r, i, QTableWidgetItem(str(v or "")))

    def _transfer(self, richtung):
        cmp = getattr(self, "_cmp", None)
        if not cmp:
            QMessageBox.information(self, "Kein Abgleich",
                                    "Bitte zuerst 'Vergleichen' ausführen.")
            return
        if richtung == "hier":
            entries, ziel, wohin = cmp["nur_hier"], self._cmp_target, "Vergleichsdatei"
        else:
            entries, ziel, wohin = cmp["nur_dort"], self._syn, "Arbeitsbestand"
        if not entries:
            self._say("Nichts zu übertragen (%s)." % wohin)
            return
        n, errs = sm.transfer(entries, ziel)
        self._say("%d Eintrag/Einträge in den %s übertragen." % (n, wohin))
        for e in errs:
            self._say("  " + e)
        self._load_layers()
        self._compare()

    def _tab_check(self):
        w = QWidget()
        v = QVBoxLayout(w)
        h = QHBoxLayout()
        b1 = QPushButton("Bestand prüfen")
        b1.clicked.connect(self._check)
        b2 = QPushButton("Artengruppen reparieren")
        b2.clicked.connect(self._repair)
        h.addWidget(b1)
        h.addWidget(b2)
        h.addStretch(1)
        v.addLayout(h)
        self.report = QTextEdit()
        self.report.setReadOnly(True)
        v.addWidget(self.report, 1)
        return w

    # ── Ziel / Layer ────────────────────────────────────────────────────────
    def _target_changed(self):
        isfile = self.target.currentData() == "file"
        self.path.setEnabled(isfile)
        self.browse.setEnabled(isfile)
        self._load_layers()

    def _pick(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "Referenzlisten-GeoPackage wählen", "", "GeoPackage (*.gpkg)")
        if p:
            self.path.setText(p)
            self._load_layers()

    def _load_layers(self):
        if self.target.currentData() == "file":
            p = self.path.text().strip()
            if not p or not os.path.isfile(p):
                self._ref = self._syn = self._ag = None
                self.status.setText("keine Datei")
                return
            self._ref, self._syn, self._ag = sm.layers_from_gpkg(p)
        else:
            self._ref, self._syn, self._ag = sm.layers_from_project()
        n = self._syn.featureCount() if self._syn else 0
        missing = [n_ for n_, l in (("Arten", self._ref),
                                    ("Arten_Synonyme", self._syn),
                                    ("Artengruppen", self._ag)) if l is None]
        if missing:
            self.status.setText("fehlt: " + ", ".join(missing))
            self._say("Nicht verfügbar: %s" % ", ".join(missing))
        else:
            self.status.setText("%d Synonyme" % n)

    def _say(self, msg):
        self.log.append(msg)

    def _ok(self):
        if not (self._ref and self._syn and self._ag):
            QMessageBox.warning(self, "Nicht bereit",
                                "Die Layer 'Arten', 'Arten_Synonyme' und "
                                "'Artengruppen' sind nicht verfügbar.")
            return False
        return True

    # ── Hinzufügen ──────────────────────────────────────────────────────────
    def _search(self, text):
        self.hits.clear()
        self._cands = []
        if not (self._ref and self._ag):
            return
        self._cands = sm.find_species(self._ref, self._ag, text)
        for c in self._cands:
            it = QListWidgetItem("%s   [%s]" % (c["anzeigename"], c["artengruppe"]))
            it.setData(Qt.UserRole, c)
            self.hits.addItem(it)

    def _add(self):
        if not self._ok():
            return
        it = self.hits.currentItem()
        if it is None:
            QMessageBox.information(self, "Zielart fehlt",
                                    "Bitte eine Zielart aus der Trefferliste wählen.")
            return
        c = it.data(Qt.UserRole)
        terms = [t.strip() for t in self.terms.toPlainText().splitlines() if t.strip()]
        if not terms:
            QMessageBox.information(self, "Keine Synonyme",
                                    "Bitte mindestens einen Suchbegriff eingeben.")
            return
        entries = [{"term": t, "entityid": c["entityid"],
                    "parentid": c["parentid"]} for t in terms]
        n, errs = sm.add_synonyms(self._syn, entries,
                                  bearbeiter=self.bearbeiter.text())
        self._say("%d Synonym(e) zu „%s“ [%s] ergänzt."
                  % (n, c["anzeigename"], c["artengruppe"]))
        for e in errs:
            self._say("  " + e)
        if n:
            self.terms.clear()
        self._load_layers()

    # ── Import ──────────────────────────────────────────────────────────────
    def _pick_import(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "Datei wählen", "", "Tabellen (*.csv *.xlsx *.xlsm);;Alle (*)")
        if p:
            self.imp_path.setText(p)

    def _dry_run(self):
        if not self._ok():
            return
        p = self.imp_path.text().strip()
        if not os.path.isfile(p):
            QMessageBox.warning(self, "Datei", "Bitte eine gültige Datei wählen.")
            return
        try:
            rows = sm.read_table(p)
        except Exception as e:
            QMessageBox.critical(self, "Lesefehler", str(e))
            return
        self._ready, problems = sm.prepare_import(
            rows, self._ref, self._syn, self._ag)
        self.table.setRowCount(0)
        for r in self._ready:
            self._row(r["term"], r["ziel"], r["gruppe"], "bereit")
        for term, grund, cands in problems:
            hint = grund + ((" – z. B. " + ", ".join(cands)) if cands else "")
            self._row(term, "", "", hint)
        self.apply_btn.setEnabled(bool(self._ready))
        self._say("Trockenlauf: %d bereit, %d Probleme (%d Zeilen gelesen)."
                  % (len(self._ready), len(problems), len(rows)))

    def _row(self, a, b, c, d):
        r = self.table.rowCount()
        self.table.insertRow(r)
        for i, v in enumerate((a, b, c, d)):
            self.table.setItem(r, i, QTableWidgetItem(str(v)))

    def _apply_import(self):
        if not (self._ok() and self._ready):
            return
        src = os.path.basename(self.imp_path.text().strip())
        n, errs = sm.add_synonyms(self._syn, self._ready,
                                  quelle="Import %s" % src,
                                  bearbeiter=self.bearbeiter.text())
        self._say("%d Synonym(e) importiert." % n)
        for e in errs:
            self._say("  " + e)
        self._ready = []
        self.apply_btn.setEnabled(False)
        self._load_layers()

    # ── Prüfung ─────────────────────────────────────────────────────────────
    def _check(self):
        if not self._ok():
            return
        r = sm.check(self._syn, self._ref, self._ag)
        def block(title, items):
            if not items:
                return "<p><b>%s:</b> keine</p>" % title
            return ("<p><b>%s (%d):</b><br>%s</p>"
                    % (title, len(items), ", ".join(str(x) for x in items[:40])
                       + (" …" if len(items) > 40 else "")))
        html = ["<p><b>Synonyme gesamt:</b> %d</p>" % r["gesamt"]]
        html.append(block("Ungültige Artengruppe (in der Kaskade nicht auffindbar)",
                          r["ungueltige_gruppe"]))
        html.append(block("Artengruppe passt nicht zur Zielart", r["gruppe_abweichend"]))
        html.append(block("Zielart existiert nicht", r["zielart_fehlt"]))
        html.append(block("Doppelte Suchbegriffe", r["doppelt"]))
        html.append("<p><i>Nachweis: Neue Einträge werden mit "
                    "erfasst_von / erfasst_am gespeichert.</i></p>")
        self.report.setHtml("".join(html))
        self._say("Prüfung abgeschlossen.")

    def _repair(self):
        if not self._ok():
            return
        n, bad = sm.repair_groups(self._syn, self._ref, self._ag)
        self._say("%d Artengruppen-Zuordnung(en) korrigiert." % n)
        if bad:
            self._say("Nicht korrigierbar (keine gültige Gruppe): %s"
                      % ", ".join(str(b) for b in bad[:20]))
        self._check()
