"""
core/import_core.py – Artname-Matching & Altdaten-Import-Algorithmen
=====================================================================
Enthält:
  - TF-IDF-Index (sklearn)
  - Levenshtein / Ensemble-Scoring
  - k-NN Spatial Index (BallTree)
  - Synonyme laden (data/synonyme.json)
  - build_arten_lookup(), import_altdaten()
  - Feldwert-Matching (Institution, Status, Stadium)
  - Validierungsmetriken (Precision@k, MRR, Cohen's κ)

Keine Qt-Abhängigkeiten (außer QgsVectorLayer für Typisierung).
"""
"""
FT – Altdaten importieren
=========================
3-Tab-Dialog:
  Tab 1 – Quelle:    Datei laden, Artname-Feld + Suchmodus, Testsuche
  Tab 2 – Mapping:   Pro Zielfeld: Quellfeld ODER Fixwert ODER Auto
  Tab 3 – Import:    Log + Fortschritt
"""

import os, sqlite3
import uuid as _uuid_mod

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QGroupBox, QTextEdit,
    QDialogButtonBox, QFileDialog, QComboBox, QCheckBox,
    QProgressBar, QTabWidget, QWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QSpinBox, QSizePolicy,
)
from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal, QDate, QDateTime, QTime
from qgis.PyQt.QtGui import QColor, QBrush
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry,
    QgsPointXY, QgsCoordinateReferenceSystem,
    QgsCoordinateTransform, QgsCoordinateTransformContext,
    QgsWkbTypes,
)
from datetime import date


# numpy + sklearn – in OSGeo4W/QGIS vorhanden; bei Fehlen: Auto-Install

def _ensure_dependencies():
    missing = []
    try:
        import numpy  # noqa
    except ImportError as _e_np:
        missing.append("numpy")
        print(f"[FT-Import] numpy fehlt: {_e_np}")
    try:
        import sklearn  # noqa
    except ImportError as _e_sk:
        missing.append("scikit-learn")
        print(f"[FT-Import] sklearn fehlt: {_e_sk}")
    if not missing:
        return True
    from qgis.PyQt.QtWidgets import QMessageBox
    reply = QMessageBox.question(
        None, "Fehlende Bibliotheken",
        f"Das Plugin benötigt: {', '.join(missing)}\n\n"
        "Jetzt automatisch via pip installieren?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    )
    if reply != QMessageBox.StandardButton.Yes:
        return False
    import sys
    from qgis.PyQt.QtCore import QThread
    from qgis.PyQt.QtCore import pyqtSignal as _pS2
    from qgis.PyQt.QtWidgets import (QDialog as _QD2, QVBoxLayout as _QVL2,
                                      QTextEdit as _QTE2, QLabel as _QL2,
                                      QProgressBar as _QPB2, QPushButton as _QPB3)
    class _PipWorker(QThread):
        line_out = _pS2(str)
        done     = _pS2(bool)
        def __init__(self, pkgs): super().__init__(); self.pkgs = pkgs
        def run(self):
            import subprocess, sys
            try:
                # Argumentliste statt Kommandozeile, auf allen Systemen:
                # Ohne shell=True gibt es keine Kommandozeile, die
                # interpretiert werden koennte. Leerzeichen im Pfad sind
                # dabei kein Problem - subprocess setzt die Anfuehrungs-
                # zeichen unter Windows selbst (list2cmdline).
                proc = subprocess.Popen(
                    [sys.executable, "-m", "pip", "install",
                     "--no-warn-script-location"] + self.pkgs,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True)
                for line in proc.stdout: self.line_out.emit(line.rstrip())
                proc.wait(); self.done.emit(proc.returncode == 0)
            except Exception as e:
                self.line_out.emit(f"Fehler: {e}"); self.done.emit(False)
    dlg = _QD2(); dlg.setWindowTitle("Bibliotheken installieren …")
    dlg.setMinimumWidth(500)
    lo = _QVL2(dlg); lo.addWidget(_QL2(f"Installiere: {', '.join(missing)}"))
    bar = _QPB2(); bar.setRange(0, 0); lo.addWidget(bar)
    log = _QTE2(); log.setReadOnly(True); log.setFixedHeight(160); lo.addWidget(log)
    dlg.setModal(True); dlg.show()
    result = [False]
    worker = _PipWorker(missing)
    def on_line(t): log.append(t); log.verticalScrollBar().setValue(log.verticalScrollBar().maximum())
    def on_done(ok):
        result[0] = ok; bar.setRange(0, 1); bar.setValue(1)
        log.append("\n✓ Fertig – bitte QGIS neu starten." if ok else "\n✗ Fehlgeschlagen.")
        b = _QPB3("Schließen"); b.clicked.connect(dlg.accept); dlg.layout().addWidget(b)
    worker.line_out.connect(on_line); worker.done.connect(on_done)
    worker.start(); dlg.exec()
    return result[0]


try:
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    from sklearn.neighbors import BallTree
    _SKLEARN_AVAILABLE = True
except Exception as _sklearn_err:
    import sys as _sys_sk
    print(f"[FT-Import] Fehler: {_sklearn_err}", file=_sys_sk.stderr)
    _SKLEARN_AVAILABLE = (_ensure_dependencies()
                          if isinstance(_sklearn_err, ImportError) else False)
    if _SKLEARN_AVAILABLE:
        try:
            import numpy as np
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity
            from sklearn.neighbors import BallTree
        except ImportError:
            _SKLEARN_AVAILABLE = False


# __file__ ist in core/ → eine Ebene hoch zum Plugin-Root
_PLUGIN_DIR     = os.path.dirname(os.path.dirname(__file__))
_NUTZUNG_GPKG   = os.path.join(_PLUGIN_DIR, "data", "Nutzung.gpkg")
_NUTZUNG_TABLE  = "202601_gru_vereinf_05170000_wesel_epsg25832__nutzung"
_NUTZUNG_FIELD  = "nutzart"
_ARTEN_LOOKUP_CACHE: dict = {}
_ARTEN_LOOKUP_MODE:  str  = ""

_REF_GPKG   = os.path.join(_PLUGIN_DIR,
               "data", "fundpunkte_tiere", "Referenzen.gpkg")

# Felder die durch Artname-Auflösung automatisch gesetzt werden
AUTO_FIELDS = {"Artname", "Artengruppe", "Artname_wiss", "Artname_deutsch"}
# Felder die durch Geometrie automatisch gesetzt werden
GEO_FIELDS  = {"Utm_east", "Utm_north"}
# Frueher: automatisch gesetzte, aber ueberschreibbare Datumsfelder.
# Aenderungsdatum ist inzwischen ein geschuetztes Systemfeld (NOW_FIELDS),
# die Menge bleibt fuer die Kategorisierung im Dialog erhalten.
DATE_FIELDS = set()   # Beobachtungsdatum bleibt manuell mappbar
# Felder die nicht manuell gemappt werden können
SYSTEM_FIELDS = {"fid", "geom"}
# Felder die beim Import immer automatisch mit einer neuen UUID befüllt
# werden und deshalb nicht gemappt werden dürfen (Quell-IDs landen in
# der Tabelle Fund_Quellfelder und gehen damit nicht verloren)
UUID_FIELDS = {"Kennung"}
# Felder die beim Import immer mit dem aktuellen Datum belegt werden
# und deshalb nicht gemappt werden dürfen (Anlage A: Editierbar = nein).
# Ein Datum aus der Quelle gehört fachlich in Beobachtungsdatum.
# Aenderungsdatum ist in der DB DATETIME NOT NULL, Eingabedatum DATE NOT NULL;
# beide sind laut Anlage A Systemfelder (Editierbar = nein).
NOW_FIELDS  = {"Eingabedatum", "Aenderungsdatum"}
# Alle Felder die automatisch gesetzt und gegen Mapping geschützt sind
PROTECTED_FIELDS = UUID_FIELDS | NOW_FIELDS


# ── Artensuche ────────────────────────────────────────────────────────────────

# ── TF-IDF Artname-Index (wird beim ersten Aufruf gebaut) ────────────────────

# Synonyme: häufige Altdaten-Bezeichnungen → normalisierter Suchterm
_SYNONYMS: dict = {}


def _load_synonyms() -> dict:
    """
    Lädt die Artname-Synonymtabelle aus data/synonyme.json.
    Gibt ein flaches Dict {quell_artname: suchterm} zurück.
    Fällt auf ein leeres Dict zurück wenn die Datei fehlt.
    """
    import json as _json
    json_path = os.path.join(_PLUGIN_DIR, "data", "synonyme.json")
    if not os.path.isfile(json_path):
        return {}
    try:
        with open(json_path, encoding="utf-8") as _f:
            data = _json.load(_f)
        flat = {}
        for kategorie in data.get("synonyme", {}).values():
            flat.update(kategorie)
        return flat
    except Exception as _e:
        import traceback as _tb
        print(f"[FT-Import] synonyme.json Ladefehler: {_e}")
        return {}


_SYNONYMS = _load_synonyms()



# Habitat-Mapping: trainiert auf ATKIS-Nutzungsklassen (Kreis Wesel, nutzart-Feld)
# Schluessel: Substring des Artengruppen-Namens (normalisiert)
# Wert: {nutzart-Substring (normalisiert): Boost-Faktor}
_ARTENGRUPPE_HABITAT = {
    "amph": {
        "fliessgew": 1.9, "stehendes gew": 1.8, "sumpf": 1.8,
        "landwirtschaft": 1.3, "sport-, freizeit": 1.2,
        "unland": 1.1, "wald": 0.8, "wohnbau": 0.5,
        "industrie": 0.4, "strassenverkehr": 0.3,
    },
    "fisch": {
        "fliessgew": 2.0, "stehendes gew": 1.9, "sumpf": 1.5,
        "hafenbecken": 1.4, "schiffsverkehr": 1.2,
        "landwirtschaft": 0.7, "wald": 0.5,
    },
    "libel": {
        "fliessgew": 1.9, "stehendes gew": 1.8, "sumpf": 1.7,
        "landwirtschaft": 1.3, "sport-, freizeit": 1.2, "wald": 0.8,
    },
    "kocher": {
        "fliessgew": 1.9, "stehendes gew": 1.7, "sumpf": 1.6,
    },
    "eintagsfli": {
        "fliessgew": 1.9, "stehendes gew": 1.6, "sumpf": 1.5,
    },
    "steinfli": {
        "fliessgew": 1.9, "stehendes gew": 1.5,
    },
    "schnecke": {
        "sumpf": 1.6, "fliessgew": 1.5, "stehendes gew": 1.5,
        "wald": 1.3, "gehoelz": 1.2,
    },
    "saeuget": {
        "wald": 1.4, "gehoelz": 1.3, "landwirtschaft": 1.2,
        "sport-, freizeit": 1.1, "flaeche gemischter": 1.1,
    },
    "vogel": {
        "wald": 1.3, "gehoelz": 1.3, "fliessgew": 1.3,
        "stehendes gew": 1.3, "sumpf": 1.2, "landwirtschaft": 1.2,
        "sport-, freizeit": 1.1, "heide": 1.2,
        "strassenverkehr": 0.7, "industrie": 0.6,
    },
    "flederm": {
        "wald": 1.5, "gehoelz": 1.4, "fliessgew": 1.3,
        "stehendes gew": 1.3, "wohnbau": 1.2,
        "flaeche gemischter": 1.2, "flaeche besonderer": 1.2,
        "industrie": 1.1,
    },
    "kafer": {
        "wald": 1.5, "gehoelz": 1.4, "landwirtschaft": 1.2,
        "unland": 1.3, "heide": 1.3, "tagebau": 1.2, "halde": 1.2,
    },
    "laufkaef": {
        "landwirtschaft": 1.4, "wald": 1.3, "gehoelz": 1.2,
        "unland": 1.3, "fliessgew": 1.2,
    },
    "tagfalter": {
        "heide": 1.7, "unland": 1.5, "landwirtschaft": 1.4,
        "sport-, freizeit": 1.3, "halde": 1.3, "tagebau": 1.2,
        "wald": 0.9, "strassenverkehr": 0.5,
    },
    "geradflueg": {
        "heide": 1.7, "landwirtschaft": 1.5, "unland": 1.4,
        "sport-, freizeit": 1.3, "sumpf": 1.2,
    },
    "ameise": {
        "wald": 1.4, "gehoelz": 1.3, "heide": 1.4, "unland": 1.2,
    },
    "biene": {
        "landwirtschaft": 1.4, "sport-, freizeit": 1.3,
        "heide": 1.4, "gehoelz": 1.2, "unland": 1.3,
    },
    "wanze": {
        "landwirtschaft": 1.3, "gehoelz": 1.2, "heide": 1.3,
    },
    "zikade": {
        "landwirtschaft": 1.3, "heide": 1.4, "unland": 1.3,
    },
}
_PROTECTION_BOOST_MAP = {
    "ffh":1.4,"natura":1.3,"vogelschutz":1.2,"spa":1.2,
    "naturschutz":1.2,"nsg":1.2,"lsg":1.1,"naturpark":1.1,
}
def _get_habitat_boost(lu, ag):
    lu_n = _normalize(lu)
    ag_n = _normalize(ag)
    best = 1.0
    for ag_key, habitat_map in _ARTENGRUPPE_HABITAT.items():
        if ag_key not in ag_n:
            continue
        for kw, factor in habitat_map.items():
            if kw in lu_n:
                best = max(best, factor)
    return best
def _get_protection_boost(pv):
    pv=pv.lower()
    for k,f2 in _PROTECTION_BOOST_MAP.items():
        if k in pv:return f2
    return 1.0
class _ContextLayers:
    def __init__(self):
        self.landuse_layer=self.landuse_field=None
        self.protect_layer=self.protect_field=None
        self._lu_index=self._pr_index=None
        self._lu_feats={};self._pr_feats={};self.built=False
    def build(self):
        from qgis.core import QgsSpatialIndex
        self._lu_index=self._pr_index=None
        self._lu_feats={};self._pr_feats={}
        if self.landuse_layer and self.landuse_field:
            idx=QgsSpatialIndex()
            for feat in self.landuse_layer.getFeatures():
                idx.insertFeature(feat);self._lu_feats[feat.id()]=feat
            self._lu_index=idx
        if self.protect_layer and self.protect_field:
            idx=QgsSpatialIndex()
            for feat in self.protect_layer.getFeatures():
                idx.insertFeature(feat);self._pr_feats[feat.id()]=feat
            self._pr_index=idx
        self.built=bool(self._lu_index or self._pr_index)
    def get_context(self,x,y):
        from qgis.core import QgsPointXY,QgsGeometry,QgsRectangle
        pt=QgsGeometry.fromPointXY(QgsPointXY(x,y))
        bb=QgsRectangle(x,y,x,y)
        lu_val=pr_val=""
        if self._lu_index:
            for fid in self._lu_index.intersects(bb):
                feat=self._lu_feats.get(fid)
                if feat and feat.geometry().contains(pt):
                    lu_val=str(feat[self.landuse_field] or "");break
        if self._pr_index:
            for fid in self._pr_index.intersects(bb):
                feat=self._pr_feats.get(fid)
                if feat and feat.geometry().contains(pt):
                    pr_val=str(feat[self.protect_field] or "");break
        return lu_val,pr_val
_CONTEXT=_ContextLayers()
def ensemble_rank(candidates,knn_vote,lu_val,pr_val):
    sc={}
    for sim,entry in candidates[:12]:
        eid=entry["entityid"]
        sc[eid]={"entry":entry,"tfidf":float(sim),"knn":0.0,"hab":1.0,"prot":1.0}
    if knn_vote:
        eid=knn_vote["entry"]["entityid"]
        conf=knn_vote["count"]/max(knn_vote.get("total",1),1)
        if eid not in sc:
            sc[eid]={"entry":knn_vote["entry"],"tfidf":0.0,"knn":0.0,"hab":1.0,"prot":1.0}
        sc[eid]["knn"]=float(conf)
    pb=_get_protection_boost(pr_val)
    for s in sc.values():
        ag=s["entry"].get("Name_deutsch","") or s["entry"].get("term","")
        s["hab"]=_get_habitat_boost(lu_val,ag);s["prot"]=pb
    res=[]
    for s in sc.values():
        score=0.40*s["tfidf"]+0.35*s["knn"]+0.15*(s["hab"]-1.0)+0.10*(s["prot"]-1.0)
        res.append((score,s["entry"],s))
    res.sort(key=lambda x:x[0],reverse=True)
    return res

class _TFIDFIndex:
    """sklearn TF-IDF (Bi+Trigramme, sparse float32). 4.5x Build, 70x Query."""
    def __init__(self):
        self._vectorizer = None; self._matrix = None
        self._entries = []; self._idf = {}; self.built = False

    @staticmethod
    def _char_ngrams(text):
        t = f' {_normalize(text)} '
        return [t[i:i+n] for n in (2,3) for i in range(len(t)-n+1)]

    def build(self, entries):
        if not _SKLEARN_AVAILABLE: return
        self._entries = entries
        corpus = [e["term"]+" "+e["Name_deutsch"] for e in entries]
        self._vectorizer = TfidfVectorizer(
            analyzer=self._char_ngrams, sublinear_tf=True, dtype=np.float32)
        self._matrix = self._vectorizer.fit_transform(corpus)
        self._idf    = self._vectorizer.vocabulary_
        self.built   = True

    def query(self, raw, top_k=5):
        if not self.built or not _SKLEARN_AVAILABLE: return []
        sims    = cosine_similarity(self._vectorizer.transform([raw]), self._matrix)[0]
        k       = min(top_k, len(sims))
        top_idx = np.argpartition(sims, -k)[-k:]
        top_idx = top_idx[np.argsort(sims[top_idx])[::-1]]
        return [(float(sims[i]), self._entries[i]) for i in top_idx]

    def batch_query(self, raws, top_k=5):
        """Alle Suchbegriffe auf einmal – 70x schneller als N Einzel-Queries."""
        if not self.built or not raws or not _SKLEARN_AVAILABLE:
            return [[] for _ in raws]
        sims = cosine_similarity(self._vectorizer.transform(raws), self._matrix)
        results = []
        for row in sims:
            k = min(top_k, len(row))
            top_idx = np.argpartition(row, -k)[-k:]
            top_idx = top_idx[np.argsort(row[top_idx])[::-1]]
            results.append([(float(row[i]), self._entries[i]) for i in top_idx])
        return results

    def ensemble_query(self, raw, top_k=5, alpha=0.65):
        """TF-IDF pre-filter (top-30) + Levenshtein Reranking."""
        candidates = self.query(raw, top_k=30)
        if not candidates: return []
        raw_n  = _normalize(raw)
        scored = [(_ensemble_sim(s, _lev_sim(raw_n, e), alpha), e)
                  for s, e in candidates]
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:top_k]

def search_arten(query, by="both", limit=20):
    if not query.strip() or not os.path.isfile(_REF_GPKG):
        return []
    con = sqlite3.connect(_REF_GPKG)
    cur = con.cursor()
    q = f"%{query.strip()}%"
    if by == "wiss":
        cur.execute(
            "SELECT entityid,term,Name_deutsch,parentid FROM Arten "
            "WHERE parentid!='nan' AND lower(term) LIKE lower(?) "
            "ORDER BY term LIMIT ?", (q, limit))
    elif by == "de":
        cur.execute(
            "SELECT entityid,term,Name_deutsch,parentid FROM Arten "
            "WHERE parentid!='nan' AND lower(Name_deutsch) LIKE lower(?) "
            "ORDER BY Name_deutsch LIMIT ?", (q, limit))
    else:
        cur.execute(
            "SELECT entityid,term,Name_deutsch,parentid FROM Arten "
            "WHERE parentid!='nan' AND "
            "(lower(term) LIKE lower(?) OR lower(Name_deutsch) LIKE lower(?)) "
            "ORDER BY Name_deutsch,term LIMIT ?", (q, q, limit))
    rows = [{"entityid":r[0],"term":r[1],"Name_deutsch":r[2] or "","parentid":r[3]}
            for r in cur.fetchall()]
    con.close()
    return rows


def _synonym_unscharf(syn_key: str):
    """
    Letzter Versuch, wenn ein Synonymziel nicht exakt in der Liste steht.

    Gesucht wird nur noch am ANFANG des Namens, nicht mehr irgendwo darin,
    und ein blosser Gattungsname wird nicht mehr still auf eine Art
    verengt. Beides ist Erfahrung aus echten Daten:

      * '%acrocephalus%' traf frueher auch 'Ocypus macrocephalus' - einen
        Kurzfluegelkaefer. Weil die Reihenfolge nach Namenslaenge ging,
        gewann der Kaefer gegen jeden Rohrsaenger.
      * Ein Gattungsname ohne Art ('bufo', 'nyctalus') passt auf mehrere
        Arten. Eine davon auszuwaehlen hiesse, eine Bestimmung zu
        behaupten, die die Rohdaten nicht hergeben. Solche Faelle bleiben
        offen und landen in Fund_Fehlend - dort entscheidet die Station.

    Rueckgabe: Eintrag oder None.
    """
    if not syn_key or not os.path.isfile(_REF_GPKG):
        return None
    import sqlite3 as _sq
    schluessel = syn_key.strip()
    con = _sq.connect(_REF_GPKG)
    try:
        treffer = con.execute(
            "SELECT entityid,term,Name_deutsch,parentid"
            " FROM Arten WHERE parentid!='nan' AND"
            " (lower(term) LIKE lower(?) OR lower(Name_deutsch) LIKE lower(?))"
            " ORDER BY length(term) LIMIT 25",
            (f"{schluessel}%", f"{schluessel}%")).fetchall()
    finally:
        con.close()
    if not treffer:
        return None
    # Gattungsname (ein Wort) mit mehreren Arten darunter -> keine Auswahl.
    if " " not in schluessel:
        arten = {r[1] for r in treffer}
        if len(arten) > 1:
            return None
    r = treffer[0]
    return {"entityid": r[0], "term": r[1] or "",
            "Name_deutsch": r[2] or "", "parentid": r[3] or ""}


def _normalize(s: str) -> str:
    """Normalisiert Umlaute und Gross-/Kleinschreibung fuer den Lookup.
    Wandelt oe->ö, ae->ä, ue->ü und umgekehrt, damit beide Schreibweisen matchen.
    """
    return (s.lower().strip()
              .replace("ä","ae").replace("ö","oe")
              .replace("ü","ue").replace("ß","ss")
              .replace("Ä","ae").replace("Ö","oe")
              .replace("Ü","ue"))


def build_arten_lookup(by):
    """
    Erstellt ein Lookup-Dict fuer die Artname-Auflosung.
    Alle Keys werden umlaut-normalisiert gespeichert, damit Varianten
    wie 'Erdkroete' und 'Erdkröte' beide gefunden werden.
    """
    if not os.path.isfile(_REF_GPKG):
        return {}
    con = sqlite3.connect(_REF_GPKG)
    cur = con.cursor()
    cur.execute("SELECT entityid,term,Name_deutsch,parentid FROM Arten "
                "WHERE parentid!='nan'")
    lu = {}
    for eid, term, name_de, parentid in cur.fetchall():
        entry = {"entityid":eid,"term":term or "","Name_deutsch":name_de or "","parentid":parentid or ""}
        if by in ("wiss","both") and term:
            lu[term.lower().strip()] = entry          # original
            lu[_normalize(term)]     = entry          # umlaut-normalisiert
        if by in ("de","both") and name_de:
            lu[name_de.lower().strip()] = entry       # original
            lu[_normalize(name_de)]     = entry       # umlaut-normalisiert
    con.close()
    return lu


# ── Import-Funktion ───────────────────────────────────────────────────────────


def _ensure_fehlend_table(gpkg_path: str):
    """
    Legt die Tabelle Fund_Fehlend im Ziel-GPKG an (falls nicht vorhanden).
    Speichert Kennung + Artname-Rohwert nicht aufgeloester Features.
    """
    import sqlite3 as _sq
    con = _sq.connect(gpkg_path)
    cur = con.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS \"Fund_Fehlend\" ("
        "fid        INTEGER PRIMARY KEY AUTOINCREMENT,"
        "Kennung    TEXT,"
        "Artname_roh TEXT,"
        "Artname_wiss TEXT,"
        "Beobachtungsdatum TEXT,"
        "Kartierer  TEXT,"
        "Fundort    TEXT"
        ")"
    )
    # In GPKG-Metadaten eintragen (damit QGIS es als Layer sieht)
    cur.execute(
        "INSERT OR IGNORE INTO gpkg_contents "
        "(table_name, data_type, identifier, description) "
        "VALUES ('Fund_Fehlend','attributes','Fund_Fehlend',"
        "'Nicht aufgeloeste Artnamen beim Import')"
    )
    con.commit()
    con.close()


def _append_fehlend(gpkg_path: str, rows: list):
    """
    Fuegt Zeilen in Fund_Fehlend ein.
    rows: [(Kennung, Artname_roh, Artname_wiss, Beobachtungsdatum, Kartierer, Fundort), ...]
    """
    if not rows:
        return
    import sqlite3 as _sq
    con = _sq.connect(gpkg_path)
    cur = con.cursor()
    cur.executemany(
        "INSERT OR IGNORE INTO \"Fund_Fehlend\" "
        "(Kennung, Artname_roh, Artname_wiss, Beobachtungsdatum, Kartierer, Fundort) "
        "VALUES (?,?,?,?,?,?)",
        rows
    )
    con.commit()
    con.close()


def import_altdaten(src_layer, tgt_layer, mapping, artname_field,
                    artname_mode, progress_cb=None, artname_overrides=None,
                    field_value_overrides=None):
    """
    mapping: Liste von Dicts:
      {"tgt": fund_field, "mode": "src"|"fix"|"auto",
       "src_field": str|None, "fix_value": str|None}
    Gibt (importiert, nicht_aufgeloest, fehler) zurück.
    """
    global _ARTEN_LOOKUP_CACHE, _ARTEN_LOOKUP_MODE
    if artname_mode != _ARTEN_LOOKUP_MODE or not _ARTEN_LOOKUP_CACHE:
        _ARTEN_LOOKUP_CACHE = build_arten_lookup(artname_mode)
        _ARTEN_LOOKUP_MODE  = artname_mode
    lookup = dict(_ARTEN_LOOKUP_CACHE)
    if artname_overrides:
        lookup.update(artname_overrides)
    features = list(src_layer.getFeatures())

    src_crs = src_layer.crs()
    tgt_crs = tgt_layer.crs() or QgsCoordinateReferenceSystem("EPSG:25832")
    transform = None
    if src_crs.isValid() and tgt_crs.isValid() and src_crs != tgt_crs:
        transform = QgsCoordinateTransform(
            src_crs, tgt_crs, QgsCoordinateTransformContext())

    tgt_fields = tgt_layer.fields()
    imported = not_resolved = errors = 0
    today = date.today().isoformat()

    # Ziel-GPKG-Pfad ermitteln (fuer Fund_Fehlend-Tabelle)
    _gpkg_path = None
    _src_str = tgt_layer.source()
    if "|" in _src_str:
        _gpkg_path = _src_str.split("|")[0]
    elif _src_str.lower().endswith(".gpkg"):
        _gpkg_path = _src_str
    if _gpkg_path and os.path.isfile(_gpkg_path):
        _ensure_fehlend_table(_gpkg_path)
    _fehlend_rows     = []
    _fehlend_pending  = None  # Hilfsdaten für Fund_Fehlend, pro Feature

    # Nicht gemappte Quellfelder ermitteln
    _mapped_src = set()
    for m in mapping:
        if m.get("src_field"):
            _mapped_src.add(m["src_field"].lower())
    if artname_field:
        _mapped_src.add(artname_field.lower())
    _extra_fields = [
        f.name() for f in src_layer.fields()
        if f.name().lower() not in _mapped_src
    ]
    _extra_rows = []
    # Zielfeld -> Quellfeld (fuer Fund_Fehlend: Altdaten heissen anders als das
    # Zielschema, ein Zugriff ueber den Zielnamen liefe sonst ins Leere)
    _src_of = {m["tgt"]: m["src_field"] for m in mapping
               if m.get("mode") == "src" and m.get("src_field")}
    if _extra_fields and _gpkg_path and os.path.isfile(_gpkg_path):
        _ensure_extras_table(_gpkg_path, _extra_fields)

    # Pflicht-Datumsfelder (NOT NULL) einmalig ermitteln – fuer verstaendliche
    # Meldungen statt eines kryptischen OGR-NOT-NULL-Fehlers je Datensatz
    _required_dates = []
    try:
        from qgis.core import QgsFieldConstraints as _QFC
        for _fld in tgt_fields:
            if "date" not in (_fld.typeName() or "").lower():
                continue
            if _fld.name() in NOW_FIELDS:
                continue          # wird ohnehin automatisch gesetzt
            if int(_fld.constraints().constraints()) & int(
                    _QFC.Constraint.ConstraintNotNull):
                _required_dates.append(_fld.name())
    except Exception:
        _required_dates = [n for n in ("Beobachtungsdatum",)
                           if tgt_fields.indexFromName(n) >= 0]
    _date_problems = {}   # Zielfeld -> [Anzahl, {Beispielwerte}]
    _skipped_date  = 0

    tgt_layer.startEditing()
    for i, src_feat in enumerate(features):
        if progress_cb and i % 50 == 0:
            progress_cb(int(i / max(len(features),1) * 100),
                        f"Feature {i+1}/{len(features)} …")
        try:
            _fehlend_pending = None  # Reset für jedes Feature
            # Artname auflösen – 3-stufig:
            # 1. Direktlookup + Override
            # 2. Synonymtabelle
            # 3. TF-IDF (gleiche Logik wie Tab 3 Scan)
            raw_name  = src_feat[artname_field] if artname_field else None
            art_entry = None
            if raw_name:
                raw_str = str(raw_name).strip()
                raw_n   = _normalize(raw_str)
                # Stufe 1: Direktlookup (inkl. Overrides aus Tab 3)
                art_entry = lookup.get(raw_str.lower()) or lookup.get(raw_n)
                # Stufe 2: Synonymtabelle
                if not art_entry:
                    syn_key = _SYNONYMS.get(raw_n) or _SYNONYMS.get(raw_str.lower())
                    if syn_key:
                        art_entry = (lookup.get(syn_key.lower())
                                     or lookup.get(_normalize(syn_key)))
                        if not art_entry:
                            art_entry = _synonym_unscharf(syn_key)
                # Stufe 3: TF-IDF (Fallback fuer unbekannte Namen)
                if not art_entry and _TFIDF_INDEX.built:
                    # Ensemble: TF-IDF + Levenshtein (Schwelle 0.30)
                    tf_results = _TFIDF_INDEX.ensemble_query(raw_str, top_k=5)
                    if tf_results:
                        has_unb = "unbestimmt" in raw_n
                        if has_unb:
                            for _ens, _entry in tf_results:
                                if "unbestimmt" in _entry["Name_deutsch"].lower():
                                    art_entry = _entry; break
                        if not art_entry:
                            best_ens, best_entry = tf_results[0]
                        # Genus-Check: wenn Quellname Gattung enthält,
                        # aber Treffer eine andere Gattung hat → verwerfen
                        _src_genus = raw_str.split()[0].lower() if raw_str else ""
                        _tgt_genus = best_entry.get("term","").split()[0].lower()
                        _genus_ok  = (_src_genus == _tgt_genus or
                                      len(_src_genus) < 4 or
                                      _src_genus not in best_entry.get("term","").lower())
                        if best_ens > 0.30 and _genus_ok:
                            art_entry = best_entry
                        elif best_ens > 0.45 and not _genus_ok:
                            pass  # Gattung stimmt nicht → kein Auto-Match
                        elif best_ens > 0.60:
                            art_entry = best_entry  # hoher Score trotzdem
            if not art_entry and raw_name:
                not_resolved += 1
                # Fuer Fund_Fehlend: Hilfsdaten merken (Kennung erst nach Build)
                def _safe(feat, field):
                    try:
                        v = feat[field]
                        return str(v) if v is not None and str(v).upper() != "NULL" else ""
                    except Exception: return ""
                _fehlend_pending = {
                    "artname_roh": str(raw_name),
                    "datum":       _safe(src_feat, _src_of.get(
                                            "Beobachtungsdatum", "Beobachtungsdatum")),
                    "kartierer":   _safe(src_feat, _src_of.get(
                                            "Kartierer", "Kartierer")),
                    "fundort":     _safe(src_feat, _src_of.get(
                                            "Fundort", "Fundort")),
                }

            # Geometrie
            geom = src_feat.geometry()
            if transform and geom and not geom.isEmpty():
                geom.transform(transform)

            new_feat = QgsFeature(tgt_fields)
            if geom:
                new_feat.setGeometry(geom)

            # Auto: Artenauflösung
            if art_entry:
                _s(new_feat, tgt_fields, "Artname",         art_entry.get("entityid", ""))
                _s(new_feat, tgt_fields, "Artengruppe",     art_entry.get("parentid", ""))
                _s(new_feat, tgt_fields, "Artname_wiss",    art_entry.get("term", ""))
                _s(new_feat, tgt_fields, "Artname_deutsch", art_entry.get("Name_deutsch", ""))
            elif raw_name:
                _s(new_feat, tgt_fields, "Artname_wiss", str(raw_name))

            # Auto: Kennung immer mit neuer UUID befüllen (nicht mappbar).
            # Format wie der QGIS-Ausdruck uuid(): {GROSSBUCHSTABEN}
            for _uf in UUID_FIELDS:
                _s(new_feat, tgt_fields, _uf,
                   "{" + str(_uuid_mod.uuid4()).upper() + "}")

            # Auto: Koordinaten
            if geom and not geom.isEmpty():
                pt = geom.asPoint()
                _s(new_feat, tgt_fields, "Utm_east",  round(pt.x(), 2))
                _s(new_feat, tgt_fields, "Utm_north", str(round(pt.y(), 2)))

            # Auto: Aenderungsdatum + Eingabedatum = Zeitpunkt des Imports.
            # Beide sind NOT NULL und werden typgerecht (QDateTime/QDate)
            # gesetzt; Beobachtungsdatum kommt weiterhin aus dem Mapping.
            for _nf in NOW_FIELDS:
                _s(new_feat, tgt_fields, _nf, _now_for_field(tgt_fields, _nf))

            # Manuelles Mapping aus Dialog-Tabelle
            for m in mapping:
                tgt_f = m["tgt"]
                # Schutz: automatisch gesetzte Felder (Kennung, Eingabedatum)
                # nie durch ein Mapping überschreiben – auch nicht aus einer
                # älteren gespeicherten Konfiguration
                if tgt_f in PROTECTED_FIELDS:
                    continue
                if m["mode"] == "src" and m.get("src_field"):
                    _sf = m["src_field"]
                    _raw_val = (src_feat[_sf]
                                if _sf in [f.name() for f in src_feat.fields()]
                                else None)
                elif m["mode"] == "fix" and m.get("fix_value") is not None:
                    _raw_val = m["fix_value"]
                else:
                    _raw_val = None
                # Manuelle Feldwert-Zuordnung aus Tab 3 anwenden
                if _raw_val is not None and field_value_overrides:
                    _fv_m = field_value_overrides.get(tgt_f.lower(), {})
                    _rs2  = str(_raw_val).strip()
                    _mp2  = _fv_m.get(_rs2.lower()) or _fv_m.get(_rs2)
                    if _mp2: _raw_val = _mp2
                if m["mode"] in ("src", "fix") and _raw_val is not None:
                    # Datumsfelder typgerecht konvertieren; leere Werte
                    # nicht in Nicht-Text-Felder schreiben (sonst NULL in
                    # einer NOT-NULL-Spalte -> INSERT schlaegt fehl)
                    _conv = _coerce_for_field(tgt_fields, tgt_f, _raw_val)
                    _tn   = _field_typename(tgt_fields, tgt_f)
                    if _conv is None:
                        # Datumswert nicht eindeutig lesbar -> merken und melden,
                        # statt still eine NULL zu erzeugen
                        if "date" in _tn and not _is_unset(_raw_val):
                            _slot = _date_problems.setdefault(tgt_f, [0, set()])
                            _slot[0] += 1
                            if len(_slot[1]) < 5:
                                _slot[1].add(str(_raw_val).strip()[:40])
                    elif (not str(_conv).strip()
                          and "string" not in _tn):
                        pass
                    else:
                        _s(new_feat, tgt_fields, tgt_f, _conv)
                # mode == "auto" → bereits oben gesetzt, nichts tun

            # Pflicht-Datumsfeld leer? -> Datensatz mit klarer Meldung
            # ueberspringen statt am NOT-NULL-Constraint scheitern zu lassen
            _miss_date = [_n for _n in _required_dates
                          if _is_unset(new_feat[_n])]
            if _miss_date:
                _skipped_date += 1
                errors += 1
                if _skipped_date <= 3 and progress_cb:
                    progress_cb(-1, f"  \u26a0 Datensatz {i+1} uebersprungen: "
                                    f"{', '.join(_miss_date)} ohne gueltiges Datum")
                continue

            tgt_layer.addFeature(new_feat)
            imported += 1
            # Kennung aus gebautem Feature lesen (für Fehlend + Extras)
            _kennung_now = ""
            try:
                _ki2 = tgt_fields.indexFromName("Kennung")
                if _ki2 >= 0:
                    _kennung_now = str(new_feat.attribute(_ki2) or "")
            except Exception: pass
            # Nicht gemappte Felder in Fund_Quellfelder
            if _extra_fields:
                def _sv(feat, fname):
                    try:
                        v = feat[fname]
                        from qgis.core import NULL as _QN4
                        if v is None or v is _QN4: return None
                        s = str(v).strip()
                        return s if s and s.upper() != "NULL" else None
                    except Exception: return None
                _extra_rows.append(
                    tuple([_kennung_now]
                          + [_sv(src_feat, fld) for fld in _extra_fields])
                )
            # Fehlend-Tabelle
            if _fehlend_pending is not None:
                _fehlend_rows.append((
                    _kennung_now,
                    _fehlend_pending["artname_roh"],
                    "",
                    _fehlend_pending["datum"],
                    _fehlend_pending["kartierer"],
                    _fehlend_pending["fundort"],
                ))
        except Exception as _imp_err:
            errors += 1
            if errors == 1:  # Ersten Fehler ins Log schreiben
                import traceback as _tb
                if progress_cb:
                    progress_cb(-1, f"✗ Fehler Feature {i+1}: {_imp_err}\n"
                                   + _tb.format_exc()[:500])

    tgt_layer.commitChanges()

    # Zusammenfassung der Datumsprobleme
    if _date_problems and progress_cb:
        progress_cb(-1, "\n  Datumswerte, die nicht eindeutig lesbar waren:")
        for _fname, (_cnt, _samples) in sorted(_date_problems.items()):
            progress_cb(-1, f"    {_fname}: {_cnt} Wert(e), z. B. "
                            + ", ".join(sorted(_samples)))
        progress_cb(-1, "    Hinweis: zweistellige Jahre (z. B. 19.07.01), reine "
                        "Jahreszahlen und Excel-Datumsserien werden bewusst nicht "
                        "geraten. Bitte in der Quelle auf ein eindeutiges Format "
                        "bringen (z. B. TT.MM.JJJJ).")
    if _skipped_date and progress_cb:
        progress_cb(-1, f"  \u26a0 {_skipped_date} Datensatz/Datensaetze ohne "
                        f"gueltiges Pflichtdatum uebersprungen "
                        f"({', '.join(_required_dates)}).")

    # Fund_Fehlend mit Kennung befuellen
    if _fehlend_rows and _gpkg_path and os.path.isfile(_gpkg_path):
        # Kennung aus den zuletzt importierten Features lesen
        # _fehlend_rows hat 7-Tupel mit Index; Kennung aus Artname_wiss (Rohwert)
        final_rows = []
        for r in _fehlend_rows:
            # r = (None, artname_roh, artname_wiss, datum, kartierer, fundort, feat_idx)
            final_rows.append((
                r[0],   # Kennung (None = unbekannt, Feature wurde evtl. importiert)
                r[1],   # Artname_roh
                r[2],   # Artname_wiss
                r[3],   # Beobachtungsdatum
                r[4],   # Kartierer
                r[5],   # Fundort
            ))
        _append_fehlend(_gpkg_path, final_rows)
        if progress_cb and final_rows:
            progress_cb(-1, f"  → {len(final_rows)} Einträge in Fund_Fehlend gespeichert")

    # Nicht gemappte Felder in Fund_Quellfelder schreiben
    if _extra_rows and _extra_fields and _gpkg_path and os.path.isfile(_gpkg_path):
        _append_extras(_gpkg_path, _extra_fields, _extra_rows)
        if progress_cb:
            progress_cb(-1,
                f"  → {len(_extra_rows)} Zeilen in Fund_Quellfelder "
                f"({len(_extra_fields)} Felder) gespeichert")

    return imported, not_resolved, errors


def _ensure_extras_table(gpkg_path: str, extra_fields: list):
    """
    Legt Fund_Quellfelder an (oder ergänzt fehlende Spalten).
    extra_fields: [Feldname, ...]
    """
    import sqlite3 as _sq
    con = _sq.connect(gpkg_path)
    cur = con.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS \"Fund_Quellfelder\" ("
        "fid     INTEGER PRIMARY KEY AUTOINCREMENT,"
        "Kennung TEXT"
        ")"
    )
    # Vorhandene Spalten prüfen und fehlende ergänzen
    cur.execute("PRAGMA table_info(\"Fund_Quellfelder\")")
    existing = {row[1].lower() for row in cur.fetchall()}
    for field in extra_fields:
        if field.lower() not in existing:
            try:
                cur.execute(
                    f"ALTER TABLE \"Fund_Quellfelder\" "
                    f"ADD COLUMN \"{field}\" TEXT"
                )
            except Exception:
                pass
    # GPKG-Metadaten
    cur.execute(
        "INSERT OR IGNORE INTO gpkg_contents "
        "(table_name,data_type,identifier,description) "
        "VALUES ('Fund_Quellfelder','attributes','Fund_Quellfelder',"
        "'Nicht gemappte Quellfelder – verknuepft ueber Kennung')"
    )
    con.commit()
    con.close()


def _append_extras(gpkg_path: str, extra_fields: list, rows: list):
    """
    Fuegt Zeilen in Fund_Quellfelder ein.
    rows: [(kennung, val1, val2, ...), ...]  – Reihenfolge wie extra_fields
    """
    if not rows or not extra_fields:
        return
    import sqlite3 as _sq
    cols  = ", ".join(f'"{f}"' for f in extra_fields)
    ph    = ", ".join(["?"] * (len(extra_fields) + 1))
    sql   = f'INSERT OR IGNORE INTO "Fund_Quellfelder" (Kennung, {cols}) VALUES ({ph})'
    con   = _sq.connect(gpkg_path)
    cur   = con.cursor()
    cur.executemany(sql, rows)
    con.commit()
    con.close()



def _field_typename(fields, name) -> str:
    """Typname des Zielfeldes in Kleinschreibung ('qdatetime', 'qdate', ...)."""
    idx = fields.indexFromName(name)
    if idx < 0:
        return ""
    try:
        return (fields.at(idx).typeName() or "").lower()
    except Exception:
        return ""


def _now_for_field(fields, name):
    """
    Liefert den Jetzt-Wert im Typ des Zielfeldes.
    Wichtig: Der OGR-Provider verwirft einen reinen String, wenn er ihn nicht
    in ein Datum konvertieren kann -> das Feld wird NULL und eine NOT-NULL-
    Spalte (z. B. Fund.Aenderungsdatum) laesst den INSERT scheitern.
    """
    tn = _field_typename(fields, name)
    if "datetime" in tn:
        return QDateTime.currentDateTime()
    if "date" in tn:
        return QDate.currentDate()
    return date.today().isoformat()


# Datumsmuster fuer Altdaten. Bewusst NICHT enthalten sind Muster mit
# zweistelligem Jahr ("dd.MM.yy"): Qt liest "19.07.01" als 1901-07-19, was
# still um 100 Jahre falsche Datensaetze erzeugen wuerde. Solche Werte werden
# stattdessen gemeldet (siehe _date_problems im Import).
_DATETIME_PATTERNS = ("yyyy-MM-dd HH:mm:ss", "yyyy-MM-dd HH:mm",
                      "dd.MM.yyyy HH:mm:ss", "dd.MM.yyyy HH:mm",
                      "dd/MM/yyyy HH:mm:ss", "dd/MM/yyyy HH:mm")
_DATE_PATTERNS     = ("yyyy-MM-dd", "yyyy-M-d", "dd.MM.yyyy", "d.M.yyyy",
                      "yyyy/MM/dd", "dd/MM/yyyy", "dd-MM-yyyy", "yyyyMMdd")


def _parse_date_text(txt: str):
    """
    Liest einen Datums-Text und gibt (QDate, QTime|None) zurueck,
    oder (None, None) wenn der Wert nicht eindeutig lesbar ist.
    Mehrdeutiges wird bewusst abgelehnt statt geraten.
    """
    # 1. ISO (auch mit Zeitanteil, tolerant gegenueber / und . als Trenner)
    dt = QDateTime.fromString(txt, Qt.DateFormat.ISODate)
    if dt.isValid():
        return dt.date(), (dt.time() if "T" in txt or " " in txt else None)
    # 2. Muster mit Zeitanteil
    for pat in _DATETIME_PATTERNS:
        dt = QDateTime.fromString(txt, pat)
        if dt.isValid():
            return dt.date(), dt.time()
    # 3. Reine Datumsmuster auf dem Gesamtstring
    for pat in _DATE_PATTERNS:
        d = QDate.fromString(txt, pat)
        if d.isValid():
            return d, None
    # 4. Zeitanteil abtrennen und erneut als reines Datum versuchen
    head = txt.replace("T", " ").split(" ")[0].strip()
    if head and head != txt:
        d = QDate.fromString(head, Qt.DateFormat.ISODate)
        if d.isValid():
            return d, None
        for pat in _DATE_PATTERNS:
            d = QDate.fromString(head, pat)
            if d.isValid():
                return d, None
    return None, None


def _coerce_for_field(fields, name, value):
    """
    Wandelt einen Quellwert in den Typ des Zielfeldes.
    Datumsfelder erhalten echte QDate/QDateTime-Objekte; laesst sich ein Wert
    nicht eindeutig als Datum lesen, wird None geliefert (Feld wird nicht
    geschrieben), damit keine stille NULL in eine NOT-NULL-Spalte laeuft.
    Nicht-Datumsfelder bleiben unveraendert.
    """
    tn = _field_typename(fields, name)
    if "date" not in tn:
        return value
    want_dt = "datetime" in tn
    if isinstance(value, QDateTime):
        return value if want_dt else value.date()
    if isinstance(value, QDate):
        return QDateTime(value, QTime(0, 0)) if want_dt else value
    if value is None:
        return None
    txt = str(value).strip()
    if not txt or txt.upper() == "NULL":
        return None
    d, t = _parse_date_text(txt)
    if d is None:
        return None
    if not want_dt:
        return d
    # Ohne Zeitanteil auf Mitternacht setzen - NICHT auf die aktuelle Uhrzeit,
    # sonst bekommt ein historischer Datensatz eine irrefuehrende Zeit.
    return QDateTime(d, t if t is not None else QTime(0, 0))


def _is_unset(v) -> bool:
    """True, wenn ein Attributwert leer/NULL/ungueltig ist."""
    if v is None:
        return True
    try:
        from qgis.core import NULL as _N
        if v is _N:
            return True
    except Exception:
        pass
    if isinstance(v, (QDate, QDateTime)):
        return not v.isValid()
    if isinstance(v, str):
        return not v.strip() or v.strip().upper() == "NULL"
    return False


def _q_ident(name: str) -> str:
    """
    Quotet einen SQL-Bezeichner (Tabellen- oder Spaltenname) sicher.

    Werte gehoeren in Platzhalter (?), Bezeichner koennen das nicht: SQL
    erlaubt keine Parametrisierung von Tabellen- und Spaltennamen. Deshalb
    der vorgeschriebene Weg - in doppelte Anfuehrungszeichen setzen und
    enthaltene Anfuehrungszeichen verdoppeln. Damit kann ein Name die
    Zeichenkette nicht verlassen.
    """
    if not isinstance(name, str) or not name or "\x00" in name:
        raise ValueError(f"Unzulaessiger SQL-Bezeichner: {name!r}")
    return '"' + name.replace('"', '""') + '"'


def _s(feat, fields, name, value):
    idx = fields.indexFromName(name)
    if idx >= 0:
        feat.setAttribute(idx, value)


# ── Dialog ────────────────────────────────────────────────────────────────────

# Farben für die Mapping-Tabelle
COLOR_AUTO = QColor(220, 240, 220)   # grün = automatisch
COLOR_GEO  = QColor(220, 235, 250)   # blau = Geometrie
COLOR_DATE = QColor(250, 245, 215)   # gelb = Datum-Default
COLOR_MAP  = QColor(255, 255, 255)   # weiß = manuell
COLOR_UUID = QColor(235, 225, 245)   # violett = automatische UUID





# ── Levenshtein-Distanz (pure Python, kein Import nötig) ─────────────────────

def _levenshtein(s1: str, s2: str) -> int:
    """Editierdistanz zwischen zwei Strings."""
    if s1 == s2: return 0
    if not s1: return len(s2)
    if not s2: return len(s1)
    if len(s1) < len(s2): s1, s2 = s2, s1
    prev = list(range(len(s2) + 1))
    for c1 in s1:
        curr = [prev[0] + 1]
        for j, c2 in enumerate(s2):
            curr.append(min(prev[j+1]+1, curr[-1]+1,
                            prev[j] + (0 if c1 == c2 else 1)))
        prev = curr
    return prev[-1]


def _lev_sim(raw_n: str, entry: dict) -> float:
    """
    Normalisierte Levenshtein-Ähnlichkeit (0–1) zwischen
    einem normalisierten Suchbegriff und einem Arten-Eintrag.
    Nimmt das Maximum aus Vergleich mit term und Name_deutsch.
    """
    t_n  = _normalize(entry["term"])
    de_n = _normalize(entry["Name_deutsch"])
    d_t  = _levenshtein(raw_n, t_n)
    d_de = _levenshtein(raw_n, de_n)
    best_d   = min(d_t, d_de)
    best_len = len(t_n) if d_t <= d_de else len(de_n)
    return 1.0 - best_d / max(len(raw_n), best_len, 1)


def _ensemble_sim(tfidf_sim: float, lev_sim: float,
                  alpha: float = 0.65) -> float:
    """
    Gewichtetes Ensemble:
      alpha       * TF-IDF-Score  (Zeichentrigramme, gut für Komposita)
      (1-alpha)   * Levenshtein   (Editierdistanz, gut für Tippfehler)
    """
    return alpha * tfidf_sim + (1.0 - alpha) * lev_sim



_TFIDF_INDEX = _TFIDFIndex()


def _build_tfidf_index():
    """Lädt alle Arten und baut den sklearn TF-IDF-Index (einmalig)."""
    # kein "global": _TFIDF_INDEX wird nur gelesen und in-place gefuellt
    if _TFIDF_INDEX.built or not os.path.isfile(_REF_GPKG):
        return
    import sqlite3 as _sq
    con = _sq.connect(_REF_GPKG)
    entries = [
        {"entityid": r[0], "term": r[1] or "",
         "Name_deutsch": r[2] or "", "parentid": r[3] or ""}
        for r in con.execute(
            "SELECT entityid, term, Name_deutsch, parentid "
            "FROM Arten WHERE parentid != 'nan'")
    ]
    con.close()
    _TFIDF_INDEX.build(entries)

class _KNNSpatialIndex:
    """sklearn BallTree k-NN Spatial Index (UTM, euklidisch)."""
    def __init__(self):
        self._tree = None; self._pts = None; self._entries = []; self.built = False

    def build(self, records):
        valid = [r for r in records if r.get("x") and r.get("y")]
        if not valid: return
        self._pts     = np.array([[r["x"],r["y"]] for r in valid], dtype=np.float64)
        self._entries = [{"entityid":r["entityid"],"term":r["term"],
                          "Name_deutsch":r["Name_deutsch"]} for r in valid]
        self._tree = BallTree(self._pts, metric="euclidean") if _SKLEARN_AVAILABLE else None
        self.built = True

    def vote(self, x, y, k=10, max_radius=5000.0):
        if not self.built: return {}
        q = np.array([[x, y]])
        if self._tree is not None:
            dists, idx = self._tree.query(q, k=min(k, len(self._entries)))
            dists, idx = dists[0], idx[0]
        else:
            d = np.sqrt(((self._pts - q[0])**2).sum(axis=1))
            idx = np.argsort(d)[:k]; dists = d[idx]
        neighbors = [(float(dists[i]), self._entries[idx[i]])
                     for i in range(len(idx)) if float(dists[i]) <= max_radius]
        if not neighbors: return {}
        votes: dict = {}
        for dist, entry in neighbors:
            eid = entry["entityid"]
            if eid not in votes:
                votes[eid] = {"entry":entry,"count":0,"min_dist":dist}
            votes[eid]["count"] += 1
            votes[eid]["min_dist"] = min(votes[eid]["min_dist"], dist)
        best = max(votes.values(), key=lambda v: (v["count"], -v["min_dist"]))
        best["total"] = len(neighbors)
        return best


_KNN_INDEX = _KNNSpatialIndex()

# ── Kontrollierte Vokabulare (Institution, Status, Stadium) ───────────────────
_FIELD_VOCAB_CACHE: dict = {}
# Feste Abfragen je Referenztabelle - kein zusammengesetztes SQL
_VOCAB_SQL = {
    "Status":      'SELECT listitemid, term FROM "Status"',
    "Geschlecht":  'SELECT listitemid, term FROM "Geschlecht"',
    "Einheit":     'SELECT listitemid, term FROM "Einheit"',
    "Institution": 'SELECT listitemid, term FROM "Institution"',
}

def _build_field_vocab(table: str) -> dict:
    # kein "global": _FIELD_VOCAB_CACHE wird nur gelesen und mutiert
    if table in _FIELD_VOCAB_CACHE:
        return _FIELD_VOCAB_CACHE[table]
    if not os.path.isfile(_REF_GPKG):
        return {}
    import sqlite3 as _sq
    try:
        con = _sq.connect(_REF_GPKG)
        cur = con.cursor()
        abfrage = _VOCAB_SQL.get(table)
        if abfrage is None:          # nur bekannte Referenztabellen
            con.close()
            return {}
        cur.execute(abfrage)
        lookup = {}
        for listitemid, term in cur.fetchall():
            if term:
                n = _normalize(term)
                lookup[n]                    = (listitemid, term)
                lookup[term.lower().strip()] = (listitemid, term)
                # ae/oe/ue-Variante vorberechnen für alte Shapes
                ae_var = n.replace("ä","ae").replace("ö","oe").replace("ü","ue").replace("ß","ss")
                if ae_var != n:
                    lookup[ae_var] = (listitemid, term)
        con.close()
    except Exception:
        lookup = {}
    _FIELD_VOCAB_CACHE[table] = lookup
    return lookup


def _fuzzy_match_field(raw_value: str, table: str) -> tuple:
    """Fuzzy-Match eines Werts gegen ein kontrolliertes Vokabular."""
    if not raw_value:
        return (None, raw_value)
    vocab = _build_field_vocab(table)
    if not vocab:
        return (None, raw_value)
    raw_n = _normalize(raw_value)
    # 1. Exakt
    if raw_n in vocab:
        return vocab[raw_n]
    if raw_value.lower().strip() in vocab:
        return vocab[raw_value.lower().strip()]
    # 2. Substring
    for norm_key, entry in vocab.items():
        if raw_n in norm_key or norm_key in raw_n:
            return entry
    # 3. Token-Match
    import re as _re_fv
    tokens = [t for t in _re_fv.split(r'[\s\-/,\.]+', raw_n) if len(t) >= 4]
    best_score = 0
    best_entry = (None, raw_value)
    for norm_key, entry in vocab.items():
        score = sum(1 for t in tokens if t in norm_key)
        if score > best_score:
            best_score = score
            best_entry = entry
    if best_entry[0] is not None:
        return best_entry
    # 4. Levenshtein (max. Distanz abhängig von Wortlänge)
    max_dist = max(1, len(raw_n) // 6)   # kurze Wörter: max 1, lange: mehr
    best_dist = max_dist + 1
    best_lev  = (None, raw_value)
    # Nur gegen eindeutige Keys (kein ae/oe-Duplikat)
    seen_eids = set()
    for norm_key, entry in vocab.items():
        eid = entry[0]
        if eid in seen_eids:
            continue
        seen_eids.add(eid)
        d = _levenshtein(raw_n, norm_key)
        if d < best_dist:
            best_dist, best_lev = d, entry
    return best_lev


_FIELD_TO_VOCAB = {
    "status":        "Status",
    "stadium":       "Geschlecht",
    "zaehleinheit":  "Einheit",
    "institution":   "Institution",
}



def _validate_matcher(test_pairs, artname_mode="both", top_k=5):
    """
    Berechnet Matching-Guete: Precision@k, MRR, Cohen's Kappa.
    test_pairs: [(quell_artname, erwarteter_wiss_name), ...]
    """
    if not test_pairs:
        return {}
    lookup = _ARTEN_LOOKUP_CACHE if _ARTEN_LOOKUP_CACHE else build_arten_lookup(artname_mode)
    hits_at = {1: 0, 3: 0, 5: 0}
    rr_sum  = 0.0
    n_direct = n_synonym = n_tfidf = n_miss = 0
    predicted = []
    actual    = []

    for raw, expected_term in test_pairs:
        raw_str = str(raw).strip()
        raw_n   = _normalize(raw_str)
        exp_n   = _normalize(expected_term)
        candidates   = []
        stage_winner = "miss"

        direct = lookup.get(raw_str.lower()) or lookup.get(raw_n)
        if direct:
            candidates.append(direct)
            stage_winner = "direkt"
        else:
            syn_key = _SYNONYMS.get(raw_n) or _SYNONYMS.get(raw_str.lower())
            if syn_key:
                syn_e = lookup.get(syn_key.lower()) or lookup.get(_normalize(syn_key))
                if syn_e:
                    candidates.append(syn_e)
                    stage_winner = "synonym"

        if _TFIDF_INDEX.built:
            ens = _TFIDF_INDEX.ensemble_query(raw_str, top_k=top_k)
            for ens_sim, entry in ens:
                if entry not in candidates:
                    candidates.append(entry)
            if candidates and stage_winner == "miss":
                stage_winner = "tfidf"

        rank = None
        for pos, entry in enumerate(candidates[:top_k], 1):
            if (_normalize(entry.get("term","")) == exp_n or
                    _normalize(entry.get("Name_deutsch","")) == exp_n):
                rank = pos; break

        if rank is not None:
            for k in hits_at:
                if rank <= k:
                    hits_at[k] += 1
            rr_sum += 1.0 / rank
        else:
            n_miss += 1

        if stage_winner == "direkt":    n_direct  += 1
        elif stage_winner == "synonym": n_synonym += 1
        elif stage_winner == "tfidf":   n_tfidf   += 1

        top1 = _normalize(candidates[0].get("term","")) if candidates else "__none__"
        predicted.append(top1)
        actual.append(exp_n)

    n   = len(test_pairs)
    p_o = sum(1 for p, a in zip(predicted, actual) if p == a) / n
    from collections import Counter as _Ctr
    pc  = _Ctr(predicted); ac = _Ctr(actual)
    all_labels = set(predicted) | set(actual)
    p_e = sum((pc.get(lb,0)/n) * (ac.get(lb,0)/n) for lb in all_labels)
    kappa = (p_o - p_e) / (1.0 - p_e) if p_e < 1.0 else 1.0

    return {
        "n_tested":       n,
        "precision_at_1": hits_at[1] / n,
        "precision_at_3": hits_at[3] / n,
        "precision_at_5": hits_at[5] / n,
        "mrr":            rr_sum / n,
        "cohens_kappa":   kappa,
        "n_direct":       n_direct,
        "n_synonym":      n_synonym,
        "n_tfidf":        n_tfidf,
        "n_miss":         n_miss,
    }


def _extract_test_pairs(fund_layer):
    """
    Extrahiert Testpaare aus einem importierten Fund-Layer.
    Strategien (in dieser Reihenfolge):
    1. Artname_wiss + Artname_deutsch direkt vorhanden (ideal)
    2. Artname = entityid → term aus Referenzen.gpkg nachschlagen
    3. AN_LANUK (Quell-Artname) + Artname_wiss falls verfuegbar
    Gibt [(quell_name, erwarteter_term), ...] zurueck.
    """
    pairs = {}
    field_names = [f.name() for f in fund_layer.fields()]

    # Entityid → term Lookup aus Referenz aufbauen
    eid_to_term = {}
    if os.path.isfile(_REF_GPKG):
        import sqlite3 as _sq7
        con7 = _sq7.connect(_REF_GPKG)
        cur7 = con7.cursor()
        cur7.execute("SELECT entityid, term, Name_deutsch FROM Arten WHERE parentid!='nan'")
        for eid, term, name_de in cur7.fetchall():
            eid_to_term[str(eid)] = (term or "", name_de or "")
        con7.close()

    for feat in fund_layer.getFeatures():
        try:
            from qgis.core import NULL as _QN6

            def _fv(field):
                if field not in field_names: return ""
                v = feat[field]
                if v is None or v is _QN6: return ""
                s = str(v).strip()
                return s if s and s.upper() != "NULL" else ""

            art_wiss   = _fv("Artname_wiss")
            art_de     = _fv("Artname_deutsch")
            art_eid    = _fv("Artname")
            an_lanuk   = _fv("AN_LANUK")  # Quell-Artname falls vorhanden

            # Erwarteter Referenz-Term ermitteln
            ref_term = ""
            if art_wiss:
                ref_term = art_wiss
            elif art_eid and art_eid in eid_to_term:
                ref_term = eid_to_term[art_eid][0]  # wiss. Name

            if not ref_term:
                continue

            # Quell-Artname bestimmen (womit wurde importiert?)
            # AN_LANUK enthaelt oft den Original-Artnamen
            quell_name = an_lanuk if an_lanuk else art_de if art_de else ref_term

            if quell_name and ref_term:
                pairs[quell_name.lower()] = (quell_name, ref_term)
        except Exception:
            continue
    return list(pairs.values())


def _kappa_interpretation(kappa):
    if kappa >= 0.81: return "sehr gut"
    if kappa >= 0.61: return "gut"
    if kappa >= 0.41: return "moderat"
    if kappa >= 0.21: return "gering"
    if kappa >= 0.00: return "minimal"
    return "schlechter als Zufall"

