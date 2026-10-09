"""
personen_dialog.py – Personen meiner Station
============================================
Formular für die Cloud-Admins der Stationen: Personen eintragen, ändern,
abmelden und wieder aktivieren. Die Liste liegt in der Fachdatenbank
(verwaltung.person). Was dort steht, setzt der Abgleich auf dem Server
alle 15 Minuten um – Datenbankzugang, QFieldCloud-Organisation und
Stations-Team – und schreibt das Ergebnis in die Spalte status zurück.

Die Datenbank prüft selbst, wer was darf (Zeilenschutz und Trigger):
  * ein Cloud-Admin sieht und pflegt nur die Personen seiner Station(en)
  * Kürzel und Station sind nach dem Anlegen fest
  * Löschen gibt es nicht – abmelden heißt „aktiv“ entfernen
  * die Cloud-Rolle „creator“ vergibt nur die EDV-Servicestelle
Dieses Formular macht die Regeln nur sichtbar und übersetzt die
Meldungen der Datenbank.

Die Statusauswertung (status_auswerten) ist ohne Qt testbar.
"""
from __future__ import annotations

import datetime as dt
import re

KUERZEL_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
ABGLEICH_TAKT_MIN = 15
ABGLEICH_ALARM_MIN = 45          # älter = Abgleich läuft vermutlich nicht

# Ampelstufen, aufsteigend nach Dringlichkeit
OK, AUS, WARTEN, FEHLER = 0, 1, 2, 3
AMPEL_FARBE = {OK: "#2B6E52", AUS: "#8A928E", WARTEN: "#B7791F", FEHLER: "#B42318"}

SPALTEN = ("kuerzel", "station", "vorname", "nachname", "email", "qfc_benutzer",
           "sensibel", "cloud_rolle", "aktiv", "gueltig_bis", "bemerkung",
           "status", "status_am", "beantragt_von", "beantragt_am",
           "geaendert_von", "geaendert_am")


# ── Statusauswertung (ohne Qt) ───────────────────────────────────────────

def _aware(t):
    if t is None:
        return None
    if t.tzinfo is None:
        return t.replace(tzinfo=dt.timezone.utc)
    return t


def status_auswerten(p: dict, jetzt: dt.datetime | None = None) -> tuple[int, str, list[str]]:
    """Ampel, Kurztext und Erklärungen für eine Zeile aus verwaltung.person."""
    jetzt = _aware(jetzt or dt.datetime.now(dt.timezone.utc))
    heute = jetzt.date()
    status = (p.get("status") or "").strip()
    teile = [t.strip() for t in status.split(",") if t.strip()] if status else []
    status_am = _aware(p.get("status_am"))
    geaendert_am = _aware(p.get("geaendert_am"))
    abgelaufen = p.get("gueltig_bis") is not None and p["gueltig_bis"] < heute
    soll_aktiv = bool(p.get("aktiv")) and not abgelaufen

    # Liegt eine Änderung vor, die der Abgleich noch nicht gesehen hat?
    ist_aktiv = any(t == "aktiv" for t in teile)
    ist_gesperrt = any(t.startswith("gesperrt") for t in teile)
    wartet = (not teile or teile == ["beantragt"] or status_am is None
              or (geaendert_am is not None and geaendert_am > status_am)
              or (soll_aktiv and ist_gesperrt) or (not soll_aktiv and ist_aktiv))
    if wartet:
        if soll_aktiv:
            txt = (f"Die Eintragung ist gespeichert und wird beim nächsten Abgleich umgesetzt "
                   f"(alle {ABGLEICH_TAKT_MIN} Minuten).")
        else:
            txt = (f"Die Abmeldung ist gespeichert und wird beim nächsten Abgleich umgesetzt "
                   f"(alle {ABGLEICH_TAKT_MIN} Minuten).")
        return WARTEN, "wartet auf Abgleich", [txt]

    stufe, kurz, erkl = OK, "", []

    def setze(s, k, e):
        nonlocal stufe, kurz
        erkl.append(e)
        if s > stufe or not kurz:
            stufe, kurz = max(stufe, s), k

    for t in teile:
        if t.startswith("FEHLER"):
            setze(FEHLER, "Fehler",
                  "Beim Abgleich ist ein Fehler aufgetreten. Die EDV-Servicestelle ist informiert.")
        elif t == "aktiv":
            setze(OK, "eingerichtet", "Datenbankzugang ist eingerichtet.")
        elif t.startswith("gesperrt"):
            grund = "abgelaufen („gültig bis“ überschritten)" if "abgelaufen" in t else "abgemeldet"
            setze(AUS, "abgemeldet",
                  f"Zugang gesperrt: {grund}. Erfasste Funde bleiben erhalten.")
        elif t == "wartet auf Registrierung in QFieldCloud":
            setze(WARTEN, "wartet auf Registrierung",
                  "Die Person muss sich zuerst selbst bei QFieldCloud registrieren. "
                  "Stimmt der QFieldCloud-Name genau (Groß-/Kleinschreibung)?")
        elif t == "Secret fehlt":
            setze(WARTEN, "Secret fehlt",
                  "Für die sensiblen Daten fehlt noch das Secret: Die EDV-Servicestelle erzeugt "
                  "die Zugangsdaten, danach legen Sie das Secret im Projekt an.")
        elif t == "sensible DB fehlt noch":
            setze(WARTEN, "sensible DB fehlt",
                  "Die Datenbank für sensible Daten der Station richtet die EDV-Servicestelle ein.")
        elif t == "QFieldCloud ok":
            setze(OK, "eingerichtet", "QFieldCloud: Mitglied der Organisation und im Stations-Team.")
        elif t == "ohne QFieldCloud":
            setze(OK, "eingerichtet",
                  "Kein QFieldCloud-Name eingetragen – nur Datenbankzugang.")
        elif t.startswith("QFieldCloud: geschuetztes Konto"):
            setze(OK, "eingerichtet",
                  "Das QFieldCloud-Konto verwaltet die EDV-Servicestelle selbst.")
        elif t == "aus QFieldCloud entfernt":
            setze(AUS, "abgemeldet", "Aus der QFieldCloud-Organisation entfernt.")
        elif t == "beantragt":
            continue
        else:
            setze(OK, t, t)
    return stufe, kurz or "eingerichtet", erkl


def letzter_abgleich(zeilen: list[dict]):
    """Jüngster Zeitstempel des Abgleichs über alle Zeilen."""
    ts = [_aware(z.get("status_am")) for z in zeilen if z.get("status_am")]
    return max(ts) if ts else None


def fehlertext(e: Exception) -> str:
    """Meldung der Datenbank in verständliche Worte fassen."""
    diag = getattr(e, "diag", None)
    msg = (getattr(diag, "message_primary", None) or str(e)).strip().splitlines()[0]
    code = getattr(e, "pgcode", None) or ""
    if code == "42P01":
        return ("Die Personenliste ist auf dem Server noch nicht eingerichtet. "
                "Bitte an die EDV-Servicestelle wenden.")
    if "row-level security" in msg:
        return "Diese Station dürfen Sie nicht pflegen."
    if code == "42501" and "permission denied" in msg:
        return "Keine Berechtigung für die Personenliste. Bitte an die EDV-Servicestelle wenden."
    if code == "23505" and "qfc_benutzer" in msg:
        return "Dieser QFieldCloud-Name ist schon einer anderen Person zugeordnet."
    if code == "23505" and "person_pkey" in msg:
        return "Dieses Kürzel ist schon vergeben – bitte ein anderes wählen."
    ersetzen = {"Kuerzel": "Kürzel", "waehlen": "wählen", "aendert": "ändert",
                "gehoert": "gehört", "Loeschen": "Löschen"}
    for a, b in ersetzen.items():
        msg = msg.replace(a, b)
    return msg


def _zeit(t) -> str:
    if not t:
        return ""
    try:
        return _aware(t).astimezone().strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(t)


# ── Qt-Teil ──────────────────────────────────────────────────────────────

from qgis.PyQt.QtCore import Qt, QDate                              # noqa: E402
from qgis.PyQt.QtGui import QColor, QBrush                         # noqa: E402
from qgis.PyQt.QtWidgets import (                                  # noqa: E402
    QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)


class PersonDialog(QDialog):
    """Eine Person eintragen oder ändern."""

    def __init__(self, parent, station: str, person: dict | None, edv: bool):
        super().__init__(parent)
        self.neu = person is None
        self.p = dict(person or {})
        self.station = station
        self.edv = edv
        self.setWindowTitle("Neue Person" if self.neu else f"Person {self.p['kuerzel']}")
        self.setMinimumWidth(460)

        lay = QVBoxLayout(self)
        form = QFormLayout()

        self.kuerzel = QLineEdit(self.p.get("kuerzel") or "")
        self.kuerzel.setPlaceholderText("z. B. mmuster – Kleinbuchstaben, Ziffern, _")
        self.kuerzel.setMaxLength(31)
        self.kuerzel.setEnabled(self.neu)
        self.kuerzel.setToolTip("Wird zur Anmeldung an der Datenbank (p_<kürzel>).\n"
                                "Nach dem Speichern nicht mehr änderbar.")
        form.addRow("Kürzel:", self.kuerzel)
        form.addRow("Station:", QLabel(f"<b>{station}</b>"))

        self.vorname = QLineEdit(self.p.get("vorname") or "")
        self.nachname = QLineEdit(self.p.get("nachname") or "")
        self.email = QLineEdit(self.p.get("email") or "")
        self.qfc = QLineEdit(self.p.get("qfc_benutzer") or "")
        self.qfc.setPlaceholderText("Benutzername nach der Registrierung bei QFieldCloud")
        self.qfc.setToolTip("Leer lassen, wenn die Person QFieldCloud nicht nutzt.")
        form.addRow("Vorname:", self.vorname)
        form.addRow("Nachname:", self.nachname)
        form.addRow("E-Mail:", self.email)
        form.addRow("QFieldCloud-Name:", self.qfc)

        self.sensibel = QCheckBox("Zugang zu den sensiblen Daten der Station")
        self.sensibel.setChecked(bool(self.p.get("sensibel")))
        form.addRow("", self.sensibel)

        self.rolle = QComboBox()
        self.rolle.addItems(["member", "creator"])
        self.rolle.setCurrentText(self.p.get("cloud_rolle") or "member")
        self.rolle.setEnabled(edv)
        if not edv:
            self.rolle.setToolTip("Die Cloud-Rolle „creator“ vergibt nur die EDV-Servicestelle.")
        form.addRow("Cloud-Rolle:", self.rolle)

        self.aktiv = QCheckBox("aktiv")
        self.aktiv.setChecked(self.p.get("aktiv", True) is not False)
        form.addRow("", self.aktiv)

        bis_row = QHBoxLayout()
        self.befristet = QCheckBox("befristet bis")
        self.bis = QDateEdit()
        self.bis.setCalendarPopup(True)
        self.bis.setDisplayFormat("dd.MM.yyyy")
        g = self.p.get("gueltig_bis")
        if g:
            self.befristet.setChecked(True)
            self.bis.setDate(QDate(g.year, g.month, g.day))
        else:
            self.bis.setDate(QDate.currentDate().addMonths(6))
        self.bis.setEnabled(self.befristet.isChecked())
        self.befristet.toggled.connect(self.bis.setEnabled)
        bis_row.addWidget(self.befristet)
        bis_row.addWidget(self.bis)
        bis_row.addStretch()
        form.addRow("Gültig:", bis_row)

        self.bemerkung = QPlainTextEdit(self.p.get("bemerkung") or "")
        self.bemerkung.setFixedHeight(60)
        form.addRow("Bemerkung:", self.bemerkung)
        lay.addLayout(form)

        hinweis = QLabel("Gelöscht wird nichts: Zum Abmelden „aktiv“ entfernen oder "
                         "eine Befristung setzen. Erfasste Funde bleiben erhalten.")
        hinweis.setWordWrap(True)
        hinweis.setStyleSheet("color: #4F5A55;")
        lay.addWidget(hinweis)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._pruefen)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _pruefen(self):
        k = self.kuerzel.text().strip().lower()
        if self.neu:
            if not KUERZEL_RE.match(k) or k.endswith("_qfc"):
                QMessageBox.warning(self, "Kürzel",
                                    "Das Kürzel muss mit einem Buchstaben beginnen und darf nur "
                                    "Kleinbuchstaben, Ziffern und _ enthalten (2–31 Zeichen).")
                return
            if not self.nachname.text().strip():
                QMessageBox.warning(self, "Nachname", "Bitte den Nachnamen eintragen.")
                return
        mail = self.email.text().strip()
        if mail and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", mail):
            QMessageBox.warning(self, "E-Mail", "Die E-Mail-Adresse sieht nicht gültig aus.")
            return
        if re.search(r"\s", self.qfc.text().strip()):
            QMessageBox.warning(self, "QFieldCloud-Name", "Der QFieldCloud-Name enthält Leerzeichen.")
            return
        self.accept()

    def werte(self) -> dict:
        def leer(s):
            s = s.strip()
            return s or None
        d = self.bis.date()
        return {
            "kuerzel": self.kuerzel.text().strip().lower(),
            "station": self.station,
            "vorname": leer(self.vorname.text()),
            "nachname": leer(self.nachname.text()),
            "email": leer(self.email.text()),
            "qfc_benutzer": leer(self.qfc.text()),
            "sensibel": self.sensibel.isChecked(),
            "cloud_rolle": self.rolle.currentText(),
            "aktiv": self.aktiv.isChecked(),
            "gueltig_bis": dt.date(d.year(), d.month(), d.day()) if self.befristet.isChecked() else None,
            "bemerkung": leer(self.bemerkung.toPlainText()),
        }


class PersonenDialog(QDialog):
    """Personen meiner Station – Liste, Status und Pflege."""

    KOPF = ("", "Status", "Kürzel", "Name", "QFieldCloud-Name", "Sensibel", "Gültig bis", "Stand")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Personen meiner Station")
        self.resize(1000, 640)
        self.con = None
        self.edv = False
        self.zeilen: list[dict] = []

        lay = QVBoxLayout(self)

        # Verbindung
        box = QGroupBox("Verbindung zur Fachdatenbank")
        bl = QHBoxLayout(box)
        from qgis.core import QgsSettings
        s = QgsSettings()
        self.dienst = QLineEdit(s.value("naturschutz/personen_dienst", "bs_fachdaten", type=str))
        self.benutzer = QLineEdit(s.value("naturschutz/personen_benutzer", "", type=str))
        self.benutzer.setPlaceholderText("p_<kürzel>")
        self.passwort = QLineEdit()
        self.passwort.setEchoMode(QLineEdit.EchoMode.Password)
        self.passwort.setPlaceholderText("wird nicht gespeichert")
        self.passwort.returnPressed.connect(self._verbinden)
        self.verbinden_btn = QPushButton("Verbinden")
        self.verbinden_btn.clicked.connect(self._verbinden)
        for lbl, w in (("Dienst:", self.dienst), ("Benutzer:", self.benutzer),
                       ("Passwort:", self.passwort)):
            bl.addWidget(QLabel(lbl))
            bl.addWidget(w)
        bl.addWidget(self.verbinden_btn)
        lay.addWidget(box)

        # Station und Filter
        top = QHBoxLayout()
        top.addWidget(QLabel("Station:"))
        self.station = QComboBox()
        self.station.setMinimumWidth(160)
        self.station.currentIndexChanged.connect(self._laden)
        top.addWidget(self.station)
        self.abgemeldete = QCheckBox("Abgemeldete anzeigen")
        self.abgemeldete.toggled.connect(self._fuellen)
        top.addWidget(self.abgemeldete)
        top.addStretch()
        self.abgleich_lbl = QLabel("")
        top.addWidget(self.abgleich_lbl)
        lay.addLayout(top)

        # Tabelle
        self.tab = QTableWidget(0, len(self.KOPF))
        self.tab.setHorizontalHeaderLabels(self.KOPF)
        self.tab.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tab.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.tab.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tab.verticalHeader().setVisible(False)
        hh = self.tab.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.tab.itemSelectionChanged.connect(self._details)
        self.tab.cellDoubleClicked.connect(lambda *_: self._bearbeiten())
        lay.addWidget(self.tab, 1)

        self.detail = QLabel("Bitte zuerst verbinden.")
        self.detail.setWordWrap(True)
        self.detail.setTextFormat(Qt.TextFormat.RichText)
        self.detail.setMinimumHeight(70)
        self.detail.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.detail.setStyleSheet("background: #F4F5F1; border: 1px solid #CDD3CC; "
                                  "border-radius: 6px; padding: 8px;")
        lay.addWidget(self.detail)

        # Knöpfe
        kn = QHBoxLayout()
        self.neu_btn = QPushButton("Neue Person …")
        self.edit_btn = QPushButton("Bearbeiten …")
        self.ab_btn = QPushButton("Abmelden")
        self.an_btn = QPushButton("Wieder aktivieren")
        self.akt_btn = QPushButton("Aktualisieren")
        self.neu_btn.clicked.connect(self._neu)
        self.edit_btn.clicked.connect(self._bearbeiten)
        self.ab_btn.clicked.connect(lambda: self._aktiv_setzen(False))
        self.an_btn.clicked.connect(lambda: self._aktiv_setzen(True))
        self.akt_btn.clicked.connect(self._laden)
        for b in (self.neu_btn, self.edit_btn, self.ab_btn, self.an_btn):
            kn.addWidget(b)
        kn.addStretch()
        kn.addWidget(self.akt_btn)
        schliessen = QPushButton("Schließen")
        schliessen.clicked.connect(self.accept)
        kn.addWidget(schliessen)
        lay.addLayout(kn)
        self._knoepfe()

    # ── Verbindung ───────────────────────────────────────────────────────
    def _verbinden(self):
        from .pg_verbindung import connect
        self._trennen()
        p = {"service": self.dienst.text().strip(), "user": self.benutzer.text().strip(),
             "password": self.passwort.text()}
        if not p["service"]:
            QMessageBox.warning(self, "Dienst", "Bitte den Dienst eintragen, z. B. bs_fachdaten.")
            return
        try:
            self.con = connect(p, timeout=8)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Verbindung",
                                "Keine Verbindung zur Fachdatenbank.\n\n"
                                "Ist der VPN-Zugang (WireGuard) aktiv und das Passwort richtig?\n\n"
                                f"{str(e).strip().splitlines()[0] if str(e).strip() else e}")
            return
        from qgis.core import QgsSettings
        s = QgsSettings()
        s.setValue("naturschutz/personen_dienst", p["service"])
        s.setValue("naturschutz/personen_benutzer", p["user"])
        self.passwort.clear()

        try:
            stationen = self._stationen()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Personenliste", fehlertext(e))
            self._trennen()
            return
        if not stationen:
            QMessageBox.information(
                self, "Personen meiner Station",
                "Sie sind für keine Station als Cloud-Admin eingetragen.\n\n"
                "Die EDV-Servicestelle schaltet Cloud-Admins frei.")
            self._trennen()
            return
        self.station.blockSignals(True)
        self.station.clear()
        self.station.addItems(stationen)
        self.station.blockSignals(False)
        self.verbinden_btn.setText("Neu verbinden")
        self._laden()

    def _trennen(self):
        if self.con is not None:
            try:
                self.con.close()
            except Exception:
                pass
        self.con = None
        self.zeilen = []

    def _stationen(self) -> list[str]:
        with self.con.cursor() as c:
            c.execute("SELECT pg_has_role(current_user, 'bs_verwaltung', 'MEMBER')")
            if c.fetchone()[0]:
                try:
                    c.execute("SET ROLE bs_verwaltung")
                    self.edv = True
                except Exception:
                    self.edv = False
            if self.edv:
                c.execute(r"""SELECT substring(rolname FROM 5) FROM pg_roles
                               WHERE rolname ~ '^stn_[a-z][a-z0-9_]*$'
                                 AND rolname !~ '_(admin|sensibel)$' ORDER BY 1""")
            else:
                c.execute("SELECT unnest(verwaltung.meine_admin_stationen()) ORDER BY 1")
            stationen = [r[0] for r in c.fetchall()]
            # Zugriff auf die Tabelle früh prüfen (fehlt sie, kommt hier die Meldung)
            c.execute("SELECT 1 FROM verwaltung.person LIMIT 1")
        return stationen

    # ── Daten ────────────────────────────────────────────────────────────
    def _laden(self):
        if self.con is None or not self.station.currentText():
            return
        try:
            with self.con.cursor() as c:
                c.execute(f"SELECT {', '.join(SPALTEN)} FROM verwaltung.person "
                          "WHERE station = %s ORDER BY nachname NULLS LAST, vorname, kuerzel",
                          (self.station.currentText(),))
                self.zeilen = [dict(zip(SPALTEN, z)) for z in c.fetchall()]
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Personenliste", fehlertext(e))
            return
        self._fuellen()

    def _sichtbar(self) -> list[dict]:
        if self.abgemeldete.isChecked():
            return self.zeilen
        heute = dt.date.today()
        return [z for z in self.zeilen
                if z["aktiv"] and not (z["gueltig_bis"] and z["gueltig_bis"] < heute)
                or status_auswerten(z)[1] == "wartet auf Abgleich"]

    def _fuellen(self):
        alt = self._auswahl()
        alt_k = alt["kuerzel"] if alt else None
        zeilen = self._sichtbar()
        self.tab.setRowCount(len(zeilen))
        jetzt = dt.datetime.now(dt.timezone.utc)
        for i, z in enumerate(zeilen):
            stufe, kurz, _ = status_auswerten(z, jetzt)
            name = " ".join(x for x in (z["vorname"], z["nachname"]) if x)
            werte = ("●", kurz, z["kuerzel"], name, z["qfc_benutzer"] or "",
                     "ja" if z["sensibel"] else "",
                     z["gueltig_bis"].strftime("%d.%m.%Y") if z["gueltig_bis"] else "",
                     _zeit(z["status_am"]))
            for j, w in enumerate(werte):
                it = QTableWidgetItem(w)
                it.setData(Qt.ItemDataRole.UserRole, z["kuerzel"])
                if j == 0:
                    it.setForeground(QBrush(QColor(AMPEL_FARBE[stufe])))
                    it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if stufe == AUS:
                    it.setForeground(QBrush(QColor(AMPEL_FARBE[AUS])))
                self.tab.setItem(i, j, it)
        # Auswahl wiederherstellen
        for i in range(self.tab.rowCount()):
            if self.tab.item(i, 2).text() == alt_k:
                self.tab.selectRow(i)
                break
        self._abgleich_anzeigen(jetzt)
        self._details()

    def _abgleich_anzeigen(self, jetzt):
        t = letzter_abgleich(self.zeilen)
        if t is None:
            self.abgleich_lbl.setText("Noch kein Abgleich gelaufen")
            self.abgleich_lbl.setStyleSheet("color: #B7791F;")
            return
        alter = (jetzt - t).total_seconds() / 60
        if alter > ABGLEICH_ALARM_MIN:
            self.abgleich_lbl.setText(f"Letzter Abgleich: {_zeit(t)} – läuft nicht? EDV informieren")
            self.abgleich_lbl.setStyleSheet("color: #B42318; font-weight: 600;")
        else:
            self.abgleich_lbl.setText(f"Letzter Abgleich: {_zeit(t)}")
            self.abgleich_lbl.setStyleSheet("color: #4F5A55;")

    def _auswahl(self) -> dict | None:
        r = self.tab.currentRow()
        if r < 0 or not self.tab.selectedItems():
            return None
        k = self.tab.item(r, 2).text()
        return next((z for z in self.zeilen if z["kuerzel"] == k), None)

    def _details(self):
        z = self._auswahl()
        self._knoepfe()
        if self.con is None:
            self.detail.setText("Bitte zuerst verbinden.")
            return
        if z is None:
            n = len(self._sichtbar())
            self.detail.setText(f"{n} Person{'en' if n != 1 else ''} angezeigt. "
                                "Eine Zeile auswählen, um den Stand zu sehen.")
            return
        stufe, kurz, erkl = status_auswerten(z)
        farbe = AMPEL_FARBE[stufe]
        name = " ".join(x for x in (z["vorname"], z["nachname"]) if x) or z["kuerzel"]
        if (z["nachname"] or "").startswith("(Bestand"):
            erkl = erkl + ["Aus dem Bestand übernommen – bitte unter „Bearbeiten“ "
                           "Vor- und Nachname ergänzen."]
        zeilen = "".join(f"<li>{e}</li>" for e in erkl)
        info = []
        if z["beantragt_von"]:
            info.append(f"eingetragen {_zeit(z['beantragt_am'])} von {z['beantragt_von']}")
        if z["geaendert_von"]:
            info.append(f"geändert {_zeit(z['geaendert_am'])} von {z['geaendert_von']}")
        self.detail.setText(
            f"<b>{name}</b> ({z['kuerzel']}) – <span style='color:{farbe}; font-weight:600'>{kurz}</span>"
            f"<ul style='margin:4px 0 4px -20px'>{zeilen}</ul>"
            f"<span style='color:#5E6762'>{' · '.join(info)}</span>")

    def _knoepfe(self):
        verbunden = self.con is not None and bool(self.station.currentText())
        z = self._auswahl() if verbunden else None
        self.neu_btn.setEnabled(verbunden)
        self.akt_btn.setEnabled(verbunden)
        self.edit_btn.setEnabled(z is not None)
        self.ab_btn.setEnabled(bool(z and z["aktiv"]))
        self.an_btn.setEnabled(bool(z and not z["aktiv"]))

    # ── Schreiben ────────────────────────────────────────────────────────
    def _ausfuehren(self, sql: str, args: tuple) -> int | None:
        try:
            with self.con.cursor() as c:
                c.execute(sql, args)
                return c.rowcount
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Nicht gespeichert", fehlertext(e))
            return None

    def _neu(self):
        dlg = PersonDialog(self, self.station.currentText(), None, self.edv)
        if not dlg.exec():
            return
        w = dlg.werte()
        felder = ["kuerzel", "station", "vorname", "nachname", "email", "qfc_benutzer",
                  "sensibel", "aktiv", "gueltig_bis", "bemerkung"]
        if self.edv:
            felder.append("cloud_rolle")
        sql = (f"INSERT INTO verwaltung.person ({', '.join(felder)}) "
               f"VALUES ({', '.join(['%s'] * len(felder))})")
        if self._ausfuehren(sql, tuple(w[f] for f in felder)) is not None:
            self._laden()
            self._waehle(w["kuerzel"])

    def _bearbeiten(self):
        z = self._auswahl()
        if z is None:
            return
        dlg = PersonDialog(self, z["station"], z, self.edv)
        if not dlg.exec():
            return
        w = dlg.werte()
        felder = ["vorname", "nachname", "email", "qfc_benutzer", "sensibel",
                  "aktiv", "gueltig_bis", "bemerkung"]
        if self.edv:
            felder.append("cloud_rolle")
        sql = (f"UPDATE verwaltung.person SET {', '.join(f + ' = %s' for f in felder)} "
               "WHERE kuerzel = %s")
        n = self._ausfuehren(sql, tuple(w[f] for f in felder) + (z["kuerzel"],))
        if n == 0:
            QMessageBox.warning(self, "Nicht gespeichert",
                                "Die Person wurde nicht gefunden – bitte aktualisieren.")
        self._laden()

    def _aktiv_setzen(self, aktiv: bool):
        z = self._auswahl()
        if z is None:
            return
        name = " ".join(x for x in (z["vorname"], z["nachname"]) if x) or z["kuerzel"]
        if not aktiv:
            frage = (f"{name} abmelden?\n\nBeim nächsten Abgleich wird der Datenbankzugang "
                     "gesperrt und die Person aus QFieldCloud entfernt. Gelöscht wird nichts – "
                     "erfasste Funde bleiben erhalten.")
            if z["sensibel"]:
                frage += ("\n\nDie Person hatte Zugang zu sensiblen Daten: Bitte die "
                          "EDV-Servicestelle bitten, ihre Secrets in QFieldCloud zu löschen.")
        else:
            frage = f"{name} wieder aktivieren?"
        if QMessageBox.question(self, "Personen meiner Station", frage) \
                != QMessageBox.StandardButton.Yes:
            return
        sql = "UPDATE verwaltung.person SET aktiv = %s"
        args: tuple = (aktiv,)
        if aktiv and z["gueltig_bis"] and z["gueltig_bis"] < dt.date.today():
            sql += ", gueltig_bis = NULL"
        sql += " WHERE kuerzel = %s"
        if self._ausfuehren(sql, args + (z["kuerzel"],)) is not None:
            self._laden()

    def _waehle(self, kuerzel: str):
        for i in range(self.tab.rowCount()):
            if self.tab.item(i, 2).text() == kuerzel:
                self.tab.selectRow(i)
                return

    def done(self, r):
        self._trennen()
        super().done(r)
