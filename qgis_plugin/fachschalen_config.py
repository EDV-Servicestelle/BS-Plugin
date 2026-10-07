import shutil as _shutil, os as _os
try:
    _d = _os.path.dirname(__file__)
    for _r, _ds, _ in _os.walk(_d):
        for _cd in _ds:
            if _cd == "__pycache__": _shutil.rmtree(_os.path.join(_r, _cd), ignore_errors=True)
except Exception: pass

"""
Fachschalen-Konfiguration – direkt aus den Musterprojekten abgeleitet.

Fundpunkte Tiere : FT/FT_Muster.qgz  +  FT/Fundpunkte.gpkg  +  FT/Referenzen.gpkg
Biotopbaum       : Biotopbaum/Erfassung.qgs  +  Biotopbaum/Fundpunkte.gpkg
                   +  Biotopbaum/Referenzlisten.gpkg
"""

# ── WMS/WMTS-Hintergrundkarten (NRW-Geodatendienste) ─────────────────────────
# Quelle: aus beiden QGS/QGZ-Projekten extrahiert

NRW_WMS_LAYERS = [
    {
        "name":          "DTK Farbe",
        "type":          "wmts",
        "url":           "https://www.wmts.nrw.de/geobasis/wmts_nw_dtk",
        "layer":         "nw_dtk_col",
        "format":        "image/png",
        "crs":           "EPSG:25832",
        "style":         "default",
        "tilematrixset": "EPSG_25832_16",
    },
    {
        "name":          "DOP",
        "type":          "wmts",
        "url":           "https://www.wmts.nrw.de/geobasis/wmts_nw_dop",
        "layer":         "nw_dop",
        "format":        "image/png",
        "crs":           "EPSG:25832",
        "style":         "default",
        "tilematrixset": "EPSG_25832_16",
    },
    {
        "name":   "DGK5 Grundriss",
        "type":   "wms",
        "url":    "https://www.wms.nrw.de/geobasis/wms_nw_dgk5",
        "layer":  "nw_dgk5_grundriss",
        "format": "image/png",
        "crs":    "EPSG:25832",
    },
    {
        "name":   "Höhenlinien",
        "type":   "wms",
        "url":    "https://www.wms.nrw.de/geobasis/wms_nw_hl_hp_schwarz",
        "layer":  "nw_hl_hp_hoehenlinien",
        "format": "image/png",
        "crs":    "EPSG:25832",
    },
]

# ── Fachschalen-Definitionen ──────────────────────────────────────────────────

# Gemeinsames Schema für Institution, Karterer, Untersuchungsgebiet
GEMEINSAM_SCHEMA = "gemeinsam"

GEMEINSAM_TABLES = {
    "institution":         "institution",
    "karterer":            "karterer",
    "untersuchungsgebiet": "untersuchungsgebiet",
}

# ── NRW Kreise / kreisfreie Städte ───────────────────────────────────────────
# Schlüssel: Anzeigename | Wert: (AGS 8-stellig, URL-Name für opengeodata.nrw.de)
NRW_KREISE = {
    "Aachen (Städteregion)":    ("05334002", "aachen"),
    "Bielefeld":                ("05711000", "bielefeld"),
    "Bochum":                   ("05911000", "bochum"),
    "Bonn":                     ("05314000", "bonn"),
    "Borken":                   ("05554004", "borken"),
    "Bottrop":                  ("05512000", "bottrop"),
    "Coesfeld":                 ("05558008", "coesfeld"),
    "Dortmund":                 ("05913000", "dortmund"),
    "Duisburg":                 ("05112000", "duisburg"),
    "Düren":                    ("05358004", "dueren"),
    "Düsseldorf":               ("05111000", "duesseldorf"),
    "Ennepe-Ruhr-Kreis":        ("05954008", "ennepe-ruhr-kreis"),
    "Essen":                    ("05113000", "essen"),
    "Euskirchen":               ("05366008", "euskirchen"),
    "Gelsenkirchen":            ("05513000", "gelsenkirchen"),
    "Gütersloh":                ("05754012", "guetersloh"),
    "Hagen":                    ("05914000", "hagen"),
    "Hamm":                     ("05915000", "hamm"),
    "Heinsberg":                ("05370012", "heinsberg"),
    "Herford":                  ("05758012", "herford"),
    "Herne":                    ("05916000", "herne"),
    "Hochsauerlandkreis":       ("05958012", "hochsauerlandkreis"),
    "Höxter":                   ("05762016", "hoexter"),
    "Kleve":                    ("05154016", "kleve"),
    "Köln":                     ("05315000", "koeln"),
    "Krefeld":                  ("05114000", "krefeld"),
    "Leverkusen":               ("05316000", "leverkusen"),
    "Lippe":                    ("05766020", "lippe"),
    "Märkischer Kreis":         ("05962020", "maerkischer-kreis"),
    "Mettmann":                 ("05158020", "mettmann"),
    "Minden-Lübbecke":          ("05770024", "minden-luebbecke"),
    "Mönchengladbach":          ("05116000", "moenchengladbach"),
    "Mülheim an der Ruhr":      ("05117000", "muelheim-an-der-ruhr"),
    "Münster":                  ("05515000", "muenster"),
    "Oberhausen":               ("05119000", "oberhausen"),
    "Oberbergischer Kreis":     ("05374024", "oberbergischer-kreis"),
    "Olpe":                     ("05966024", "olpe"),
    "Paderborn":                ("05774028", "paderborn"),
    "Recklinghausen":           ("05562028", "recklinghausen"),
    "Remscheid":                ("05120000", "remscheid"),
    "Rhein-Erft-Kreis":         ("05362028", "rhein-erft-kreis"),
    "Rhein-Kreis Neuss":        ("05162024", "rhein-kreis-neuss"),
    "Rhein-Sieg-Kreis":         ("05382028", "rhein-sieg-kreis"),
    "Rheinisch-Bergischer Kreis":("05378028","rheinisch-bergischer-kreis"),
    "Siegen-Wittgenstein":      ("05970032", "siegen-wittgenstein"),
    "Soest":                    ("05974036", "soest"),
    "Solingen":                 ("05122000", "solingen"),
    "Steinfurt":                ("05566036", "steinfurt"),
    "Unna":                     ("05978040", "unna"),
    "Viersen":                  ("05166028", "viersen"),
    "Warendorf":                ("05570040", "warendorf"),
    "Wesel":                    ("05170040", "wesel"),
    "Wuppertal":                ("05124000", "wuppertal"),
}



FACHSCHALEN = [

    # ════════════════════════════════════════════════════════════════════════
    # 1. Fundpunkte Tiere
    #    Quelle: FT/FT_Muster.qgz
    #    Gruppen im Projekt: Referenzlisten | WMS
    # ════════════════════════════════════════════════════════════════════════
    {
        "code":        "fundpunkte_tiere",
        "bezeichnung": "Fundpunkte Tiere",
        "schema_name": "fundpunkte_tiere",   # PostGIS-Schema (anpassen)
        "ref_schema":  "referenz",            # PostGIS-Schema (anpassen)

        "geo_layers": [
    {
        "table": "Fund", "geom_col": "geom", "geom_type": "Point",
        "default_values": {
            "Kennung":           {"expression": "uuid()",            "apply_on_update": False},
            "Utm_east":          {"expression": "x(@geometry)",       "apply_on_update": True},
            "Utm_north":         {"expression": "y(@geometry)",       "apply_on_update": True},
            "Aenderungsdatum":   {"expression": "now()",              "apply_on_update": True},
            "Beobachtungsdatum": {"expression": "now()",              "apply_on_update": False},
            "Eingabedatum":      {"expression": "now()",              "apply_on_update": False},
            "Kartierer":         {"expression": "@kartierer",         "apply_on_update": False},
            "Institution":       {"expression": "attribute(get_feature('Institution','term',@institution),'entityid')", "apply_on_update": False},
            "Artname_deutsch":   {"expression": "attribute(get_feature('Arten','entityid',\"Artname\"),'Name_deutsch')", "apply_on_update": True},
            "Artname_wiss":      {"expression": "attribute(get_feature('Arten','entityid',\"Artname\"),'term')",        "apply_on_update": True},
        },
        "value_relations": {
            "Artengruppe": {
                "ref_table": "artengruppen", "key": "listitemid", "value": "term",
                "filter": "", "use_completer": False, "completer_match_flags": 2,
                "order_by_value": False, "allow_null": True, "nof_columns": 1,
            },
            "Artname": {
                "ref_table": "arten", "key": "entityid", "value": "anzeigename",
                "filter": '"parentid" = current_value( \'Artengruppe\')',
                "use_completer": True, "completer_match_flags": 2,
                "order_by_value": False, "allow_null": True, "nof_columns": 1,
            },
            "Institution": {
                "ref_table": "institution", "key": "entityid", "value": "term",
                "filter": "", "use_completer": False, "completer_match_flags": 2,
                "order_by_value": False, "allow_null": True, "nof_columns": 1,
            },
            "Zaehleinheit": {
                "ref_table": "einheit", "key": "entityid", "value": "term",
                "filter": "", "use_completer": False, "completer_match_flags": 2,
                "order_by_value": False, "allow_null": True, "nof_columns": 1,
            },
            "Status": {
                "ref_table": "status", "key": "entityid", "value": "term",
                "filter": "", "use_completer": False, "completer_match_flags": 2,
                "order_by_value": False, "allow_null": True, "nof_columns": 1,
            },
            "Stadium": {
                "ref_table": "stadium", "key": "entityid", "value": "term",
                "filter": "", "use_completer": False, "completer_match_flags": 2,
                "order_by_value": False, "allow_null": True, "nof_columns": 1,
            },
            "Geschlecht": {
                "ref_table": "geschlecht", "key": "entityid", "value": "term",
                "filter": "", "use_completer": False, "completer_match_flags": 2,
                "order_by_value": False, "allow_null": True, "nof_columns": 1,
            },
            "Pop_zustand": {
                "ref_table": "Bewertung_Erhaltungszustand", "key": "entityid", "value": "term",
                "filter": "", "use_completer": False, "completer_match_flags": 2,
                "order_by_value": False, "allow_null": True, "nof_columns": 1,
            },
            "Habitatqualitaet": {
                "ref_table": "Bewertung_Erhaltungszustand", "key": "entityid", "value": "term",
                "filter": "", "use_completer": False, "completer_match_flags": 2,
                "order_by_value": False, "allow_null": True, "nof_columns": 1,
            },
            "Pop_beeintraechtigung": {
                "ref_table": "Bewertung_Erhaltungszustand", "key": "entityid", "value": "term",
                "filter": "", "use_completer": False, "completer_match_flags": 2,
                "order_by_value": False, "allow_null": True, "nof_columns": 1,
            },
            "Erhaltung_gesamt": {
                "ref_table": "Bewertung_Erhaltungszustand", "key": "entityid", "value": "term",
                "filter": "", "use_completer": False, "completer_match_flags": 2,
                "order_by_value": False, "allow_null": True, "nof_columns": 1,
            },
            "Genauigkeit": {
                "ref_table": "Unschaerfe", "key": "entityid", "value": "term",
                "filter": "", "use_completer": False, "completer_match_flags": 2,
                "order_by_value": False, "allow_null": True, "nof_columns": 1,
            },
        },
        "extra_widgets": {
            "Anzahl": {"type": "Range", "min": 0, "max": 2147483647, "step": 1},
        },
    },
],

        # Referenzlisten – aus FT/Referenzen.gpkg
        # Reihenfolge entspricht dem Muster-QGZ (Referenzlisten-Gruppe)
        "ref_tables": [
            "Arten",
            "Arten_Synonyme",
            "Artengruppen",
            "Einheit",
            "Geschlecht",
            "Stadium",
            "Institution",
            "Status",
            "Bewertung_Erhaltungszustand",
            "Unschaerfe",
        ],

        # ── GeoPackage-Offline-Quellen ────────────────────────────────────────
        "gpkg_data": {
            "geo_layers": [
                {
                    "gpkg":      "data/fundpunkte_tiere/Fundpunkte.gpkg",
                    "layername": "Fund",
                    "display":   "Fund",
                    "is_ref":    False,
                },
            ],
            "ref_layers": [
                {"gpkg": "data/fundpunkte_tiere/Referenzen.gpkg", "layername": "Arten"},
                {"gpkg": "data/fundpunkte_tiere/Referenzen.gpkg", "layername": "Arten_Synonyme"},
                {"gpkg": "data/fundpunkte_tiere/Referenzen.gpkg", "layername": "Artengruppen"},
                {"gpkg": "data/fundpunkte_tiere/Referenzen.gpkg", "layername": "Einheit"},
                {"gpkg": "data/fundpunkte_tiere/Referenzen.gpkg", "layername": "Geschlecht"},
                {"gpkg": "data/fundpunkte_tiere/Referenzen.gpkg", "layername": "Stadium"},
                {"gpkg": "data/fundpunkte_tiere/Referenzen.gpkg", "layername": "Institution"},
                {"gpkg": "data/fundpunkte_tiere/Referenzen.gpkg", "layername": "Status"},
                {"gpkg": "data/fundpunkte_tiere/Referenzen.gpkg", "layername": "Bewertung_Erhaltungszustand"},
                {"gpkg": "data/fundpunkte_tiere/Referenzen.gpkg", "layername": "Unschaerfe"},
            ],
            # UG kommt ausschließlich über den UG-Dialog (kein Template hier).
            "border_layers": [],
        },
    },

    # ════════════════════════════════════════════════════════════════════════
    # 2. Biotopbaum
    #    Quelle: Biotopbaum/Erfassung.qgs
    #    Gruppen im Projekt: Refenzlisten | WMS
    # ════════════════════════════════════════════════════════════════════════
    {
        "code":        "biotopbaum",
        "bezeichnung": "Biotopbaum",
        "schema_name": "biotopbaum",   # PostGIS-Schema (anpassen)
        "ref_schema":  "referenz_bt",  # PostGIS-Schema (anpassen)

        "geo_layers": [
            {
                "table":     "Baueme",    # Schreibweise aus GPKG (Tippfehler im Original)
                "geom_col":  "geom",
                "geom_type": "Point",
                # Default-Expressions – exakt aus Biotopbaum/Erfassung.qgs
                "default_values": {
                    "Objektid":       {"expression": "uuid()",                                                                   "apply_on_update": False},
                    "x":              {"expression": "x(@geometry)",                                                             "apply_on_update": True},
                    "y":              {"expression": "y(@geometry)",                                                             "apply_on_update": True},
                    "K_Datum":        {"expression": "now()",                                                                    "apply_on_update": False},
                    "Aenderungsdatum":{"expression": "now()",                                                                    "apply_on_update": True},
                    "bearbeiter":     {"expression": "@kartierer",   "apply_on_update": False},
                    "adrolle":        {"expression": "attribute(get_feature('adressrollle','kurzname',@institution),'entityid')", "apply_on_update": False},
                    "Kartierer":      {"expression": "@kartierer",   "apply_on_update": False},
                    "Institution":    {"expression": "@institution", "apply_on_update": False},
                },
                # ValueRelation-Felder – exakt aus Biotopbaum/Erfassung.qgs
                "value_relations": {
                    "posi_Lage": {
                        "ref_table": "Chance7_Position",
                        "key":       "entityid",
                        "value":     "langname",
                        "filter":    "",
                    },
                    "akkumulat": {
                        "ref_table": "Chance7_Aufnahmetyp",
                        "key":       "entityid",
                        "value":     "kurzname",
                        "filter":    "",
                    },
                    "sonderstruk": {
                        "ref_table": "BAUM_Sonderstrukturen",
                        "key":       "entityid",
                        "value":     "langname",
                        "filter":    "",
                    },
                    "besitzart": {
                        "ref_table": "Besitz",
                        "key":       "entityid",
                        "value":     "kurzname",
                        "filter":    "",
                    },
                    "baumart": {
                        "ref_table": "Baeume_BAUM",
                        "key":       "entityid",
                        "value":     "langname",
                        "filter":    "",
                    },
                    "baumtyp": {
                        "ref_table": "Chance7_Biotopbaum",
                        "key":       "entityid",
                        "value":     "kurzname",
                        "filter":    "",
                    },
                    "Besonnung": {
                        "ref_table": "Chance7_Beschattung",
                        "key":       "entityid",
                        "value":     "langname",
                        "filter":    "",
                    },
                    "vitalitaet": {
                        "ref_table": "Zusatz_Vitalitaet_BAUM",
                        "key":       "entityid",
                        "value":     "kurzname",
                        "filter":    "",
                    },
                    "zersetzung": {
                        "ref_table": "Chance7_Zersetzung",
                        "key":       "entityid",
                        "value":     "langname",
                        "filter":    "",
                    },
                    "adrolle": {
                        "ref_table": "adressrollle",
                        "key":       "entityid",
                        "value":     "term",
                        "filter":    "",
                    },
                    "terminart": {
                        "ref_table": "Termin_BT",
                        "key":       "entityid",
                        "value":     "kurzname",
                        "filter":    "",
                    },
                    "Verkehrssicherungspflicht": {
                        "ref_table": "Verkehrssicherung_BAUM",
                        "key":       "entityid",
                        "value":     "kurzname",
                        "filter":    "",
                    },
                    "Baumpilze": {
                        "ref_table": "Chance7_Baumpilze",
                        "key":       "entityid",
                        "value":     "langname",
                        "filter":    "",
                    },
                },
            },
            {
                # Zweiter Feature-Layer: Baumhöhlen (ohne Geometrie → Attributtabelle)
                "table":     "Hoehlen",
                "geom_col":  None,
                "geom_type": "Tabelle",
                "value_relations": {
                    "Baumhoehlen_Typ": {
                        "ref_table":  "Baumhoehlen",
                        "key":        "entityid",
                        "value":      "Baumhoehlentyp",
                        "filter":     "",
                        "use_completer": False,
                    },
                },
            },
        ],

        # Eltern-Kind-Beziehung: ein Baum hat mehrere Höhlen
        "layer_relations": [
            {
                "id":                 "biotopbaum_hoehlen_baum",
                "name":              "Baumhöhlen",
                "strength":          "Composition",
                "referencing_layer": "Hoehlen",
                "referencing_field": "Baum_ObjektID",
                "referenced_layer":  "Baueme",
                "referenced_field":  "Objektid",
            },
        ],

        # Referenzlisten – aus Biotopbaum/Referenzlisten.gpkg
        # Tabelle1 wird weggelassen (nur Dokumentation, kein Wertfeld)
        "ref_tables": [
            "BAUM_Sonderstrukturen",
            "Baeume_BAUM",
            "Baumhoehlen",
            "Besitz",
            "Chance7_Aufnahmetyp",
            "Chance7_Baumpilze",
            "Chance7_Beschattung",
            "Chance7_Biotopbaum",
            "Chance7_HoeheLage",
            "Chance7_Position",
            "Chance7_Zersetzung",
            "LandschlLage_Baum",
            "LangBreitHoch",
            "Termin_BT",
            "Verkehrssicherung_BAUM",
            "Zusatz_Vitalitaet_BAUM",
            "adressrollle",
        ],

        # ── GeoPackage-Offline-Quellen ────────────────────────────────────────
        # Pfade relativ zum Plugin-Verzeichnis (data/biotopbaum/)
        "gpkg_data": {
            # Erfassungs-Layer (Geometrie + Tabellen)
            "geo_layers": [
                {
                    "gpkg":       "data/biotopbaum/Erfassung.gpkg",
                    "layername":  "Baueme",
                    "display":    "Baueme",
                    "is_ref":     False,
                },
                {
                    "gpkg":       "data/biotopbaum/Erfassung.gpkg",
                    "layername":  "Hoehlen",
                    "display":    "Hoehlen",
                    "is_ref":     False,
                },
            ],
            # Referenzlisten
            "ref_layers": [
                {"gpkg": "data/biotopbaum/Referenzlisten.gpkg", "layername": "BAUM_Sonderstrukturen"},
                {"gpkg": "data/biotopbaum/Referenzlisten.gpkg", "layername": "Baeume_BAUM"},
                {"gpkg": "data/biotopbaum/Referenzlisten.gpkg", "layername": "Baumhoehlen"},
                {"gpkg": "data/biotopbaum/Referenzlisten.gpkg", "layername": "Besitz"},
                {"gpkg": "data/biotopbaum/Referenzlisten.gpkg", "layername": "Chance7_Aufnahmetyp"},
                {"gpkg": "data/biotopbaum/Referenzlisten.gpkg", "layername": "Chance7_Baumpilze"},
                {"gpkg": "data/biotopbaum/Referenzlisten.gpkg", "layername": "Chance7_Beschattung"},
                {"gpkg": "data/biotopbaum/Referenzlisten.gpkg", "layername": "Chance7_Biotopbaum"},
                {"gpkg": "data/biotopbaum/Referenzlisten.gpkg", "layername": "Chance7_HoeheLage"},
                {"gpkg": "data/biotopbaum/Referenzlisten.gpkg", "layername": "Chance7_Position"},
                {"gpkg": "data/biotopbaum/Referenzlisten.gpkg", "layername": "Chance7_Zersetzung"},
                {"gpkg": "data/biotopbaum/Referenzlisten.gpkg", "layername": "LandschlLage_Baum"},
                {"gpkg": "data/biotopbaum/Referenzlisten.gpkg", "layername": "LangBreitHoch"},
                {"gpkg": "data/biotopbaum/Referenzlisten.gpkg", "layername": "Termin_BT"},
                {"gpkg": "data/biotopbaum/Referenzlisten.gpkg", "layername": "Verkehrssicherung_BAUM"},
                {"gpkg": "data/biotopbaum/Referenzlisten.gpkg", "layername": "Zusatz_Vitalitaet_BAUM"},
                {"gpkg": "data/biotopbaum/Referenzlisten.gpkg", "layername": "adressrollle"},
            ],
            # Echte Grenzen (Kreise, FFH usw.) kommen über den Grundlagen-Dialog,
            # nicht mehr über Fachschalen-Relikte. UG kommt über den UG-Dialog.
            "border_layers": [],
        },
    },

    {'bezeichnung': 'Brutvögel',
     'code': 'brutvogel',
     'geo_layers': [{'default_values': {'Anzahl': {'apply_on_update': False, 'expression': '1'},
                                        'BearbeiterIn_letzteAenderung': {'apply_on_update': True,
                                                                         'expression': '@user_account_name'},
                                        'Bemerkung': {'apply_on_update': False, 'expression': "''"},
                                        'Brutstatus': {'apply_on_update': True,
                                                       'expression': 'CASE WHEN "Verhalten" IN '
                                                                     "('Nahrungssuchend','Sichtung','Rastend') AND "
                                                                     '"Stadium_Geschlecht" IN '
                                                                     "('M','W','AV','P','F') THEN 'A' WHEN "
                                                                     '"Stadium_Geschlecht" IN (\'JV\') THEN \'C\' WHEN '
                                                                     '"Verhalten"=\'Rufend\' AND "Stadium_Geschlecht" IN '
                                                                     "('M','W','AV') THEN 'A' WHEN "
                                                                     '"Verhalten"=\'Rufend\' AND '
                                                                     '"Stadium_Geschlecht"=\'P\' THEN \'B\' WHEN '
                                                                     '"Verhalten"=\'Rufend\' AND '
                                                                     '"Stadium_Geschlecht"=\'JV\' THEN \'C\' WHEN '
                                                                     '"Verhalten"=\'Singend\' AND "Stadium_Geschlecht" IN '
                                                                     "('M','W','AV') THEN 'A' WHEN "
                                                                     '"Verhalten"=\'Singend\' AND '
                                                                     '"Stadium_Geschlecht"=\'P\' THEN \'B\' WHEN '
                                                                     '"Verhalten"=\'Warnend\' AND "Stadium_Geschlecht" IN '
                                                                     "('M','W','AV','P','F') THEN 'B' WHEN "
                                                                     '"Verhalten"=\'Warnend\' AND "Stadium_Geschlecht" IN '
                                                                     '(\'JV\') THEN \'C\' WHEN "Verhalten"=\'Mit '
                                                                     'Nistmaterial\' AND "Stadium_Geschlecht" IN '
                                                                     "('M','W','AV','P','F') THEN 'B' WHEN "
                                                                     '"Stadium_Geschlecht"=\'N\' THEN \'C\' WHEN '
                                                                     '"Verhalten"=\'Mit Futter\' AND "Stadium_Geschlecht" '
                                                                     "IN ('M','W','AV','P','F') THEN 'C' ELSE '[Null]' "
                                                                     'END'},
                                        'Brutzeitcode': {'apply_on_update': True,
                                                         'expression': 'CASE WHEN "Verhalten" IN '
                                                                       "('Nahrungssuchend','Sichtung','Rastend') AND "
                                                                       '"Stadium_Geschlecht" IN '
                                                                       "('M','W','AV','P','F') THEN 'A0' WHEN "
                                                                       '"Stadium_Geschlecht" IN (\'JV\') THEN \'C12\' WHEN '
                                                                       '"Verhalten"=\'Rufend\' AND "Stadium_Geschlecht" IN '
                                                                       "('M','W','AV') THEN 'A1' WHEN "
                                                                       '"Verhalten"=\'Rufend\' AND '
                                                                       '"Stadium_Geschlecht"=\'P\' THEN \'B3\' WHEN '
                                                                       '"Verhalten"=\'Rufend\' AND '
                                                                       '"Stadium_Geschlecht"=\'JV\' THEN \'C12\' WHEN '
                                                                       '"Verhalten"=\'Singend\' AND "Stadium_Geschlecht" '
                                                                       "IN ('M','W','AV') THEN 'A2' WHEN "
                                                                       '"Verhalten"=\'Singend\' AND '
                                                                       '"Stadium_Geschlecht"=\'P\' THEN \'B5\' WHEN '
                                                                       '"Verhalten"=\'Warnend\' AND "Stadium_Geschlecht" '
                                                                       "IN ('M','W','AV','P','F') THEN 'B7' WHEN "
                                                                       '"Verhalten"=\'Warnend\' AND "Stadium_Geschlecht" '
                                                                       'IN (\'JV\') THEN \'C12\' WHEN "Verhalten"=\'Mit '
                                                                       'Nistmaterial\' AND "Stadium_Geschlecht" IN '
                                                                       "('M','W','AV','P','F') THEN 'B9' WHEN "
                                                                       '"Stadium_Geschlecht"=\'N\' THEN \'C13b\' WHEN '
                                                                       '"Verhalten"=\'Mit Futter\' AND '
                                                                       '"Stadium_Geschlecht" IN '
                                                                       "('M','W','AV','P','F') THEN 'C14b' ELSE '[Null]' "
                                                                       'END'},
                                        'Genauigkeit': {'apply_on_update': False, 'expression': "'gleich'"},
                                        'Stadium_Geschlecht': {'apply_on_update': False, 'expression': "'M'"},
                                        'Verhalten': {'apply_on_update': False, 'expression': "'Singend'"},
                                        'Zeitstempel_Beobachtung': {'apply_on_update': True,
                                                                    'expression': 'if("nachtraeglich_erfasst",attributes(get_feature(\'Begehungsliste\',\'uuid\',"kartiergang"))[\'Zeitstempel_Start\'],now())'},
                                        'Zeitstempel_Digitalisierung': {'apply_on_update': False, 'expression': 'now()'},
                                        'Zeitstempel_letzteAenderung': {'apply_on_update': True, 'expression': 'now()'},
                                        'anzeigename': {'apply_on_update': True,
                                                        'expression': 'concat("Anzahl",\' '
                                                                      '\',"Vogel_Art",\'-\',represent_value("Stadium_Geschlecht"),\', '
                                                                      '\',represent_value("Verhalten"),\', am '
                                                                      '\',format_date("Zeitstempel_Beobachtung",\'d. '
                                                                      "MMM'),' um "
                                                                      '\',format_date("Zeitstempel_Beobachtung",\'HH:mm\',\'de\'),\' '
                                                                      "Uhr.')"},
                                        'geometry_type': {'apply_on_update': True,
                                                          'expression': 'geometry_type($geometry)'},
                                        'nachtraeglich_erfasst': {'apply_on_update': False, 'expression': 'False'},
                                        'vb_uuid': {'apply_on_update': False, 'expression': 'uuid()'}},
                     'geom_col': 'geom',
                     'geom_type': 'Point',
                     'table': 'Vogelbeobachtungen',
                     'value_relations': {'Brutstatus': {'filter': '',
                                                        'key': 'Brutzeitcode',
                                                        'ref_table': 'Referenzliste_Brutzeitcodes',
                                                        'value': 'anzeigename'},
                                         'Brutzeitcode': {'filter': '',
                                                          'key': 'Brutzeitcode',
                                                          'ref_table': 'Referenzliste_Brutzeitcodes',
                                                          'value': 'anzeigename'}}},
                    {'default_values': {'Bemerkung': {'apply_on_update': False, 'expression': "''"},
                                        'Bewegung_Art': {'apply_on_update': False, 'expression': "'StartLandepunkt'"},
                                        'Zeitstempel_Beobachtung': {'apply_on_update': True,
                                                                    'expression': 'attributes(get_feature(\'Vogelbeobachtungen\',\'vb_uuid\',"vb_uuid"))[\'Zeitstempel_Beobachtung\']'},
                                        'Zeitstempel_Digitalisierung': {'apply_on_update': False, 'expression': 'now()'},
                                        'ob_uuid': {'apply_on_update': False, 'expression': 'uuid()'}},
                     'geom_col': 'geom',
                     'geom_type': 'LineString',
                     'table': 'Ortsbewegungen',
                     'value_relations': {}},
                    {'default_values': {'Bemerkung': {'apply_on_update': False, 'expression': "''"},
                                        'Simultan_Art': {'apply_on_update': False, 'expression': "'direkt'"},
                                        'Zeitstempel_Beobachtung': {'apply_on_update': True,
                                                                    'expression': 'attributes(get_feature(\'Vogelbeobachtungen\',\'vb_uuid\',"vb_uuid"))[\'Zeitstempel_Beobachtung\']'},
                                        'Zeitstempel_Digitalisierung': {'apply_on_update': False, 'expression': 'now()'},
                                        'sim_uuid': {'apply_on_update': False, 'expression': 'uuid()'},
                                        'vb2_uuid': {'apply_on_update': True,
                                                     'expression': 'array_to_string(overlay_nearest(layer:=\'Vogelbeobachtungen\',expression:="vb_uuid",max_distance:=10))'}},
                     'geom_col': 'geom',
                     'geom_type': 'Point',
                     'table': 'Simultanmarker',
                     'value_relations': {'vb2_uuid': {'filter': '',
                                                      'key': 'vb_uuid',
                                                      'ref_table': 'Vogelbeobachtungen',
                                                      'value': 'anzeigename'}}},
                    {'default_values': {'Anzahl': {'apply_on_update': False, 'expression': '1'},
                                        'Bemerkung': {'apply_on_update': False, 'expression': "''"},
                                        'Bemerkung_plausi': {'apply_on_update': False, 'expression': "''"},
                                        'Vogel_Art': {'apply_on_update': True,
                                                      'expression': "array_to_string(array_distinct(aggregate(layer:='Vogelbeobachtungen',aggregate:='array_agg',concatenator:=',',expression:=Vogel_Art,filter:=intersects($geometry,geometry(@parent)))))"},
                                        'flaeche': {'apply_on_update': True, 'expression': '$area'},
                                        'geometry_duplicate': {'apply_on_update': True,
                                                               'expression': "overlay_equals('Papierreviere')"},
                                        'geometry_valid': {'apply_on_update': True, 'expression': 'is_valid($geometry)'}},
                     'geom_col': 'geom',
                     'geom_type': 'Polygon',
                     'table': 'Papierreviere',
                     'value_relations': {}},
                    {'default_values': {'Datum': {'apply_on_update': True,
                                                  'expression': 'substr(to_string(to_date("Zeitstempel_Start")),1,10)'},
                                        'Witterung': {'apply_on_update': False, 'expression': "''"},
                                        'Zeitstempel_Ende': {'apply_on_update': False,
                                                             'expression': '"Zeitstempel_Start" + to_interval(\'4 '
                                                                           "hours')"},
                                        'Zeitstempel_Start': {'apply_on_update': False, 'expression': 'now()'},
                                        'anzeigename': {'apply_on_update': True,
                                                        'expression': 'represent_value("Kartiergang") || \', \' || '
                                                                      'substr(to_string(format_date("Zeitstempel_Start",\'dd.MM.yyyy\',\'de\')),1,10) '
                                                                      '|| \', \' || represent_value("Erfasser")'},
                                        'uuid': {'apply_on_update': False, 'expression': 'uuid()'},
                                        'Erfasser': {'apply_on_update': False, 'expression': "attribute(get_feature('Referenzliste_Mitarbeiter','uuid',array_first(aggregate('Referenzliste_Mitarbeiter','array_agg',\"uuid\",concat(\"Vorname\",\' \',\"Nachname\")=@kartierer))),'uuid')"},
                                        'Kartierer': {'apply_on_update': False, 'expression': '@kartierer'},
                                        'Institution': {'apply_on_update': False, 'expression': '@institution'},
                                        'zeit_plausi': {'apply_on_update': True,
                                                        'expression': '"Zeitstempel_Start" <= "Zeitstempel_Ende"'}},
                     'geom_col': None,
                     'geom_type': 'Tabelle',
                     'table': 'Begehungsliste',
                     'value_relations': {}}],
     'gpkg_data': {'border_layers': [],
                   'geo_layers': [{'display': 'Vogelbeobachtungen',
                                   'gpkg': 'data/brutvogel/QFS_bv.gpkg',
                                   'is_ref': False,
                                   'layername': 'Vogelbeobachtungen'},
                                  {'display': 'Ortsbewegungen',
                                   'gpkg': 'data/brutvogel/QFS_bv.gpkg',
                                   'is_ref': False,
                                   'layername': 'Ortsbewegungen'},
                                  {'display': 'Simultanmarker',
                                   'gpkg': 'data/brutvogel/QFS_bv.gpkg',
                                   'is_ref': False,
                                   'layername': 'Simultanmarker'},
                                  {'display': 'Papierreviere',
                                   'gpkg': 'data/brutvogel/QFS_bv.gpkg',
                                   'is_ref': False,
                                   'layername': 'Papierreviere'},
                                  {'display': 'Begehungsliste',
                                   'gpkg': 'data/brutvogel/QFS_bv.gpkg',
                                   'is_ref': False,
                                   'layername': 'Begehungsliste'}],
                   'ref_layers': [{'gpkg': 'data/brutvogel/QFS_bv.gpkg', 'layername': 'Referenzliste_Arten'},
                                  {'gpkg': 'data/brutvogel/QFS_bv.gpkg', 'layername': 'Referenzliste_Brutzeitcodes'},
                                  {'gpkg': 'data/brutvogel/QFS_bv.gpkg', 'layername': 'Referenzliste_Kartiergaenge'},
                                  {'gpkg': 'data/brutvogel/QFS_bv.gpkg', 'layername': 'Referenzliste_Mitarbeiter'}],
                   'relations': [
                       # strength='Association': lose FK-Verknüpfung (Referenzlisten, Begehungen)
                       # strength='Composition': strenge Eltern-Kind-Beziehung (Ortsbewegungen, Simultanmarker)
                       {'id': 'Begehungsl_Erfasser_Referenzli_uuid',
                        'name': 'ErfasserIn',            'strength': 'Association',
                        'referencing_layer': 'Begehungsliste',          'referencing_field': 'Erfasser',
                        'referenced_layer':  'Referenzliste_Mitarbeiter','referenced_field': 'uuid'},
                       {'id': 'Vogelbeoba_kartiergang_Begehungsl_uuid',
                        'name': 'Begehungsliste',        'strength': 'Association',
                        'referencing_layer': 'Vogelbeobachtungen',      'referencing_field': 'kartiergang',
                        'referenced_layer':  'Begehungsliste',          'referenced_field': 'uuid'},
                       {'id': 'Referenzliste_Kartiergaenge',
                        'name': 'Referenzliste_Kartiergaenge', 'strength': 'Association',
                        'referencing_layer': 'Vogelbeobachtungen',      'referencing_field': 'kartiergang',
                        'referenced_layer':  'Referenzliste_Kartiergaenge','referenced_field': 'kartiergang_nr'},
                       {'id': 'Vogelbeoba_Vogel_Art_Referenzli_name',
                        'name': 'Referenzliste_Arten',   'strength': 'Association',
                        'referencing_layer': 'Vogelbeobachtungen',      'referencing_field': 'Vogel_Art',
                        'referenced_layer':  'Referenzliste_Arten',     'referenced_field': 'name'},
                       {'id': 'Ortsbewegu_vb_uuid_Vogelbeoba_vb_uuid',
                        'name': 'Ortsbewegungen',        'strength': 'Composition',
                        'referencing_layer': 'Ortsbewegungen',          'referencing_field': 'vb_uuid',
                        'referenced_layer':  'Vogelbeobachtungen',      'referenced_field': 'vb_uuid'},
                       {'id': 'Simultanma_vb_uuid_Vogelbeoba_vb_uuid',
                        'name': 'Simultanmarker',        'strength': 'Composition',
                        'referencing_layer': 'Simultanmarker',          'referencing_field': 'vb_uuid',
                        'referenced_layer':  'Vogelbeobachtungen',      'referenced_field': 'vb_uuid'},
                       {'id': 'Vogelbeoba_vb_uuid_Papierrevi_Vogelbeobachtungen',
                        'name': 'Papierreviere',         'strength': 'Association',
                        'referencing_layer': 'Vogelbeobachtungen',      'referencing_field': 'vb_uuid',
                        'referenced_layer':  'Papierreviere',           'referenced_field': 'Vogelbeobachtungen'},
                   ]},
     'ref_schema': 'referenz_brutvogel',
     'ref_tables': ['Referenzliste_Arten',
                    'Referenzliste_Brutzeitcodes',
                    'Referenzliste_Kartiergaenge',
                    'Referenzliste_Mitarbeiter'],
     'schema_name': 'brutvogel'},
]

def get_kreis_by_ags(ags5: str) -> tuple[str, str, str] | None:
    """Gibt (name, ags8, url_name) für einen 5-stelligen AGS zurück."""
    for name, (ags8, url_name) in NRW_KREISE.items():
        if ags8[:5] == ags5[:5]:
            return (name, ags8, url_name)
    return None


def get_kreis_choices() -> list[tuple[str, tuple[str, str]]]:
    """Sortierte Liste (anzeigename, (ags8, url_name)) für ComboBox."""
    return sorted(NRW_KREISE.items())

