"""
workers/import_worker.py - _ScanWorker QThread
Fuehrt Lookup-Aufbau, KNN/TF-IDF-Indexierung und Artname-Aufloesung
im Hintergrund aus, damit die QGIS-GUI nicht einfriert.
"""
from qgis.PyQt.QtCore import QThread, pyqtSignal
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature,
    QgsCoordinateReferenceSystem,
)
from qgis.PyQt.QtCore import QVariant
import os

try:
    from qgis_new_project_plugin_v152.core.import_core import (
        _SYNONYMS, _ARTENGRUPPE_HABITAT, _PROTECTION_BOOST_MAP,
        _CONTEXT, _TFIDF_INDEX, _KNN_INDEX, _KNNSpatialIndex,
        _ARTEN_LOOKUP_CACHE, _ARTEN_LOOKUP_MODE,
        _REF_GPKG, _PLUGIN_DIR,
        build_arten_lookup, _build_tfidf_index,
        _normalize, _lev_sim, _ensemble_sim,
        _get_habitat_boost, _get_protection_boost,
        ensemble_rank, _FIELD_TO_VOCAB,
        _build_field_vocab, _fuzzy_match_field,
        _validate_matcher, _extract_test_pairs, _kappa_interpretation,
        _q_ident,
    )
except ImportError:
    from ..core.import_core import (
        _SYNONYMS, _ARTENGRUPPE_HABITAT, _PROTECTION_BOOST_MAP,
        _CONTEXT, _TFIDF_INDEX, _KNN_INDEX, _KNNSpatialIndex,
        _ARTEN_LOOKUP_CACHE, _ARTEN_LOOKUP_MODE,
        _REF_GPKG, _PLUGIN_DIR,
        build_arten_lookup, _build_tfidf_index,
        _normalize, _lev_sim, _ensemble_sim,
        _get_habitat_boost, _get_protection_boost,
        ensemble_rank, _FIELD_TO_VOCAB,
        _build_field_vocab, _fuzzy_match_field,
        _validate_matcher, _extract_test_pairs, _kappa_interpretation,
        _q_ident,
    )

class _ScanWorker(QThread):
    """
    Fuehrt Lookup-Aufbau, KNN/TF-IDF-Indexierung und Artname-Aufloesung
    im Hintergrund aus, damit die QGIS-GUI nicht einfriert.
    """
    log_msg   = pyqtSignal(str)
    finished  = pyqtSignal(list, list, dict)
    # finished: (not_found_list, scan_data_list, pos_cache_dict)

    def __init__(self, src_layer, artname_field, mode,
                 lu_layer, lu_field, pr_layer, pr_field,
                 ctx_key_cache=None, parent=None):
        super().__init__(parent)
        self.src_layer      = src_layer
        self.artname_field  = artname_field
        self.mode           = mode
        self.lu_layer       = lu_layer
        self.lu_field       = lu_field
        self.pr_layer       = pr_layer
        self.pr_field       = pr_field
        self.ctx_key_cache  = ctx_key_cache

    def run(self):
        try:
            self._do_scan()
        except Exception as exc:
            import traceback
            self.log_msg.emit(f"Worker-Fehler: {exc}\n{traceback.format_exc()}")
            self.finished.emit([], [], {})

    def _do_scan(self):
        # Nur die Namen, die hier wirklich zugewiesen werden; _CONTEXT,
        # _TFIDF_INDEX und _KNN_INDEX werden in-place mutiert.
        global _ARTEN_LOOKUP_CACHE, _ARTEN_LOOKUP_MODE

        # 1. Arten-Lookup (gecacht)
        if self.mode != _ARTEN_LOOKUP_MODE or not _ARTEN_LOOKUP_CACHE:
            self.log_msg.emit("  Baue Arten-Lookup ...")
            _ARTEN_LOOKUP_CACHE = build_arten_lookup(self.mode)
            _ARTEN_LOOKUP_MODE  = self.mode
        lookup = _ARTEN_LOOKUP_CACHE

        # 2. Einzel-Pass: Namen + Koordinaten sammeln
        unique_names = set()
        pos_cache: dict = {}
        for feat in self.src_layer.getFeatures():
            val = feat[self.artname_field]
            try:
                from qgis.core import NULL as _QN
                if val is None or val is _QN:
                    continue
            except Exception:
                pass
            s = str(val).strip()
            if not s or s.upper() == "NULL":
                continue
            unique_names.add(s)
            geom = feat.geometry()
            if geom and not geom.isEmpty():
                pt = geom.asPoint()
                pos_cache.setdefault(s, []).append((pt.x(), pt.y()))
        # Koordinaten nach UTM32N (EPSG:25832) normalisieren.
        # Unterstützt GK2/3/4 (EPSG:31466-31468), UTM32 WGS84 (32632),
        # WebMercator (3857), WGS84/ETRS89 geogr. (4326/4258/4314).
        # Falls kein CRS vorhanden: Auto-Detect anhand Koordinatenbereiche.
        _src_crs = self.src_layer.crs()
        _utm32   = QgsCoordinateReferenceSystem("EPSG:25832")

        # Auto-Detect CRS anhand einer Stichprobe der Koordinaten
        def _detect_crs(pos_cache):
            """Erkennt CRS anhand der Koordinatenbereiche."""
            sample = [pt for pts in list(pos_cache.values())[:20]
                      for pt in pts[:3]]
            if not sample: return None
            xs = [p[0] for p in sample]
            ys = [p[1] for p in sample]
            mx, my = sum(xs)/len(xs), sum(ys)/len(ys)
            # WGS84 / ETRS89 geographisch
            if 5.5 < mx < 10.0 and 50.0 < my < 53.0:
                return QgsCoordinateReferenceSystem("EPSG:4326")
            # GK Streifen 2 (Rechtswert ~2.5M)
            if 2_400_000 < mx < 2_800_000 and 5_400_000 < my < 5_900_000:
                return QgsCoordinateReferenceSystem("EPSG:31466")
            # GK Streifen 3 (Rechtswert ~3.5M)
            if 3_300_000 < mx < 3_700_000 and 5_400_000 < my < 5_900_000:
                return QgsCoordinateReferenceSystem("EPSG:31467")
            # UTM32 WGS84 (wie ETRS89, minimal verschieden)
            if 200_000 < mx < 700_000 and 5_400_000 < my < 5_900_000:
                return QgsCoordinateReferenceSystem("EPSG:32632")
            # WebMercator
            if 600_000 < mx < 1_100_000 and 6_400_000 < my < 6_900_000:
                return QgsCoordinateReferenceSystem("EPSG:3857")
            return None  # Unbekannt – kein Transform

        _use_crs = _src_crs if _src_crs.isValid() else _detect_crs(pos_cache)
        if _use_crs and not _src_crs.isValid():
            self.log_msg.emit(
                f"  Auto-CRS: {_use_crs.authid()} (kein CRS im Layer)")
        _needs_transform = (
            _use_crs is not None
            and _use_crs.authid() not in ("EPSG:25832", "")
        )
        if _needs_transform:
            from qgis.core import (QgsCoordinateTransform,
                                   QgsCoordinateTransformContext, QgsPointXY)
            _tr   = QgsCoordinateTransform(
                _use_crs, _utm32, QgsCoordinateTransformContext())
            _pos2 = {}
            _err  = 0
            for _nm, _pts in pos_cache.items():
                _pos2[_nm] = []
                for _x, _y in _pts:
                    try:
                        _p = _tr.transform(QgsPointXY(_x, _y))
                        # Plausibilitäts-Check: NRW liegt in UTM32
                        # E: 280.000–560.000, N: 5.550.000–5.820.000
                        if (200_000 < _p.x() < 700_000
                                and 5_400_000 < _p.y() < 5_900_000):
                            _pos2[_nm].append((_p.x(), _p.y()))
                        else:
                            _err += 1  # Außerhalb NRW → verwerfen
                    except Exception:
                        _err += 1
            if _err:
                self.log_msg.emit(
                    f"  ⚠ {_err} Koordinaten außerhalb NRW verworfen "
                    f"(CRS: {_use_crs.authid() if _use_crs else "unbekannt"})")
            pos_cache = _pos2
        elif _use_crs is None:
            self.log_msg.emit(
                "  ⚠ CRS nicht erkannt – k-NN ohne Koordinaten-Transform")

        # 3. KNN-Index (gecacht)
        src_id = id(self.src_layer)
        if not (_KNN_INDEX.built
                and getattr(_KNN_INDEX, '_src_id', None) == src_id):
            # In-place reset (NICHT neu zuweisen – Dialog teilt dieselbe Instanz!)
            _KNN_INDEX._tree = None
            _KNN_INDEX._pts  = None
            _KNN_INDEX._entries = []
            _KNN_INDEX.built = False
            _KNN_INDEX._src_id = src_id
            records = []
            for name, positions in pos_cache.items():
                entry = lookup.get(name.lower()) or lookup.get(_normalize(name))
                if not entry:
                    syn = (_SYNONYMS.get(_normalize(name))
                           or _SYNONYMS.get(name.lower()))
                    if syn:
                        entry = (lookup.get(syn.lower())
                                 or lookup.get(_normalize(syn)))
                if not entry:
                    continue
                for x, y in positions:
                    records.append({"x": x, "y": y,
                                    "entityid": entry["entityid"],
                                    "term":     entry["term"],
                                    "Name_deutsch": entry["Name_deutsch"]})
            _KNN_INDEX.build(records)
            if _KNN_INDEX.built:
                self.log_msg.emit(
                    f"  k-NN-Index: {len(records)} aufgeloeste Records")

        # 4. Kontext-Layer (gecacht)
        _CONTEXT.landuse_layer = self.lu_layer
        _CONTEXT.landuse_field = self.lu_field
        _CONTEXT.protect_layer = self.pr_layer
        _CONTEXT.protect_field = self.pr_field
        ctx_key = (id(self.lu_layer), id(self.pr_layer),
                   self.lu_field, self.pr_field)
        if ((self.lu_layer or self.pr_layer) and
                (not _CONTEXT.built or self.ctx_key_cache != ctx_key)):
            self.log_msg.emit("  Indiziere Kontext-Layer ...")
            _CONTEXT.build()
            self.log_msg.emit("  Kontext-Layer indiziert.")

        # 5. TF-IDF (gecacht)
        if not _TFIDF_INDEX.built:
            self.log_msg.emit("  Baue TF-IDF-Index ...")
            _build_tfidf_index()
            self.log_msg.emit(
                f"  TF-IDF: {len(_TFIDF_INDEX._entries)} Arten, "
                f"{len(_TFIDF_INDEX._idf)} Trigramme")

        # 6. Nicht-erkannte bestimmen + Scan-Daten aufbauen
        not_found = sorted(n for n in unique_names
                           if n.lower() not in lookup
                           and _normalize(n) not in lookup)

        # Batch-TF-IDF+Lev für alle Artnamen auf einmal (70x schneller)
        _all_names = sorted(unique_names)
        _batch_ens: dict = {}
        if _TFIDF_INDEX.built and _all_names:
            _batch_tf = _TFIDF_INDEX.batch_query(_all_names, top_k=30)
            for _nm, _cands in zip(_all_names, _batch_tf):
                _nm_n   = _normalize(_nm)
                _scored = [(_ensemble_sim(s, _lev_sim(_nm_n, e)), e)
                           for s, e in _cands]
                _scored.sort(key=lambda x: x[0], reverse=True)
                _batch_ens[_nm] = _scored[:5]

        scan_data = []
        for name in _all_names:
            raw_n    = _normalize(name)
            is_found = name.lower() in lookup or raw_n in lookup
            syn_term = (_SYNONYMS.get(raw_n)
                        or _SYNONYMS.get(name.lower().strip()))
            if is_found:
                direct = lookup.get(raw_n) or lookup.get(name.lower())
                stage  = "Synonym" if syn_term else "Direkt"
                s_t    = direct["term"] if direct else ""
                s_d    = direct["Name_deutsch"] if direct else ""
                s_e    = direct["entityid"] if direct else ""
            else:
                sug_o = self._suggest(name, lookup)
                stage = ("Synonym" if syn_term
                         else ("TF-IDF" if sug_o else "Kein Treffer"))
                s_t   = sug_o["term"] if sug_o else ""
                s_d   = sug_o["Name_deutsch"] if sug_o else ""
                s_e   = sug_o["entityid"] if sug_o else ""
            tfs = ""
            if _TFIDF_INDEX.built:
                r = _TFIDF_INDEX.ensemble_query(name, top_k=1)
                if r:
                    tfs = f"{r[0][0]:.3f} (ens)"
            knn_txt = self._knn_text(name, pos_cache)
            scan_data.append({
                "Quell_Artname": name,
                "Erkannt":       "Ja" if is_found else "Nein",
                "KNN":           knn_txt,
                "Landnutzung": "", "Schutzgebiet": "",
                "Ensemble_Score": "",
                "Stufe":         stage,
                "Synonym_Key":   syn_term or "",
                "Vorschlag_wiss": s_t,
                "Vorschlag_de":   s_d,
                "Vorschlag_eid":  str(s_e),
                "TFIDF_Score":    tfs,
            })

        self.finished.emit(not_found, scan_data, pos_cache)

    def _suggest(self, raw, lookup):
        raw_n   = _normalize(raw)
        has_unb = "unbestimmt" in raw_n
        syn_key = (_SYNONYMS.get(raw_n)
                   or _SYNONYMS.get(raw.lower().strip()))
        if syn_key:
            e = lookup.get(syn_key.lower()) or lookup.get(_normalize(syn_key))
            if e:
                return e
            import sqlite3 as _sq
            if os.path.isfile(_REF_GPKG):
                con = _sq.connect(_REF_GPKG)
                row = con.execute(
                    "SELECT entityid,term,Name_deutsch,parentid FROM Arten "
                    "WHERE parentid!='nan' AND "
                    "(lower(term) LIKE lower(?) "
                    "OR lower(Name_deutsch) LIKE lower(?)) "
                    "ORDER BY length(term) LIMIT 1",
                    (f"%{syn_key}%", f"%{syn_key}%")).fetchone()
                con.close()
                if row:
                    return {"entityid": row[0], "term": row[1] or "",
                            "Name_deutsch": row[2] or "",
                            "parentid": row[3] or ""}
        e = lookup.get(raw_n) or lookup.get(raw.lower())
        if e:
            return e
        if not _TFIDF_INDEX.built:
            return None
        # Ensemble: TF-IDF (0.65) + Levenshtein (0.35)
        results = _TFIDF_INDEX.ensemble_query(raw, top_k=10)
        if not results:
            return None
        if has_unb:
            for ens_sim, entry in results:
                if "unbestimmt" in entry["Name_deutsch"].lower():
                    return entry
        return results[0][1]

    def _knn_text(self, raw_name, pos_cache):
        if not _KNN_INDEX.built:
            return "\u2014"
        from collections import Counter
        ev = Counter(); ee = {}; total = 0
        for x, y in pos_cache.get(raw_name, []):
            v = _KNN_INDEX.vote(x, y, k=10, max_radius=50000.0)  # 50 km
            if v:
                eid = v["entry"]["entityid"]
                ev[eid] += v["count"]; ee[eid] = v["entry"]
                total   += v.get("total", 0)
        if not ev:
            return "\u2014"
        best = ev.most_common(1)[0][0]
        e    = ee[best]
        pct  = min(int(ev[best] / max(total, 1) * 100), 100)
        return (e["Name_deutsch"] or e["term"]) + f" ({pct}%)"


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
                lookup[_normalize(term)]     = (listitemid, term)
                lookup[term.lower().strip()] = (listitemid, term)
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
    return best_entry


_FIELD_TO_VOCAB = {
    "status":      "Status",
    "stadium":     "Geschlecht",
    "institution": "Institution",
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
