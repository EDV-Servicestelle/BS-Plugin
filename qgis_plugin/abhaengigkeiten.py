"""
abhaengigkeiten.py - Python-Pakete nachinstallieren, ohne OSGeo4W-Shell
=======================================================================

Zwei Faelle:

* Standardpakete (requirements.txt: scikit-learn, openpyxl, laspy, lazrs):
  werden kurz nach dem Start von QGIS geprueft und einmal pro Plugin-Version
  angeboten (standard_pruefen). Jederzeit auch ueber das Menue
  "Python-Pakete pruefen ...".
* Optionale Pakete fuer Spezialmodule (z. B. numba fuer Hydro): per Knopf im
  jeweiligen Dialog (installieren).

Bewusst ohne qpip: qpip installiert mit --target ohne --no-deps und legt
dabei auch numpy/scipy ein zweites Mal ins Profil (siehe unten).

Installationsort (derselbe wie bei qpip, falls beides vorkommt):

    <QGIS-Profil>/python/dependencies/<Python-Version>/

Keine Administratorrechte noetig, ein Plugin-Update loescht nichts.

Absicherung gegen eine kaputte QGIS-Installation, in zwei Schritten:

1. Probelauf (pip --dry-run --report): pip loest die Abhaengigkeiten auf.
   Alle Pakete, die QGIS selbst mitbringt (numpy, scipy, ...), sind dabei per
   Constraints auf ihre installierte Version festgelegt. Findet pip so keine
   Loesung, bricht die Installation ab - bewusst OHNE zweiten Versuch ohne
   Vorgaben.
2. Installation mit --no-deps: nur die Pakete, die wirklich fehlen. Was QGIS
   schon hat, wird NICHT ein zweites Mal in den Profilordner gelegt.

Warum Schritt 2 noetig ist: Mit --target installiert pip sonst auch numpy
und scipy erneut in den Profilordner, obwohl sie in QGIS vorhanden sind. Der
Profilordner steht in sys.path vorn - nach dem naechsten QGIS-Update wuerde
die alte Kopie die neue QGIS-Version ueberdecken und GDAL brechen.
"""

import json
import platform
import re
import sys
import tempfile
from importlib import metadata
from pathlib import Path

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QProcess
from qgis.PyQt.QtWidgets import (
    QDialog, QLabel, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QVBoxLayout,
)


def _norm(name):
    """Paketname wie pip ihn vergleicht (PEP 503)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def ziel_ordner():
    """Installationsort - identisch mit qpip."""
    py = f"{sys.version_info.major}.{sys.version_info.minor}"
    return (Path(QgsApplication.qgisSettingsDirPath())
            / "python" / "dependencies" / py)


def pfad_einbinden():
    """
    Zielordner in sys.path aufnehmen.

    qpip macht das selbst; diese Funktion sorgt dafuer, dass nachinstallierte
    Pakete auch ohne qpip gefunden werden.
    """
    ziel = str(ziel_ordner())
    if ziel not in sys.path:
        sys.path.insert(0, ziel)
        sys.path_importer_cache.clear()


def python_exe():
    """
    Python-Interpreter der QGIS-Installation.

    Unter Windows ist sys.executable die qgis-bin.exe, nicht Python
    (https://github.com/qgis/QGIS/issues/45646). Ein Aufruf
    `sys.executable -m pip` startet dort keine Installation.
    """
    if platform.system() == "Windows":
        for kandidat in ("python.exe", "python3.exe"):
            p = Path(sys.prefix) / kandidat
            if p.is_file():
                return str(p)
    elif platform.system() == "Darwin":
        for basis in (Path(sys.prefix) / "bin", Path(sys.executable).parent):
            for kandidat in ("python3", "python"):
                p = basis / kandidat
                if p.is_file():
                    return str(p)
    return sys.executable


def fehlende(module):
    """
    Liefert die Pakete, deren Import fehlschlaegt.

    module: dict {Importname: pip-Paketname}, z. B. {"numba": "numba"}
    """
    import importlib
    fehlt = []
    for imp, paket in module.items():
        try:
            importlib.import_module(imp)
        except ImportError:
            fehlt.append(paket)
    return fehlt


def _vorhanden():
    """{normierter Name: Version} aller Pakete AUSSERHALB des Zielordners."""
    ziel = ziel_ordner().resolve()
    ergebnis = {}
    for dist in metadata.distributions():
        name = dist.metadata.get("Name")
        if not name or not dist.version:
            continue
        try:
            ort = Path(str(dist.locate_file(""))).resolve()
        except Exception:
            ort = None
        if ort is not None and ort == ziel:
            continue
        ergebnis.setdefault(_norm(name), dist.version)
    return ergebnis


def _vorgaben(pakete):
    """pip-Constraints: alles, was QGIS mitbringt, auf die installierte Version."""
    gewuenscht = {_norm(re.split(r"[<>=!~\[; ]", p, 1)[0]) for p in pakete}
    return sorted((f"{n}=={v}" for n, v in _vorhanden().items()
                   if n not in gewuenscht), key=str.lower)


class _InstallDialog(QDialog):
    def __init__(self, pakete, parent=None):
        super().__init__(parent)
        self.setWindowTitle("BioSt-GIS – Pakete installieren")
        self.setMinimumWidth(560)
        self.ok = False
        self._pakete = pakete

        lo = QVBoxLayout(self)
        lo.addWidget(QLabel(f"Installiere: <b>{', '.join(pakete)}</b>"))
        self._bar = QProgressBar()
        self._bar.setRange(0, 0)
        lo.addWidget(self._bar)
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(200)
        lo.addWidget(self._log)
        self._btn = QPushButton("Abbrechen")
        self._btn.clicked.connect(self._schliessen)
        lo.addWidget(self._btn)

        ziel_ordner().mkdir(parents=True, exist_ok=True)
        self._tmp = tempfile.TemporaryDirectory(prefix="biost-pip-")
        self._vorgaben = Path(self._tmp.name) / "constraints.txt"
        self._vorgaben.write_text("\n".join(_vorgaben(pakete)) + "\n",
                                  encoding="utf-8")
        self._report = Path(self._tmp.name) / "report.json"
        self._schritt = 1

        self._proc = QProcess(self)
        self._proc.setProcessChannelMode(
            QProcess.ProcessChannelMode.MergedChannels)
        self._proc.readyReadStandardOutput.connect(self._lesen)
        self._proc.finished.connect(self._fertig)
        self._proc.errorOccurred.connect(self._fehler)

        self._schreibe("Schritt 1/2: Abhängigkeiten prüfen …")
        self._starte(["-m", "pip", "install", *pakete,
                      "--dry-run", "--ignore-installed",
                      "--report", str(self._report),
                      "--constraint", str(self._vorgaben),
                      "--disable-pip-version-check", "--quiet"])

    def _starte(self, args):
        self._schreibe(f"> python {' '.join(args)}")
        self._proc.start(python_exe(), args)

    def _schreibe(self, text):
        self._log.appendPlainText(text.rstrip())
        sb = self._log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _lesen(self):
        data = bytes(self._proc.readAllStandardOutput())
        self._schreibe(data.decode("utf-8", errors="replace"))

    def _fehler(self, _err):
        self._schreibe(f"\n✗ pip konnte nicht gestartet werden: "
                       f"{self._proc.errorString()}")

    def _fertig(self, code, _status=None):
        if self._schritt == 1:
            if code != 0:
                return self._abschluss(False)
            try:
                rep = json.loads(self._report.read_text(encoding="utf-8"))
                gewaehlt = [(i["metadata"]["name"], i["metadata"]["version"])
                            for i in rep.get("install", [])]
            except Exception as e:
                self._schreibe(f"✗ Ergebnis des Probelaufs unlesbar: {e}")
                return self._abschluss(False)
            da = _vorhanden()
            neu = [f"{n}=={v}" for n, v in gewaehlt if _norm(n) not in da]
            schon = [n for n, v in gewaehlt if _norm(n) in da]
            if schon:
                self._schreibe("Bereits in QGIS vorhanden (bleibt unberührt): "
                               + ", ".join(schon))
            if not neu:
                self._schreibe("Nichts zu installieren.")
                return self._abschluss(True)
            self._schritt = 2
            self._schreibe("\nSchritt 2/2: Installiere " + ", ".join(neu))
            self._starte(["-m", "pip", "install", *neu,
                          "--no-deps", "--target", str(ziel_ordner()),
                          "--upgrade",
                          "--disable-pip-version-check",
                          "--no-warn-script-location"])
            return
        self._abschluss(code == 0)

    def _abschluss(self, ok):
        self._bar.setRange(0, 1)
        self._bar.setValue(1)
        self.ok = ok
        if ok:
            pfad_einbinden()
            self._schreibe("\n✓ Installation abgeschlossen. "
                           "Bitte QGIS einmal neu starten.")
        else:
            self._schreibe(
                "\n✗ Installation fehlgeschlagen. Häufige Ursachen: keine "
                "Internetverbindung, Proxy/Firewall der Station, oder das "
                "Paket ist mit den Bibliotheken dieser QGIS-Version nicht "
                "vereinbar. Bitte diese Ausgabe an die EDV-Servicestelle "
                "schicken.")
        self._btn.setText("Schließen")

    def _schliessen(self):
        if self._proc.state() != QProcess.ProcessState.NotRunning:
            self._proc.kill()
            self._proc.waitForFinished(3000)
        self.accept()

    def closeEvent(self, ev):
        if self._proc.state() != QProcess.ProcessState.NotRunning:
            self._proc.kill()
            self._proc.waitForFinished(3000)
        super().closeEvent(ev)


def installieren(pakete, parent=None, zweck=""):
    """
    Fragt nach und installiert die Pakete. Gibt True bei Erfolg zurueck.

    Nach der Installation ist ein Neustart von QGIS noetig, damit Module,
    die beim Laden pruefen (z. B. core.hydro), die Pakete erkennen.
    """
    if not pakete:
        return True
    text = (f"Für {zweck} werden diese Python-Pakete benötigt:\n\n"
            if zweck else "Benötigte Python-Pakete:\n\n")
    text += "\n".join(f"  • {p}" for p in pakete)
    text += ("\n\nSie werden aus dem Internet (PyPI) in Ihr QGIS-Profil "
             "installiert. Administratorrechte sind nicht nötig.\n\n"
             "Jetzt installieren?")
    antwort = QMessageBox.question(
        parent, "BioSt-GIS – Pakete installieren", text,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes)
    if antwort != QMessageBox.StandardButton.Yes:
        return False
    dlg = _InstallDialog(list(pakete), parent)
    dlg.exec()
    return dlg.ok


HINWEIS = ("Fehlende Pakete installieren Sie über "
           "Erweiterungen → BioSt-GIS → „Python-Pakete prüfen …“.")


def standard_pakete():
    """{Importname: Anforderung} aus requirements.txt."""
    pfad = Path(__file__).with_name("requirements.txt")
    pakete = {}
    if not pfad.is_file():
        return pakete
    for zeile in pfad.read_text(encoding="utf-8").splitlines():
        anf, _, kommentar = zeile.partition("#")
        anf = anf.strip()
        if not anf:
            continue
        m = re.search(r"import:\s*([A-Za-z_][\w.]*)", kommentar)
        name = re.split(r"[<>=!~\[; ]", anf, 1)[0]
        imp = m.group(1) if m else name.replace("-", "_")
        pakete[imp] = anf
    return pakete


def standard_pruefen(parent=None, version="", still=True):
    """
    Prueft die Standardpakete und bietet die Installation an.

    still=True (beim Start): fragt nur einmal pro Plugin-Version; wer ablehnt,
    wird erst mit der naechsten Version wieder gefragt. still=False (Menue):
    fragt immer und meldet auch, wenn alles da ist.
    """
    from qgis.core import QgsSettings
    fehlt = fehlende(standard_pakete())
    if not fehlt:
        if not still:
            QMessageBox.information(
                parent, "BioSt-GIS – Python-Pakete",
                "Alle benötigten Python-Pakete sind vorhanden.")
        return True
    s = QgsSettings()
    schluessel = "BioSt-GIS/pakete_gefragt_fuer_version"
    if still and version and s.value(schluessel, "") == version:
        return False
    s.setValue(schluessel, version)
    return installieren(fehlt, parent, zweck="BioSt-GIS")
