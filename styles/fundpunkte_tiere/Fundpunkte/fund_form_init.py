# -*- coding: utf-8 -*-
"""
Formular-Initialisierung des Layers 'Fund' (QGIS-Desktop).

Quelle: styles/fundpunkte_tiere/Fundpunkte/fund_form_init.py. Eingebettet
in Fund.qml, fund.qml und layer_styles der Fundpunkte.gpkg mit
tools/form_init_einbetten.py - dort nicht von Hand aendern.

Enthaelt zwei Funktionen:
1. Feldwerte festsetzen (Anpinnen), siehe Abschnitt weiter unten.
2. Synonym-Suche fuer das Feld 'Artname':

Sucht ueber akzeptierte Namen (Arten: term / Name_deutsch / anzeigename) UND
ueber Synonyme (Arten_Synonyme.synonym_term), gefiltert nach der gewaehlten
Artengruppe. Angeboten werden nur akzeptierte Arten; gespeichert wird deren
entityid. Synonyme erscheinen nie als eigener Eintrag (verdecktes Register).

Der Zugriff erfolgt ueber die QGIS-Layer-/Ausdrucks-API (QgsFeatureRequest),
NICHT ueber sqlite3. Damit funktioniert die Suche sowohl im Offline-Betrieb
(GeoPackage) als auch gegen eine zentrale PostGIS-Datenbank. Voraussetzung:
die Layer 'Arten' und 'Arten_Synonyme' sind im Projekt geladen.

Diagnose: Log-Meldungen, Reiter 'FT-Synonymsuche'.

QField ignoriert diese Funktion; die dortige Umsetzung ist Gegenstand der
Ausschreibung (Leistungsbeschreibung, Abschnitt 5.4).
"""
from qgis.PyQt.QtWidgets import (QLineEdit, QCompleter, QLabel, QWidget,
                                 QHBoxLayout, QVBoxLayout, QTabWidget,
                                 QStackedWidget, QGridLayout, QFormLayout,
                                 QBoxLayout)
from qgis.PyQt.QtCore import Qt, QStringListModel, QObject, QEvent
from qgis.core import QgsProject, QgsFeatureRequest, QgsMessageLog

_TAG = "FT-Synonymsuche"

REF_LAYER = "Arten"
SYN_LAYER = "Arten_Synonyme"
# Referenzliste: Schluessel, Anzeige, Kaskadenfeld, durchsuchte Spalten
REF_KEY, REF_DISPLAY, REF_PARENT = "entityid", "anzeigename", "parentid"
REF_SEARCH = ["term", "Name_deutsch", "anzeigename"]
# Synonymtabelle
SYN_TERM, SYN_KEY, SYN_PARENT = "synonym_term", "akzeptiert_entityid", "parentid"
LIMIT = 50


def _log(m):
    try:
        QgsMessageLog.logMessage(str(m), _TAG)
    except Exception:
        pass


def _layer(name):
    ls = QgsProject.instance().mapLayersByName(name)
    return ls[0] if ls else None


def _fname(layer, wanted):
    """Tatsaechlichen Feldnamen case-tolerant ermitteln (PostGIS/ogr2ogr)."""
    if layer is None:
        return None
    for f in layer.fields():
        if f.name().lower() == wanted.lower():
            return f.name()
    return None


def _is_numeric(layer, fname):
    try:
        idx = layer.fields().indexFromName(fname)
        return layer.fields().at(idx).isNumeric()
    except Exception:
        return False


def _lit(v):
    return "'" + str(v).replace("'", "''") + "'"


def _eq(layer, fname, value):
    if _is_numeric(layer, fname):
        try:
            return '"%s" = %s' % (fname, int(value))
        except Exception:
            pass
    return '"%s" = %s' % (fname, _lit(value))


def _like(fname, needle):
    esc = str(needle).replace("\\", "\\\\").replace("%", "\\%")
    esc = esc.replace("_", "\\_").replace("'", "''")
    return '"%s" ILIKE %s' % (fname, "'%" + esc + "%'")


def _req(expr, limit=LIMIT):
    r = QgsFeatureRequest().setFilterExpression(expr)
    try:
        r.setFlags(QgsFeatureRequest.NoGeometry)
    except Exception:
        pass
    if limit:
        r.setLimit(limit)
    return r


def _is_empty(v):
    if v is None:
        return True
    try:
        if hasattr(v, "isNull") and v.isNull():
            return True
    except Exception:
        pass
    return str(v).strip() in ("", "NULL")


def search(typed, parent_value):
    """-> Liste [(entityid, anzeigename)] akzeptierter Arten."""
    ref, syn = _layer(REF_LAYER), _layer(SYN_LAYER)
    if ref is None:
        return []
    k = _fname(ref, REF_KEY)
    d = _fname(ref, REF_DISPLAY)
    p = _fname(ref, REF_PARENT)
    if not (k and d):
        _log("Arten: Schluessel-/Anzeigefeld nicht gefunden")
        return []
    fields = [x for x in (_fname(ref, s) for s in REF_SEARCH) if x]
    has_parent = bool(p) and not _is_empty(parent_value)

    out = {}
    # 1) direkte Treffer in der Artenliste
    cl = ["(" + " OR ".join(_like(f, typed) for f in fields) + ")"]
    if has_parent:
        cl.append(_eq(ref, p, parent_value))
    try:
        for f in ref.getFeatures(_req(" AND ".join(cl))):
            out[f[k]] = f[d]
    except Exception as e:
        _log("Arten-Abfrage: %s" % e)

    # 2) Treffer ueber Synonyme -> akzeptierte entityid -> akzeptierter Name
    if syn is not None and len(out) < LIMIT:
        st = _fname(syn, SYN_TERM)
        sk = _fname(syn, SYN_KEY)
        sp = _fname(syn, SYN_PARENT)
        if st and sk:
            scl = [_like(st, typed)]
            if sp and not _is_empty(parent_value):
                scl.append(_eq(syn, sp, parent_value))
            keys = set()
            try:
                for f in syn.getFeatures(_req(" AND ".join(scl))):
                    v = f[sk]
                    if v is not None and v not in out:
                        keys.add(v)
            except Exception as e:
                _log("Synonym-Abfrage: %s" % e)
            if keys:
                num = _is_numeric(ref, k)
                vals = ", ".join((str(int(x)) if num else _lit(x)) for x in keys)
                try:
                    for f in ref.getFeatures(_req('"%s" IN (%s)' % (k, vals))):
                        out.setdefault(f[k], f[d])
                except Exception as e:
                    _log("Aufloesung: %s" % e)

    res = [(a, b) for a, b in out.items() if b not in (None, "")]
    res.sort(key=lambda t: str(t[1]).lower())
    return res[:LIMIT]


def _get_form(dialog):
    try:
        from qgis.gui import QgsAttributeForm
    except Exception:
        return None
    if isinstance(dialog, QgsAttributeForm):
        return dialog
    return dialog.findChild(QgsAttributeForm)


def _artname_page(form):
    art = None
    for w in form.findChildren(QWidget):
        if w.objectName() == "Artname":
            art = w
            break
    if art is None:
        return None
    child, p = art, art.parentWidget()
    while p is not None:
        if isinstance(p, QStackedWidget):
            return child
        child, p = p, p.parentWidget()
    return None


def _insert_top(lay, w):
    if isinstance(lay, QBoxLayout):
        lay.insertWidget(0, w)
        return True
    if isinstance(lay, QFormLayout):
        try:
            lay.insertRow(0, w)
        except Exception:
            lay.addRow(w)
        return True
    if isinstance(lay, QGridLayout):
        lay.addWidget(w, lay.rowCount(), 0, 1, max(1, lay.columnCount()))
        return True
    return False


class _EnterEater(QObject):
    def __init__(self, le, apply_cb):
        super().__init__(le)
        self._le = le
        self._apply = apply_cb

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.KeyPress and ev.key() in (Qt.Key_Return, Qt.Key_Enter):
            cp = self._le.completer()
            txt = cp.currentCompletion() if cp else ""
            if cp and cp.popup() and cp.popup().isVisible():
                cp.popup().hide()
            self._apply(txt)
            return True
        return False


# ============================================================================
# Feldwerte festsetzen (Anpinnen), wie "Wert merken" in QField
# ============================================================================
#
# Neben jedem editierbaren Feld steht beim Erfassen eine Stecknadel. Ist sie
# gedrueckt, wird der Wert dieses Feldes in jeden neuen Fundpunkt uebernommen,
# bis sie wieder geloest wird. Massgeblich ist der zuletzt gespeicherte Wert.
#
# - Festsetzungen gelten fuer die laufende QGIS-Sitzung und je Layer.
# - Kaskade: Ein Feld, dessen Auswahlliste ueber current_value('X') gefiltert
#   ist (z. B. Artname ueber Artengruppe), wird nur uebernommen, wenn X im neuen
#   Fundpunkt denselben Wert hat wie beim Festsetzen.
# - Uebernommene Werte durchlaufen die normale Pruefung (Pflichtfelder,
#   Bedingungen); sie umgehen keine Validierung.
# - QGIS 4.x bringt diese Funktion selbst mit (reuseLastValuePolicy). Ist sie
#   fuer den Layer eingeschaltet, tritt dieser Teil zurueck.
# - QField ignoriert den Init-Code; dort gibt es "Wert merken" von Haus aus.

import re as _re
import sys as _sys
import types as _types

_PIN_TAG = "FT-Anpinnen"
_PIN_MODUL = "_ft_feldwerte_angepinnt"

# Systemfelder und abgeleitete Felder werden nie festgesetzt
PIN_AUSGESCHLOSSEN = {
    "fid", "kennung", "utm_east", "utm_north", "aenderungsdatum",
    "eingabedatum", "projekt_id", "artname_deutsch", "artname_wiss",
}

_CURRENT_VALUE = _re.compile(r"current_value\s*\(\s*'([^']+)'\s*\)", _re.I)

_PIN_STIL = (
    "QToolButton{border:1px solid transparent;border-radius:4px;"
    "padding:1px;font-size:14px;}"
    "QToolButton:checked{background:#ffe082;border:1px solid #c79a00;}"
)


def _plog(m):
    try:
        QgsMessageLog.logMessage(str(m), _PIN_TAG)
    except Exception:
        pass


def _qt_enum(cls, scope, name):
    """Qt-Aufzaehlungswert fuer PyQt5 (cls.name) und PyQt6 (cls.scope.name)."""
    v = getattr(cls, name, None)
    if v is None:
        v = getattr(getattr(cls, scope), name)
    return v


def _pin_speicher(layer):
    """-> {feldname: {"wert": ..., "kontext": {steuerfeld: wert}}} des Layers.

    QGIS fuehrt den Init-Code bei jedem Oeffnen eines Formulars neu aus;
    Modulvariablen wuerden dabei zurueckgesetzt. Der Speicher liegt deshalb
    in einem eigenen Eintrag in sys.modules und lebt so lange wie QGIS."""
    mod = _sys.modules.get(_PIN_MODUL)
    if mod is None:
        mod = _types.ModuleType(_PIN_MODUL)
        mod.layer = {}
        _sys.modules[_PIN_MODUL] = mod
    return mod.layer.setdefault(layer.id(), {})


def _norm(v):
    return None if _is_empty(v) else str(v)


def _steuerfelder(layer):
    """-> {feld: [steuerfelder]} aus den Filterausdruecken der Auswahllisten."""
    abh = {}
    for i, f in enumerate(layer.fields()):
        try:
            cfg = layer.editorWidgetSetup(i).config() or {}
        except Exception:
            continue
        quellen = _CURRENT_VALUE.findall(str(cfg.get("FilterExpression") or ""))
        quellen = [q for q in quellen if q != f.name()]
        if quellen:
            abh[f.name()] = quellen
    return abh


def _pinbar(layer, name):
    if name.lower() in PIN_AUSGESCHLOSSEN:
        return False
    idx = layer.fields().indexFromName(name)
    if idx < 0:
        return False
    try:
        if layer.editFormConfig().readOnly(idx):
            return False
    except Exception:
        pass
    return True


def _nativ_aktiv(layer, namen):
    """True, wenn QGIS (ab 4.0) die Stecknadel fuer diese Felder selbst zeigt."""
    try:
        from qgis.core import Qgis
        nicht_erlaubt = Qgis.AttributeFormReuseLastValuePolicy.NotAllowed
    except Exception:
        return False
    cfg = layer.editFormConfig()
    for n in namen:
        try:
            idx = layer.fields().indexFromName(n)
            if cfg.reuseLastValuePolicy(idx) != nicht_erlaubt:
                return True
        except Exception:
            return False
    return False


def _edit_seite(w, grenze):
    """Seite des Formularfelds, auf der das Eingabe-Widget liegt."""
    child, p = w, w.parentWidget()
    while p is not None and p is not grenze:
        if isinstance(p, QStackedWidget):
            return child
        child, p = p, p.parentWidget()
    return None


def _feld_widgets(form, layer):
    """-> [(feldname, seite)] fuer alle festsetzbaren Felder im Formular."""
    try:
        from qgis.gui import QgsAttributeFormEditorWidget
    except Exception:
        return []
    out, gesehen = [], set()
    for afw in form.findChildren(QgsAttributeFormEditorWidget):
        try:
            ww = afw.editorWidget()
            name = ww.field().name()
            w = ww.widget()
        except Exception:
            continue
        if name in gesehen or w is None or not _pinbar(layer, name):
            continue
        seite = _edit_seite(w, afw)
        if seite is None or not isinstance(seite.layout(), QBoxLayout):
            continue
        gesehen.add(name)
        out.append((name, seite))
    if not out:
        # Rueckfall: Eingabe-Widgets tragen den Feldnamen als objectName
        # (so findet auch die Synonymsuche das Feld 'Artname')
        namen = {f.name() for f in layer.fields() if _pinbar(layer, f.name())}
        for w in form.findChildren(QWidget):
            name = w.objectName()
            if name not in namen or name in gesehen:
                continue
            seite = _edit_seite(w, form)
            if seite is None or not isinstance(seite.layout(), QBoxLayout):
                continue
            gesehen.add(name)
            out.append((name, seite))
    return out


def _im_erfassungsmodus(form):
    try:
        from qgis.gui import QgsAttributeEditorContext
        add = getattr(QgsAttributeEditorContext, "AddFeatureMode", None)
        if add is None:
            add = QgsAttributeEditorContext.Mode.AddFeatureMode
        return form.mode() == add
    except Exception:
        return False


def _formwert(form, name):
    try:
        return form.currentFormFeature()[name]
    except Exception:
        return None


def _pins_einrichten(form, layer):
    from qgis.PyQt.QtWidgets import (QToolButton, QGraphicsOpacityEffect,
                                     QDialogButtonBox, QPushButton)
    from qgis.PyQt.QtCore import QTimer

    felder = _feld_widgets(form, layer)
    if not felder:
        _plog("Keine festsetzbaren Felder gefunden.")
        return
    if _nativ_aktiv(layer, [n for n, _ in felder]):
        _plog(u"QGIS bietet \u201eWert merken\u201c selbst an \u2013 eigene Stecknadeln aus.")
        return

    speicher = _pin_speicher(layer)
    steuer = _steuerfelder(layer)
    alle_quellen = {q for qs in steuer.values() for q in qs}
    reihenfolge = {f.name(): i for i, f in enumerate(layer.fields())}
    knoepfe = {}
    zustand = {"loesen": None}

    def eintrag(name, wert_von):
        return {"wert": wert_von(name),
                "kontext": {q: _norm(wert_von(q))
                            for q in steuer.get(name, [])}}

    def darstellen(name):
        b = knoepfe[name]
        an = name in speicher
        b.blockSignals(True)
        b.setChecked(an)
        b.blockSignals(False)
        b.graphicsEffect().setOpacity(1.0 if an else 0.35)
        if an:
            b.setToolTip(u"Festgesetzt: Wert wird in jeden neuen Fundpunkt "
                         u"\u00fcbernommen.\nKlicken zum L\u00f6sen.")
        else:
            b.setToolTip(u"Wert festsetzen: in jeden neuen Fundpunkt "
                         u"\u00fcbernehmen, bis die Nadel gel\u00f6st wird.")

    def loesen_text():
        loesen = zustand["loesen"]
        if loesen is None:
            return
        n = len(speicher)
        loesen.setText(u"Festsetzungen l\u00f6sen (%d)" % n if n
                       else u"Festsetzungen l\u00f6sen")
        loesen.setEnabled(bool(n))

    def umschalten(name, an):
        if an:
            speicher[name] = eintrag(name, lambda n: _formwert(form, n))
            _plog("%s festgesetzt: %r" % (name, speicher[name]["wert"]))
        else:
            speicher.pop(name, None)
            _plog(u"%s gel\u00f6st" % name)
        darstellen(name)
        loesen_text()

    for name, seite in felder:
        b = QToolButton()
        b.setObjectName("ft_pin_" + name)
        b.setText(u"\U0001F4CC")
        b.setCheckable(True)
        b.setAutoRaise(True)
        b.setMinimumSize(30, 28)
        b.setStyleSheet(_PIN_STIL)
        b.setGraphicsEffect(QGraphicsOpacityEffect(b))
        b.toggled.connect(lambda an, n=name: umschalten(n, an))
        seite.layout().addWidget(b)
        knoepfe[name] = b
        darstellen(name)

    bb = form.findChild(QDialogButtonBox)
    if bb is not None:
        loesen = QPushButton()
        loesen.setObjectName("ft_pins_loesen")
        loesen.setToolTip(u"Alle Stecknadeln dieses Layers l\u00f6sen")
        bb.addButton(loesen, _qt_enum(QDialogButtonBox, "ButtonRole",
                                      "ResetRole"))
        zustand["loesen"] = loesen

        def alle_loesen():
            speicher.clear()
            for n in knoepfe:
                darstellen(n)
            loesen_text()
            _plog(u"Alle Festsetzungen gel\u00f6st")

        loesen.clicked.connect(alle_loesen)
        loesen_text()

    def anwenden():
        """Festgesetzte Werte in den neuen Fundpunkt schreiben."""
        try:
            if (not _im_erfassungsmodus(form)
                    or form.property("ft_pins_angewendet")):
                return
        except RuntimeError:          # Formular schon geschlossen
            return
        form.setProperty("ft_pins_angewendet", True)
        # Steuerfelder (z. B. Artengruppe) zuerst, dann die abhaengigen
        namen = sorted(speicher,
                       key=lambda n: (0 if n in alle_quellen else 1,
                                      reihenfolge.get(n, 999)))
        gesetzt, uebersprungen = [], []
        for n in namen:
            e = speicher[n]
            if any(_norm(_formwert(form, q)) != e["kontext"].get(q)
                   for q in steuer.get(n, [])):
                uebersprungen.append(n)
                continue
            try:
                form.changeAttribute(n, e["wert"])
                gesetzt.append(n)
            except Exception as ex:
                _plog(u"\u00dcbernahme %s: %s" % (n, ex))
        if namen:
            _plog(u"\u00fcbernommen: %s; \u00fcbersprungen (Kaskade): %s"
                  % (gesetzt, uebersprungen))

    def sichtbarkeit(*_):
        an = _im_erfassungsmodus(form)
        for b in knoepfe.values():
            b.setVisible(an)
        if zustand["loesen"] is not None:
            zustand["loesen"].setVisible(an)
        if an:
            # erst nach setFeature()/setMode() ausfuehren, sonst ueberschrieben
            QTimer.singleShot(0, anwenden)

    def gespeichert(feat):
        if not _im_erfassungsmodus(form):
            return
        for n in list(speicher):
            try:
                speicher[n] = eintrag(n, lambda x: feat[x])
            except Exception as ex:
                _plog("Merken %s: %s" % (n, ex))

    try:
        form.modeChanged.connect(sichtbarkeit)
    except Exception as ex:
        _plog("modeChanged: %s" % ex)
    try:
        form.featureSaved.connect(gespeichert)
    except Exception as ex:
        _plog("featureSaved: %s" % ex)
    sichtbarkeit()
    _plog("Stecknadeln an %d Feldern, %d festgesetzt."
          % (len(knoepfe), len(speicher)))


def init(dialog, layer, feature):
    _log("init() aufgerufen")
    try:
        _form = _get_form(dialog)
        if _form is not None and layer is not None:
            _pins_einrichten(_form, layer)
    except Exception as e:
        _plog("Init-Fehler: %s" % e)
    try:
        form = _get_form(dialog)
        ref, syn = _layer(REF_LAYER), _layer(SYN_LAYER)
        _log("form=%s  Arten=%s  Arten_Synonyme=%s"
             % (type(form).__name__ if form else None,
                bool(ref), bool(syn)))
        if form is None or ref is None:
            _log("Ohne Layer 'Arten' bzw. Formular keine Synonymsuche.")
            return
        if syn is None:
            _log("Layer 'Arten_Synonyme' fehlt - Suche laeuft ohne Synonyme.")

        search_le = QLineEdit()
        search_le.setObjectName("Artname_synonymsuche")
        search_le.setPlaceholderText(
            u"Art oder Synonym suchen (z. B. Uhu, Strix bubo) ...")
        search_le.setClearButtonEnabled(True)

        model = QStringListModel(search_le)
        comp = QCompleter(model, search_le)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        comp.setCompletionMode(QCompleter.PopupCompletion)
        search_le.setCompleter(comp)

        status = QLabel()
        status.setWordWrap(True)
        status.setVisible(False)
        _f = status.font()
        _f.setPointSizeF(max(7.0, _f.pointSizeF() - 1))
        status.setFont(_f)

        name2key = {}

        def set_status(msg, warn=False):
            status.setText(msg)
            status.setStyleSheet("color:#b00020;" if warn else "color:#8a6d00;")
            status.setVisible(bool(msg))

        def cur_ag():
            try:
                return form.currentFormFeature()["Artengruppe"]
            except Exception:
                try:
                    return feature["Artengruppe"]
                except Exception:
                    return None

        def refresh(text):
            name2key.clear()
            ag = cur_ag()
            t = text.strip()
            if _is_empty(ag):
                model.setStringList([])
                set_status(u"Bitte zuerst eine Artengruppe w\u00e4hlen.")
                return
            if len(t) < 2:
                model.setStringList([])
                set_status("")
                return
            names = []
            for key, disp in search(t, ag):
                if disp not in name2key:
                    name2key[disp] = key
                    names.append(disp)
            model.setStringList(names)
            if names:
                set_status("")
            else:
                set_status(u"\u201e%s\u201c ist als Name oder Synonym nicht "
                           u"bekannt (in dieser Artengruppe)." % t, warn=True)

        def choose(disp):
            key = name2key.get(disp)
            if key is None:
                return
            for val in (key, str(key)):
                try:
                    form.changeAttribute("Artname", val)
                    break
                except Exception as e:
                    _log("changeAttribute: %s" % e)
            search_le.clear()
            set_status("")

        def apply_choice(txt):
            if not txt:
                sl = model.stringList()
                txt = sl[0] if sl else ""
            if txt:
                choose(txt)

        search_le.textEdited.connect(refresh)
        comp.activated[str].connect(choose)
        search_le.installEventFilter(_EnterEater(search_le, apply_choice))

        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(1)
        roww = QWidget()
        h = QHBoxLayout(roww)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(QLabel(u"Art-/Synonymsuche:"))
        h.addWidget(search_le, 1)
        v.addWidget(roww)
        v.addWidget(status)

        page = _artname_page(form)
        placed = False
        if page is not None and page.layout() is not None:
            placed = _insert_top(page.layout(), wrap)
        if not placed:
            tw = form.findChild(QTabWidget)
            if tw and tw.count() > 0 and tw.widget(0).layout() is not None:
                placed = _insert_top(tw.widget(0).layout(), wrap)
        if not placed and form.layout() is not None:
            placed = _insert_top(form.layout(), wrap)
        _log("Synonymsuche aktiv (platziert=%s, Synonyme=%s)."
             % (placed, bool(syn)))
    except Exception as e:
        _log("Init-Fehler: %s" % e)
