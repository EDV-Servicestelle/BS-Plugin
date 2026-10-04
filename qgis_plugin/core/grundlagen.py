"""core/grundlagen.py - NRW OGC-API/WFS Abruf (Schutzgebiete, FFH, ALKIS)"""
import json, math, os, re, xml.etree.ElementTree as ET
try:
    import requests as _requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

try:
    from osgeo import gdal, osr, ogr
    _GDAL_OK = True
except ImportError:
    _GDAL_OK = False

try:
    from qgis.core import (QgsProject, QgsCoordinateTransformContext, QgsVectorLayer, QgsVectorFileWriter,
                           QgsFields, QgsField, QgsFeature, QgsGeometry,
                           QgsWkbTypes, QgsCoordinateReferenceSystem)
    from qgis.PyQt.QtCore import QVariant
    _QGIS_OK = True
except ImportError:
    _QGIS_OK = False

DIENSTE = {
    # ── Verwaltungsgrenzen DVG1 (Geobasis-WFS, GeoJSON) ───────────────────────
    # WFS: https://www.wfs.nrw.de/geobasis/wfs_nw_dvg
    # Nur DVG1: DVG1 hat die HÖHERE Stützpunktdichte (genauer); DVG2 ist die
    # generalisierte Variante (weniger Stützpunkte) – ein Relikt aus der Zeit
    # knappen Speichers, das sich über die Verwaltungssystematik gehalten hat.
    # Abruf über WFS 2.0 GetFeature mit OUTPUTFORMAT=GeoJSON (typ "dvg_geojson").
    # GeoJSON liefert die Attribute zuverlässig als Properties-Dict (anders als
    # das fragile GML-Parsing) – daher kommt der Name (GN) sauber durch.
    # Laut GetCapabilities: Typnamen nw_dvg1_{krs,gem,rbz,bld}; Land = _bld
    # (Bundesland, NICHT _lan!); DefaultCRS EPSG:25832.
    "dvg1_krs": {
        "label":      "Kreise / kreisfreie Städte (DVG1)",
        "typ":        "dvg_geojson",
        "url":        "https://www.wfs.nrw.de/geobasis/wfs_nw_dvg",
        "typename":   "dvg:nw_dvg1_krs",
        "srsname":    "EPSG:25832",
        "felder":     [],
        "felder_all": True,   # alle Attribute übernehmen (echter Feldname unklar)
        "ug_filter":  True,        # nur Objekte die das UG schneiden
        "gruppe":     "Verwaltungsgrenzen (DVG)",
        "layer_group": "Grenzen",   # in Layergruppe "Grenzen" einsortieren
        "default_on": False,
    },
    "dvg1_gem": {
        "label":      "Gemeinden (DVG1)",
        "typ":        "dvg_geojson",
        "url":        "https://www.wfs.nrw.de/geobasis/wfs_nw_dvg",
        "typename":   "dvg:nw_dvg1_gem",
        "srsname":    "EPSG:25832",
        "felder":     [],
        "felder_all": True,   # alle Attribute übernehmen (echter Feldname unklar)
        "ug_filter":  True,
        "gruppe":     "Verwaltungsgrenzen (DVG)",
        "layer_group": "Grenzen",   # in Layergruppe "Grenzen" einsortieren
        "default_on": False,
    },
    "dvg1_rbz": {
        "label":      "Regierungsbezirke (DVG1)",
        "typ":        "dvg_geojson",
        "url":        "https://www.wfs.nrw.de/geobasis/wfs_nw_dvg",
        "typename":   "dvg:nw_dvg1_rbz",
        "srsname":    "EPSG:25832",
        "felder":     [],
        "felder_all": True,   # alle Attribute übernehmen (echter Feldname unklar)
        "ug_filter":  True,
        "gruppe":     "Verwaltungsgrenzen (DVG)",
        "layer_group": "Grenzen",   # in Layergruppe "Grenzen" einsortieren
        "default_on": False,
    },
    "dvg1_lan": {
        "label":      "Land NRW (DVG1)",
        "typ":        "dvg_geojson",
        "url":        "https://www.wfs.nrw.de/geobasis/wfs_nw_dvg",
        "typename":   "dvg:nw_dvg1_bld",
        "srsname":    "EPSG:25832",
        "felder":     [],
        "felder_all": True,   # alle Attribute übernehmen (echter Feldname unklar)
        "ug_filter":  True,
        "gruppe":     "Verwaltungsgrenzen (DVG)",
        "layer_group": "Grenzen",   # in Layergruppe "Grenzen" einsortieren
        "default_on": False,
    },

    # ── Schutzgebiete (OGC-API, je Collection) ───────────────────────────────
    "nsg": {
        "label":      "Naturschutzgebiete (NSG)",
        "typ":        "ogcapi",
        "url":        "https://ogc-api.nrw.de/inspire-ps-schutzgebiete/v1/collections/nsg/items",
        "felder":     [
            ("siteName",   QVariant.String, "Bezeichnung"),
            ("siteCode",   QVariant.String, "Kennung"),
            ("legalBasis", QVariant.String, "Rechtsgrundlage"),
        ],
        "gruppe":     "Schutzgebiete",
        "default_on": True,
    },
    "lsg": {
        "label":      "Landschaftsschutzgebiete (LSG)",
        "typ":        "ogcapi",
        "url":        "https://ogc-api.nrw.de/inspire-ps-schutzgebiete/v1/collections/lsg/items",
        "felder":     [
            ("siteName",   QVariant.String, "Bezeichnung"),
            ("siteCode",   QVariant.String, "Kennung"),
            ("legalBasis", QVariant.String, "Rechtsgrundlage"),
        ],
        "gruppe":     "Schutzgebiete",
        "default_on": True,
    },
    "ffh": {
        "label":      "Natura 2000 FFH-Gebiete",
        "typ":        "ogcapi",
        "url":        "https://ogc-api.nrw.de/inspire-ps-schutzgebiete/v1/collections/ffh/items",
        "felder":     [
            ("siteName",   QVariant.String, "Bezeichnung"),
            ("siteCode",   QVariant.String, "Natura2000-Code"),
            ("legalBasis", QVariant.String, "Rechtsgrundlage"),
        ],
        "gruppe":     "Schutzgebiete",
        "default_on": True,
    },
    "vsg": {
        "label":      "Vogelschutzgebiete (VSG)",
        "typ":        "ogcapi",
        "url":        "https://ogc-api.nrw.de/inspire-ps-schutzgebiete/v1/collections/vsg/items",
        "felder":     [
            ("siteName",   QVariant.String, "Bezeichnung"),
            ("siteCode",   QVariant.String, "Natura2000-Code"),
            ("legalBasis", QVariant.String, "Rechtsgrundlage"),
        ],
        "gruppe":     "Schutzgebiete",
        "default_on": False,
    },
    "ntp": {
        "label":      "Naturparke",
        "typ":        "ogcapi",
        "url":        "https://ogc-api.nrw.de/inspire-ps-schutzgebiete/v1/collections/ntp/items",
        "felder":     [("siteName", QVariant.String, "Bezeichnung"),
                       ("siteCode", QVariant.String, "Kennung")],
        "gruppe":     "Schutzgebiete",
        "default_on": False,
    },
    "nwz": {
        "label":      "Naturwaldzellen",
        "typ":        "ogcapi",
        "url":        "https://ogc-api.nrw.de/inspire-ps-schutzgebiete/v1/collections/nwz/items",
        "felder":     [("siteName", QVariant.String, "Bezeichnung"),
                       ("siteCode", QVariant.String, "Kennung")],
        "gruppe":     "Schutzgebiete",
        "default_on": False,
    },
    "wg": {
        "label":      "Wildnisentwicklungsgebiete",
        "typ":        "ogcapi",
        "url":        "https://ogc-api.nrw.de/inspire-ps-schutzgebiete/v1/collections/wg/items",
        "felder":     [("siteName", QVariant.String, "Bezeichnung"),
                       ("siteCode", QVariant.String, "Kennung")],
        "gruppe":     "Schutzgebiete",
        "default_on": False,
    },
    # ── FFH-Lebensraumtypen (WFS, noch kein OGC-API-Endpunkt bekannt) ────────
    "ffh_lrt": {
        "label":      "FFH-Lebensraumtypen (LRT)",
        "typ":        "ffh_lrt",
        "ogcapi_url": "https://ogc-api.nrw.de/inspire-hb/v1/collections",
        # WFS-Fallback
        "url":        "https://www.wfs.nrw.de/umwelt/wfs_nw_inspire-ffh-lebensraumtypen",
        # FeatureType-Namen werden der Reihe nach probiert
        "typename":   "hb:HabitatOrBiotop",
        "typename_candidates": [
            "hb:HabitatOrBiotop",
            "HB.HabitatOrBiotop",
            "HabitatOrBiotop",
            "hb:HabitatOrBiotopType",
        ],
        "alt_localnames": ["HabitatOrBiotop", "HabitatOrBiotopType",
                            "HabitatOrBiotopCoverType", "HB.HabitatOrBiotop"],
        "ns":         "http://inspire.ec.europa.eu/schemas/hb/4.0",
        # Fallback: GML-ZIP von opengeodata.nrw.de (gesamtes NRW, dann lokal filtern)
        "zip_url":    "https://www.opengeodata.nrw.de/produkte/umwelt_klima/naturschutz/ffh_lrt/Lebensraumtypen_EPSG25832_Shape.zip",
        "zip_format": "shapefile",   # Shape in EPSG:25832, kein GML
        "felder":     [
            ("referenceHabitatTypeCode", QVariant.String, "LRT_Code"),
            ("referenceHabitatTypeName", QVariant.String, "LRT_Name"),
            ("localHabitatName",         QVariant.String, "Lokalname"),
        ],
        "gruppe":     "FFH-Lebensraumtypen",
        "default_on": True,
    },
    # ── Flurstücke ALKIS (OGC-API) ────────────────────────────────────────────
    "flurstuecke": {
        "label":      "Flurstücke / ALKIS",
        "typ":        "ogcapi",
        "url":        "https://ogc-api.nrw.de/lika/v1/collections/flurstueck/items",
        "felder":     [
            ("flurstueckskennzeichen", QVariant.String, "Flurstückskennzeichen"),
            ("amtlicheFlaeche",        QVariant.Double, "Fläche_m2"),
            ("gemarkungsnummer",       QVariant.String, "Gemarkungsnr"),
            ("lagebezeichnung",        QVariant.String, "Lagebezeichnung"),
        ],
        "gruppe":     "Kataster",
        "default_on": True,
    },

    "atkis_gewaesserachse": {
        "label":      "ATKIS – Gewässerachsen (ax_gewaesserachse)",
        "typ":        "atkis_wfs",
        "url":        "https://www.wfs.nrw.de/geobasis/wfs_nw_atkis-basis-dlm_aaa-modell-basiert",
        "typename":   "adv:AX_Gewaesserachse",
        "srsname":    "EPSG:25832",
        "felder":     [
            ("gml_id", QVariant.String, "GML_ID"),
            ("nam", QVariant.String, "Name"),
            ("gewaesserkennzahl", QVariant.String, "Gewaesserkennzahl"),
            ("funktion", QVariant.String, "Funktion"),
            ("breitedesgewaessers", QVariant.Int, "Breite_m_Klasse"),
            ("fliessrichtung", QVariant.Int, "Fliessrichtung"),
            ("hydrologischesmerkmal", QVariant.String, "Hydrologisches_Merkmal"),
            ("widmung", QVariant.String, "Widmung_Gewaesserordnung"),
            ("zustand", QVariant.String, "Zustand"),
        ],        "gruppe":      "ATKIS Basis-DLM",
        "default_on":  True,
        "breakline_role": "fliessgewaesser",   # Linie → TIN-Constraint
    },

    # ── Siedlung ─────────────────────────────────────────────────────────────
    "atkis_siedlung": {
        "label":      "ATKIS – Siedlungsflächen (ax_wohnbauflaeche, ax_industrie)",
        "typ":        "atkis_wfs_multi",
        "url":        "https://www.wfs.nrw.de/geobasis/wfs_nw_atkis-basis-dlm_aaa-modell-basiert",
        "typenames":  ["adv:AX_Wohnbauflaeche", "adv:AX_IndustrieUndGewerbeflaeche"],
        "srsname":    "EPSG:25832",
        "felder":     [
            ("gml_id",   QVariant.String, "GML_ID"),
            ("nam",      QVariant.String, "Name"),
            ("funktion", QVariant.String, "Funktion"),
            ("zustand",  QVariant.String, "Zustand"),
        ],
        "gruppe":      "ATKIS Siedlung",
        "default_on":  False,
    },
    "atkis_strassenverkehr": {
        "label":      "ATKIS – Straßenverkehr (ax_strassenachse)",
        "typ":        "atkis_wfs",
        "url":        "https://www.wfs.nrw.de/geobasis/wfs_nw_atkis-basis-dlm_aaa-modell-basiert",
        "typename":   "adv:AX_Strassenachse",
        "srsname":    "EPSG:25832",
        "felder":     [
            ("gml_id",         QVariant.String, "GML_ID"),
            ("bezeichnung",    QVariant.String, "Bezeichnung"),
            ("strassenschlue", QVariant.String, "Strassenschluessel"),
            ("widmung",        QVariant.String, "Widmung"),
        ],
        "gruppe":      "ATKIS Siedlung",
        "default_on":  False,
    },
    "atkis_bahnverkehr": {
        "label":      "ATKIS – Bahnverkehr (ax_bahnstrecke)",
        "typ":        "atkis_wfs",
        "url":        "https://www.wfs.nrw.de/geobasis/wfs_nw_atkis-basis-dlm_aaa-modell-basiert",
        "typename":   "adv:AX_Bahnstrecke",
        "srsname":    "EPSG:25832",
        "felder":     [
            ("gml_id",     QVariant.String, "GML_ID"),
            ("nam",        QVariant.String, "Name"),
            ("bahnkategor", QVariant.String, "Bahnkategorie"),
        ],
        "gruppe":      "ATKIS Siedlung",
        "default_on":  False,
    },
    "atkis_gebaeude": {
        "label":      "ATKIS – Gebäudegrundrisse (ax_gebaeude)",
        "typ":        "atkis_wfs",
        "url":        "https://www.wfs.nrw.de/geobasis/wfs_nw_atkis-basis-dlm_aaa-modell-basiert",
        "typename":   "adv:AX_Gebaeude",
        "srsname":    "EPSG:25832",
        "felder":     [
            ("gml_id",   QVariant.String, "GML_ID"),
            ("nam",      QVariant.String, "Name"),
            ("funktion", QVariant.String, "Funktion"),
            ("zustand",  QVariant.String, "Zustand"),
        ],
        "gruppe":      "ATKIS Siedlung",
        "default_on":  False,
    },

    # ── 3D-Gebäudemodell LOD-2 (OpenGeoData NRW, CityGML-Kacheln) ───────────
    "lod2": {
        "label":      "3D-Gebäudemodell LOD-2 (Grundflächen)",
        # OGC API Features: https://ogc-api.nrw.de/3dg/v1
        # Collection "building" – bbox nur in WGS84, kein crs/bbox-crs
        "typ":        "lod2_ogcapi",   # eigener Typ: UTM32-BBOX + collection-Fallback
        # Mögliche Collection-Namen (werden der Reihe nach probiert)
        "collection_candidates": ["building", "buildings", "lod2", "lod2_buildings", "gebaeude"],
        "base_url":   "https://ogc-api.nrw.de/3dg/v1/collections",
        "felder":     [
            ("gml_id",          QVariant.String, "GML_ID"),
            ("measuredHeight",  QVariant.Double, "Gebaeudehoehe_m"),
            ("storeysAboveGround", QVariant.Int, "Stockwerke"),
            ("function",        QVariant.String, "Funktion"),
        ],
        "gruppe":     "3D-Gebäude",
        "default_on": False,
        # Fallback auf Kachel-Download falls OGC API kein BBOX-Limit hat
        "fallback_typ": "lod2",
    },

    # ── ATKIS Basis-DLM (WFS AAA-Modell) ─────────────────────────────────────
    # Dieser WFS liefert UTM32 direkt → bbox_utm32 wird intern berechnet
    # URL: https://www.wfs.nrw.de/geobasis/wfs_nw_atkis-basis-dlm_aaa-modell-basiert

    "atkis_gewaesser_stehend": {
        "label":      "ATKIS – Stehende Gewässer (ax_stehendesgewaesser)",
        "typ":        "atkis_wfs",
        "url":        "https://www.wfs.nrw.de/geobasis/wfs_nw_atkis-basis-dlm_aaa-modell-basiert",
        "typename":   "adv:AX_StehendesGewaesser",
        "srsname":    "EPSG:25832",
        "felder":     [
            ("gml_id", QVariant.String, "GML_ID"),
            ("nam", QVariant.String, "Name"),
            ("funktion", QVariant.String, "Funktion"),
            ("schifffahrtskategorie", QVariant.String, "Schifffahrtskategorie"),
            ("zustand", QVariant.String, "Zustand"),
            ("spiegelhoehe", QVariant.Double, "Spiegelhoehe_m"),
        ],        "gruppe":      "ATKIS Basis-DLM",
        "default_on":  True,
        "breakline_role": "stehendes_gewaesser",
    },

    "atkis_gewaesser_fliessend": {
        "label":      "ATKIS – Fließgewässer (ax_fliessgewaesser)",
        "typ":        "atkis_wfs",
        "url":        "https://www.wfs.nrw.de/geobasis/wfs_nw_atkis-basis-dlm_aaa-modell-basiert",
        "typename":   "adv:AX_Fliessgewaesser",
        "srsname":    "EPSG:25832",
        "felder":     [
            ("gml_id", QVariant.String, "GML_ID"),
            ("nam", QVariant.String, "Name"),
            ("gewaesserkennzahl", QVariant.String, "Gewaesserkennzahl"),
            ("funktion", QVariant.String, "Funktion"),
            ("hydrologischesmerkmal", QVariant.String, "Hydrologisches_Merkmal"),
            ("widmung", QVariant.String, "Widmung_Gewaesserordnung"),
            ("zustand", QVariant.String, "Zustand"),
            ("tidemerkmal", QVariant.String, "Tidemerkmal"),
        ],        "gruppe":      "ATKIS Basis-DLM",
        "default_on":  True,
        "breakline_role": "fliessgewaesser",
    },

    "atkis_gewaessermittelachse": {
        "label":      "ATKIS – Berechnete Gewässermittelachsen",
        "typ":        "_intern",   # kein Download, nur GPKG-Schreiben
        "felder":     [
            ("gml_id",            QVariant.String, "GML_ID"),
            ("nam",               QVariant.String, "Name"),
            ("gewaesserkennzahl", QVariant.String, "Gewaesserkennzahl"),
            ("funktion",          QVariant.String, "Funktion"),
            ("breitedesgewaessers", QVariant.Int,  "Breite_m_Klasse"),
            ("fliessrichtung",    QVariant.Int,    "Fliessrichtung"),
            ("hydrologischesmerkmal", QVariant.String, "Hydrologisches_Merkmal"),
            ("widmung",           QVariant.String, "Widmung_Gewaesserordnung"),
            ("zustand",           QVariant.String, "Zustand"),
        ],
        "gruppe":      "ATKIS Basis-DLM",
        "default_on":  False,      # kein Dialog-Checkbox nötig
    },

    "atkis_kanal": {
        "label":      "ATKIS – Kanal (ax_kanal)",
        "typ":        "atkis_wfs",
        "url":        "https://www.wfs.nrw.de/geobasis/wfs_nw_atkis-basis-dlm_aaa-modell-basiert",
        "typename":   "adv:AX_Kanal",
        "srsname":    "EPSG:25832",
        "felder":     [
            ("gml_id",               QVariant.String, "GML_ID"),
            ("nam",                  QVariant.String, "Name"),
            ("gewaesserkennzahl",    QVariant.String, "Gewaesserkennzahl"),
            ("funktion",             QVariant.String, "Funktion"),
            ("widmung",              QVariant.String, "Widmung_Gewaesserordnung"),
            ("schifffahrtskategorie",QVariant.String, "Schifffahrtskategorie"),
            ("zustand",              QVariant.String, "Zustand"),
        ],
        "gruppe":      "ATKIS Basis-DLM",
        "default_on":  True,
        "breakline_role": "fliessgewaesser",
    },

    "atkis_hafenbecken": {
        "label":      "ATKIS – Hafenbecken (ax_hafenbecken)",
        "typ":        "atkis_wfs",
        "url":        "https://www.wfs.nrw.de/geobasis/wfs_nw_atkis-basis-dlm_aaa-modell-basiert",
        "typename":   "adv:AX_Hafenbecken",
        "srsname":    "EPSG:25832",
        "felder":     [
            ("gml_id",   QVariant.String, "GML_ID"),
            ("nam",      QVariant.String, "Name"),
        ],
        "gruppe":      "ATKIS Basis-DLM",
        "default_on":  False,
        "breakline_role": "stehendes_gewaesser",
    },

    "atkis_wohnbau": {
        "label":      "ATKIS – Wohnbaufläche (ax_wohnbauflaeche)",
        "typ":        "atkis_wfs",
        "url":        "https://www.wfs.nrw.de/geobasis/wfs_nw_atkis-basis-dlm_aaa-modell-basiert",
        "typename":   "adv:AX_Wohnbauflaeche",
        "srsname":    "EPSG:25832",
        "felder":     [
            ("gml_id",   QVariant.String, "GML_ID"),
            ("nam",      QVariant.String, "Name"),
            ("funktion", QVariant.String, "Funktion"),
            ("zustand",  QVariant.String, "Zustand"),
        ],
        "gruppe":      "ATKIS Siedlung",
        "default_on":  True,
    },

    "atkis_industrie": {
        "label":      "ATKIS – Industrie und Gewerbe (ax_industrieundgewerbeflaeche)",
        "typ":        "atkis_wfs",
        "url":        "https://www.wfs.nrw.de/geobasis/wfs_nw_atkis-basis-dlm_aaa-modell-basiert",
        "typename":   "adv:AX_IndustrieUndGewerbeflaeche",
        "srsname":    "EPSG:25832",
        "felder":     [
            ("gml_id",    QVariant.String, "GML_ID"),
            ("nam",       QVariant.String, "Name"),
            ("funktion",  QVariant.String, "Funktion"),
            ("zustand",   QVariant.String, "Zustand"),
            ("foerdergueter", QVariant.String, "Foerdergueter"),
        ],
        "gruppe":      "ATKIS Siedlung",
        "default_on":  True,
    },

    "atkis_gemischt": {
        "label":      "ATKIS – Gemischte Nutzung (ax_flaechegemischternutzung)",
        "typ":        "atkis_wfs",
        "url":        "https://www.wfs.nrw.de/geobasis/wfs_nw_atkis-basis-dlm_aaa-modell-basiert",
        "typename":   "adv:AX_FlaecheGemischterNutzung",
        "srsname":    "EPSG:25832",
        "felder":     [
            ("gml_id",   QVariant.String, "GML_ID"),
            ("nam",      QVariant.String, "Name"),
            ("funktion", QVariant.String, "Funktion"),
        ],
        "gruppe":      "ATKIS Siedlung",
        "default_on":  True,
    },

    "atkis_besondere_nutzung": {
        "label":      "ATKIS – Besondere Funktionspräg. (ax_flaechebesondererfunktionalerpraegung)",
        "typ":        "atkis_wfs",
        "url":        "https://www.wfs.nrw.de/geobasis/wfs_nw_atkis-basis-dlm_aaa-modell-basiert",
        "typename":   "adv:AX_FlaecheBesondererFunktionalerPraegung",
        "srsname":    "EPSG:25832",
        "felder":     [
            ("gml_id",   QVariant.String, "GML_ID"),
            ("nam",      QVariant.String, "Name"),
            ("funktion", QVariant.String, "Funktion"),
            ("zustand",  QVariant.String, "Zustand"),
        ],
        "gruppe":      "ATKIS Siedlung",
        "default_on":  True,
    },

    "atkis_sport_freizeit": {
        "label":      "ATKIS – Sport und Freizeit (ax_sportfreizeitunderholungsflaeche)",
        "typ":        "atkis_wfs",
        "url":        "https://www.wfs.nrw.de/geobasis/wfs_nw_atkis-basis-dlm_aaa-modell-basiert",
        "typename":   "adv:AX_SportFreizeitUndErholungsflaeche",
        "srsname":    "EPSG:25832",
        "felder":     [
            ("gml_id",    QVariant.String, "GML_ID"),
            ("nam",       QVariant.String, "Name"),
            ("funktion",  QVariant.String, "Funktion"),
            ("zustand",   QVariant.String, "Zustand"),
            ("zugang",    QVariant.String, "Zugaenglichkeit"),
        ],
        "gruppe":      "ATKIS Siedlung",
        "default_on":  True,
    },

    "atkis_friedhof": {
        "label":      "ATKIS – Friedhof (ax_friedhof)",
        "typ":        "atkis_wfs",
        "url":        "https://www.wfs.nrw.de/geobasis/wfs_nw_atkis-basis-dlm_aaa-modell-basiert",
        "typename":   "adv:AX_Friedhof",
        "srsname":    "EPSG:25832",
        "felder":     [
            ("gml_id",   QVariant.String, "GML_ID"),
            ("nam",      QVariant.String, "Name"),
            ("funktion", QVariant.String, "Funktion"),
            ("zustand",  QVariant.String, "Zustand"),
        ],
        "gruppe":      "ATKIS Siedlung",
        "default_on":  True,
    },

    "atkis_flugverkehr": {
        "label":      "ATKIS – Flugverkehr (ax_flugverkehr)",
        "typ":        "atkis_wfs",
        "url":        "https://www.wfs.nrw.de/geobasis/wfs_nw_atkis-basis-dlm_aaa-modell-basiert",
        "typename":   "adv:AX_Flugverkehr",
        "srsname":    "EPSG:25832",
        "felder":     [
            ("gml_id",   QVariant.String, "GML_ID"),
            ("nam",      QVariant.String, "Name"),
            ("funktion", QVariant.String, "Funktion"),
            ("zustand",  QVariant.String, "Zustand"),
        ],
        "gruppe":      "ATKIS Siedlung",
        "default_on":  False,
    },

    "atkis_schiffsverkehr": {
        "label":      "ATKIS – Schiffsverkehr (ax_schiffsverkehr)",
        "typ":        "atkis_wfs",
        "url":        "https://www.wfs.nrw.de/geobasis/wfs_nw_atkis-basis-dlm_aaa-modell-basiert",
        "typename":   "adv:AX_Schiffsverkehr",
        "srsname":    "EPSG:25832",
        "felder":     [
            ("gml_id",   QVariant.String, "GML_ID"),
            ("nam",      QVariant.String, "Name"),
            ("funktion", QVariant.String, "Funktion"),
            ("schifffahrtskategorie", QVariant.String, "Schifffahrtskategorie"),
        ],
        "gruppe":      "ATKIS Basis-DLM",
        "default_on":  False,
    },

    "atkis_gartenland": {
        "label":      "ATKIS – Gartenland (ax_gartenland)",
        "typ":        "atkis_wfs",
        "url":        "https://www.wfs.nrw.de/geobasis/wfs_nw_atkis-basis-dlm_aaa-modell-basiert",
        "typename":   "adv:AX_Gartenland",
        "srsname":    "EPSG:25832",
        "felder":     [
            ("gml_id",   QVariant.String, "GML_ID"),
            ("nam",      QVariant.String, "Name"),
            ("funktion", QVariant.String, "Funktion"),
        ],
        "gruppe":      "ATKIS Basis-DLM",
        "default_on":  True,
    },

    "atkis_tagebau": {
        "label":      "ATKIS – Tagebau / Grube (ax_tagebaugrubesteinbruch)",
        "typ":        "atkis_wfs",
        "url":        "https://www.wfs.nrw.de/geobasis/wfs_nw_atkis-basis-dlm_aaa-modell-basiert",
        "typename":   "adv:AX_TagebauGrubeSteinbruch",
        "srsname":    "EPSG:25832",
        "felder":     [
            ("gml_id",        QVariant.String, "GML_ID"),
            ("nam",           QVariant.String, "Name"),
            ("abbaugut",      QVariant.String, "Abbaugut"),
            ("zustand",       QVariant.String, "Zustand"),
        ],
        "gruppe":      "ATKIS Basis-DLM",
        "default_on":  False,
    },

    "atkis_halde": {
        "label":      "ATKIS – Halde / Deponie (ax_halde)",
        "typ":        "atkis_wfs",
        "url":        "https://www.wfs.nrw.de/geobasis/wfs_nw_atkis-basis-dlm_aaa-modell-basiert",
        "typename":   "adv:AX_Halde",
        "srsname":    "EPSG:25832",
        "felder":     [
            ("gml_id",    QVariant.String, "GML_ID"),
            ("nam",       QVariant.String, "Name"),
            ("lagergut",  QVariant.String, "Lagergut"),
            ("zustand",   QVariant.String, "Zustand"),
        ],
        "gruppe":      "ATKIS Basis-DLM",
        "default_on":  False,
    },

    "atkis_sumpf": {
        "label":      "ATKIS – Sumpf (ax_sumpf)",
        "typ":        "atkis_wfs",
        "url":        "https://www.wfs.nrw.de/geobasis/wfs_nw_atkis-basis-dlm_aaa-modell-basiert",
        "typename":   "adv:AX_Sumpf",
        "srsname":    "EPSG:25832",
        "felder":     [
            ("gml_id",    QVariant.String, "GML_ID"),
            ("funktion",  QVariant.String, "Funktion"),
        ],
        "gruppe":      "ATKIS Basis-DLM",
        "default_on":  True,
    },

    "atkis_unland": {
        "label":      "ATKIS – Unland / Vegetationslose Fläche (ax_unlandvegetationslosflaeche)",
        "typ":        "atkis_wfs",
        "url":        "https://www.wfs.nrw.de/geobasis/wfs_nw_atkis-basis-dlm_aaa-modell-basiert",
        "typename":   "adv:AX_UnlandVegetationsloseFlaeche",
        "srsname":    "EPSG:25832",
        "felder":     [
            ("gml_id",    QVariant.String, "GML_ID"),
            ("funktion",  QVariant.String, "Funktion"),
            ("oberflaechenmaterial", QVariant.String, "Oberflaechenmaterial"),
        ],
        "gruppe":      "ATKIS Basis-DLM",
        "default_on":  False,
    },


    "atkis_wald": {
        "label":      "ATKIS – Wald (ax_wald)",
        "typ":        "atkis_wfs",
        "url":        "https://www.wfs.nrw.de/geobasis/wfs_nw_atkis-basis-dlm_aaa-modell-basiert",
        "typename":   "adv:AX_Wald",
        "ns":         "http://www.adv-online.de/NAS/15/Anwendungsschema",
        "srsname":    "EPSG:25832",
        "felder":     [
            ("gml_id",             QVariant.String, "GML_ID"),
            ("nam",                QVariant.String, "Name"),
            ("vegetationsmerkmal", QVariant.String, "Waldtyp"),  # 1000=Laub, 2000=Nadel, 3000=Misch
            ("zustand",            QVariant.String, "Zustand"),
        ],
        "gruppe":      "ATKIS Basis-DLM",
        "default_on":  False,
    },
    "atkis_gehoelz": {
        "label":      "ATKIS – Gehölze / Hecken (ax_gehoelz)",
        "typ":        "atkis_wfs",
        "url":        "https://www.wfs.nrw.de/geobasis/wfs_nw_atkis-basis-dlm_aaa-modell-basiert",
        "typename":   "adv:AX_Gehoelz",
        "ns":         "http://www.adv-online.de/NAS/15/Anwendungsschema",
        "srsname":    "EPSG:25832",
        "felder":     [
            ("gml_id",   QVariant.String, "GML_ID"),
            ("nam",      QVariant.String, "Name"),
            ("funktion", QVariant.String, "Funktion"),
        ],
        "gruppe":      "ATKIS Basis-DLM",
        "default_on":  False,
    },
    "atkis_moor": {
        "label":      "ATKIS – Moor / Sumpf (ax_moor, ax_sumpf)",
        "typ":        "atkis_wfs_multi",   # mehrere Typnamen in einem Layer
        "url":        "https://www.wfs.nrw.de/geobasis/wfs_nw_atkis-basis-dlm_aaa-modell-basiert",
        "typenames":  ["adv:AX_Moor", "adv:AX_Sumpf"],
        "ns":         "http://www.adv-online.de/NAS/15/Anwendungsschema",
        "srsname":    "EPSG:25832",
        "felder":     [
            ("gml_id",   QVariant.String, "GML_ID"),
            ("nam",      QVariant.String, "Name"),
            ("funktion", QVariant.String, "Funktion"),
        ],
        "gruppe":      "ATKIS Basis-DLM",
        "default_on":  False,
    },
    "atkis_heide": {
        "label":      "ATKIS – Heide (ax_heide)",
        "typ":        "atkis_wfs",
        "url":        "https://www.wfs.nrw.de/geobasis/wfs_nw_atkis-basis-dlm_aaa-modell-basiert",
        "typename":   "adv:AX_Heide",
        "ns":         "http://www.adv-online.de/NAS/15/Anwendungsschema",
        "srsname":    "EPSG:25832",
        "felder":     [
            ("gml_id",   QVariant.String, "GML_ID"),
            ("nam",      QVariant.String, "Name"),
        ],
        "gruppe":      "ATKIS Basis-DLM",
        "default_on":  False,
    },
    "atkis_landwirtschaft": {
        "label":      "ATKIS – Landwirtschaft / Grünland (ax_landwirtschaft)",
        "typ":        "atkis_wfs",
        "url":        "https://www.wfs.nrw.de/geobasis/wfs_nw_atkis-basis-dlm_aaa-modell-basiert",
        "typename":   "adv:AX_Landwirtschaft",
        "ns":         "http://www.adv-online.de/NAS/15/Anwendungsschema",
        "srsname":    "EPSG:25832",
        "felder":     [
            ("gml_id",   QVariant.String, "GML_ID"),
            ("nam",      QVariant.String, "Name"),
            ("nutzung",  QVariant.String, "Nutzungsart"),   # 1000=Ackerland, 2000=Grünland
            ("zustand",  QVariant.String, "Zustand"),
        ],
        "gruppe":      "ATKIS Basis-DLM",
        "default_on":  False,
    },
}

# ── ATKIS-Grundlagen wie die Verwaltungsgrenzen auf das UG einschränken ──────
# Zentral gesetzt, damit jeder ATKIS-Dienst (auch künftige) den UG-Filter erbt.
# Der Filter im Worker greift nur, wenn ein UG-Polygon vorliegt; die Schwelle
# bezieht sich auf die kleinere von UG-/Objektfläche (s. Worker), sodass auch
# kleine ATKIS-Flächen korrekt erhalten bleiben.
for _atkis_key, _atkis_cfg in DIENSTE.items():
    if _atkis_cfg.get("typ") in ("atkis_wfs", "atkis_wfs_multi"):
        _atkis_cfg.setdefault("ug_filter", True)



# ── WGS84-Bbox aus UTM32-Layer / Canvas ──────────────────────────────────────


# ── CRS-Konstanten ────────────────────────────────────────────────────────────
try:
    from qgis.core import QgsCoordinateReferenceSystem as _CRS
    WGS84 = _CRS("EPSG:4326")
    UTM32 = _CRS("EPSG:25832")
except Exception:
    WGS84 = None
    UTM32 = None


def _wgs84_bbox(lon_min, lat_min, lon_max, lat_max):
    return lon_min, lat_min, lon_max, lat_max


def _wgs84_to_utm32(lon_min, lat_min, lon_max=None, lat_max=None):
    """Transformiert WGS84 nach UTM32N (EPSG:25832).
    Mit 2 Args: (lon, lat) → (e, n)
    Mit 4 Args: (lon_min, lat_min, lon_max, lat_max) → (e_min, n_min, e_max, n_max)
    """
    _single = lon_max is None   # 2-Argument-Modus
    if not _QGIS_OK:
        # Naehreungsformel ohne QGIS
        import math
        lon0 = math.radians(9.0)
        def _merc(lon, lat):
            lr = math.radians(lat)
            ll = math.radians(lon)
            e  = 0.9996 * 6378137.0
            N  = e / math.sqrt(1 - 0.00669438 * math.sin(lr)**2)
            dl = ll - lon0
            E  = 500000 + 0.9996 * N * math.cos(lr) * dl
            M  = e * (lr - 0.00251882 * math.sin(2*lr))
            return E, 0.9996 * M
        sw = _merc(lon_min, lat_min)
        if _single: return sw[0], sw[1]
        ne = _merc(lon_max, lat_max)
        return sw[0], sw[1], ne[0], ne[1]
    from qgis.core import (QgsCoordinateReferenceSystem,
                           QgsCoordinateTransform,
                           QgsCoordinateTransformContext, QgsPointXY)
    wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
    utm32 = QgsCoordinateReferenceSystem("EPSG:25832")
    tr    = QgsCoordinateTransform(wgs84, utm32,
                                   QgsCoordinateTransformContext())
    sw = tr.transform(QgsPointXY(lon_min, lat_min))
    if _single: return sw.x(), sw.y()
    ne = tr.transform(QgsPointXY(lon_max, lat_max))
    return sw.x(), sw.y(), ne.x(), ne.y()


# ── WFS-Abruf ─────────────────────────────────────────────────────────────────

def _fetch_ffh_lrt(cfg: dict, bbox_wgs84: tuple, timeout=90) -> list[dict]:
    """
    FFH-LRT Abruf:
      1. GML-ZIP (primär, zuverlässig)
      2. WFS 2.0 Fallback
      3. WFS 1.1 Fallback
    """
    import io, zipfile
    lon_min, lat_min, lon_max, lat_max = bbox_wgs84
    debug_info = []

    # ── Stufe 1: GML-ZIP ─────────────────────────────────────────────────────
    zip_url = cfg.get("zip_url", "")
    if zip_url and _REQUESTS_OK:
        shp_path = None
        try:
            r = _requests.get(zip_url, timeout=300, stream=True)
            r.raise_for_status()
            import tempfile as _tmp
            tmp = _tmp.NamedTemporaryFile(suffix=".zip", delete=False)
            tmp.write(r.content); tmp.close()
            with zipfile.ZipFile(tmp.name) as zf:
                all_shps = [n for n in zf.namelist() if n.lower().endswith(".shp")]
                for pref in ("polygon", "flaeche", "area"):
                    for n in all_shps:
                        if pref in n.lower(): shp_path = n; break
                    if shp_path: break
                if not shp_path and all_shps: shp_path = all_shps[0]
            debug_info.append(f"ZIP HTTP {r.status_code}, {len(r.content)//1024} KB, shp={shp_path}")
            if shp_path:
                from osgeo import ogr as _og2, osr as _os2
                e_min_u, n_min_u, e_max_u, n_max_u = _wgs84_to_utm32(lon_min, lat_min, lon_max, lat_max)
                ds = _og2.Open(f"/vsizip/{tmp.name}/{shp_path}")
                if ds:
                    lyr = ds.GetLayer(0)
                    lyr.SetSpatialFilterRect(e_min_u, n_min_u, e_max_u, n_max_u)
                    feats_out = []
                    for feat in lyr:
                        geom = feat.GetGeometryRef()
                        if not geom: continue
                        props = {}
                        fd = feat.GetDefnRef()
                        for i in range(fd.GetFieldCount()):
                            name = fd.GetFieldDefn(i).GetName()
                            v = feat.GetField(i)
                            if v is not None: props[name] = str(v)
                        # Feldnamen-Normalisierung (Shapefile: max 10 Zeichen)
                        # Alle Felder case-insensitiv mappen
                        _plc = {k.lower(): (k, v) for k, v in props.items()}
                        # LRT-Code: alle Feldnamen die "code" oder "lrt" enthalten
                        if "referenceHabitatTypeCode" not in props:
                            for _lc_key, (_orig, _val) in _plc.items():
                                if any(x in _lc_key for x in
                                       ("lrt_c", "lrtco", "hab_cod", "habitatco",
                                        "code", "lrt_t", "typ_nr", "typ_cod")):
                                    props["referenceHabitatTypeCode"] = _val; break
                        # LRT-Name: alle Felder die "name" oder "bezeichn" enthalten
                        if "referenceHabitatTypeName" not in props:
                            for _lc_key, (_orig, _val) in _plc.items():
                                if any(x in _lc_key for x in
                                       ("lrt_n", "lrtna", "hab_nam", "habitatna",
                                        "bezeichn", "benennu", "typ_nam")):
                                    props["referenceHabitatTypeName"] = _val; break
                        # Fallback: ersten String-Wert als Code, zweiten als Name
                        _str_fields = [(k,v) for k,v in props.items()
                                       if isinstance(v,str) and v.strip()
                                       and k not in ("quelle",)]
                        if "referenceHabitatTypeCode" not in props and _str_fields:
                            props["referenceHabitatTypeCode"] = _str_fields[0][1]
                        if "referenceHabitatTypeName" not in props and len(_str_fields) > 1:
                            props["referenceHabitatTypeName"] = _str_fields[1][1]
                        # Debug: logge was im ZIP steht
                        if not any("referenceHabitat" in k for k in props):
                            debug_info.append(f"FFH-Felder: {list(props.keys())[:8]}")
                        feats_out.append({"props": props, "wkt": geom.ExportToWkt()})
                    ds = None
                    debug_info.append(f"ZIP BBOX-Filter: {len(feats_out)} Features")
                    import os as _os; _os.unlink(tmp.name)
                    if feats_out: return feats_out
                else:
                    debug_info.append(f"ZIP: OGR konnte Shapefile nicht öffnen: /vsizip/{tmp.name}/{shp_path}")
            else:
                debug_info.append(f"ZIP: kein .shp im Archiv gefunden. Dateien: {all_shps[:5]}")
        except Exception as _e:
            debug_info.append(f"ZIP-Fehler: {_e}")
            try:
                import os as _os; _os.unlink(tmp.name)
            except: pass

    # ── Stufe 2: WFS 2.0 ─────────────────────────────────────────────────────
    candidates = cfg.get("typename_candidates", [cfg.get("typename", "")])
    for tn in candidates:
        raw = b""; status = 0
        try:
            params = {"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
                      "TYPENAMES": tn, "COUNT": "5000",
                      "BBOX": f"{lon_min},{lat_min},{lon_max},{lat_max},urn:ogc:def:crs:OGC:1.3:CRS84"}
            r = _requests.get(cfg["url"], params=params, timeout=timeout)
            status = r.status_code; raw = r.content
        except Exception as _e:
            debug_info.append(f"WFS2 {tn}: {_e}"); continue
        if status == 200 and b"<" in raw[:200]:
            sub = dict(cfg); sub["typename"] = tn
            feats = _parse_wfs_gml(raw, sub)
            if feats: return feats
            debug_info.append(f"WFS2 {tn}: HTTP {status}, GML: {raw[:200].decode('utf-8','replace')}")
        else:
            debug_info.append(f"WFS2 {tn}: HTTP {status}")

    # ── Stufe 3: WFS 1.1 ─────────────────────────────────────────────────────
    for tn in candidates:
        raw = b""; status = 0
        try:
            params = {"SERVICE": "WFS", "VERSION": "1.1.0", "REQUEST": "GetFeature",
                      "TYPENAME": tn, "MAXFEATURES": "5000",
                      "SRSNAME": "urn:ogc:def:crs:EPSG::4326",
                      "BBOX": f"{lat_min},{lon_min},{lat_max},{lon_max},urn:ogc:def:crs:EPSG::4326"}
            r = _requests.get(cfg["url"], params=params, timeout=timeout)
            status = r.status_code; raw = r.content
        except Exception as _e:
            debug_info.append(f"WFS1 {tn}: {_e}"); continue
        if status == 200 and b"<" in raw[:200]:
            sub = dict(cfg); sub["typename"] = tn
            feats = _parse_wfs_gml(raw, sub)
            if feats: return feats
            debug_info.append(f"WFS1 {tn}: HTTP {status}, GML: {raw[:300].decode('utf-8','replace')}")
        else:
            debug_info.append(f"WFS1 {tn}: HTTP {status}")

    # Alle Stufen gescheitert → Diagnose als Exception
    if debug_info:
        raise RuntimeError("FFH-LRT 0 Features: " + " | ".join(debug_info[:4]))
    return []

def _is_float(s):
    try: float(s); return True
    except ValueError: return False


def _fetch_wfs(cfg: dict, bbox_wgs84: tuple, timeout=60) -> list[dict]:
    """
    Ruft Features über WFS 2.0 GetFeature mit BBOX-Filter ab.
    Gibt Liste von {props: dict, wkt: str} zurück.
    """
    lon_min, lat_min, lon_max, lat_max = bbox_wgs84
    params = {
        "SERVICE":      "WFS",
        "VERSION":      "2.0.0",
        "REQUEST":      "GetFeature",
        "TYPENAMES":    cfg["typename"],
        "BBOX":         f"{lon_min},{lat_min},{lon_max},{lat_max},urn:ogc:def:crs:EPSG::4326",
        "OUTPUTFORMAT": "application/gml+xml; version=3.2",
        "COUNT":        "2000",
    }

    r = _requests.get(cfg["url"], params=params, timeout=timeout)
    r.raise_for_status()
    return _parse_wfs_gml(r.content, cfg)


def _parse_wfs_gml(xml_bytes: bytes, cfg: dict) -> list[dict]:
    """Parst GML-Antwort und extrahiert Features."""
    features = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        raise RuntimeError(f"GML-Parse-Fehler: {e}")

    # Namespace-Map für XPath
    ns_tag = cfg.get("typename", "").split(":")[0]
    # Alle Member-Elemente durchsuchen
    for member in root.iter():
        tag = member.tag.split("}")[-1] if "}" in member.tag else member.tag
        if tag in ("member", "featureMember", "featureMembers"):
            continue
        if "}" not in member.tag:
            continue
        # Feature-Elemente: alle bekannten Varianten des Elementnamens
        feature_localname = cfg["typename"].split(":")[-1]
        alt_names = cfg.get("alt_localnames", [])
        valid_names = {feature_localname} | set(alt_names)
        # Auch Variante ohne abschließendes "Type" prüfen
        if feature_localname.endswith("Type"):
            valid_names.add(feature_localname[:-4])
        if tag not in valid_names:
            continue

        props = {}
        geom_wkt = None

        for child in member:
            child_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

            # Geometrie extrahieren – alle bekannten Feld-Namen
            if child_tag in ("geometry", "the_geom", "geom", "shape",
                             "extent", "location", "position",
                             "geometrie", "punktGeometrie",
                             "msGeometry", "ogr_geometry"):
                wkt_candidate = _gml_to_wkt(child)
                if wkt_candidate:
                    geom_wkt = wkt_candidate
                continue
            # Fallback: Kind-Element enthält direkt GML-Geometrie?
            if geom_wkt is None:
                for gml_tag in ("MultiSurface", "Polygon", "Point",
                                "MultiPolygon", "LineString", "MultiLineString"):
                    for desc in child.iter():
                        dtag = desc.tag.split("}")[-1] if "}" in desc.tag else desc.tag
                        if dtag == gml_tag:
                            wkt_candidate = _gml_to_wkt(desc)
                            if wkt_candidate:
                                geom_wkt = wkt_candidate
                            break
                    if geom_wkt:
                        break

            # Einfache Felder extrahieren (direkter Text + verschachtelte Elemente)
            for src_name, _, _ in cfg.get("felder", []):
                if child_tag.lower() == src_name.lower() and src_name not in props:
                    txt = child.text.strip() if child.text and child.text.strip() else ""
                    if not txt:
                        txt = " ".join(
                            (e.text or "").strip() for e in child.iter()
                            if e.text and e.text.strip()
                        )
                    if txt:
                        props[src_name] = txt

            # felder_all: ALLE Attribute generisch übernehmen – direkter Text,
            # verschachtelter Text UND XML-Attribute (für Dienste mit
            # unbekanntem Schema, z. B. DVG).
            if cfg.get("felder_all"):
                if child_tag not in props:
                    _t = child.text.strip() if child.text and child.text.strip() else ""
                    if not _t:
                        _t = " ".join((e.text or "").strip() for e in child.iter()
                                      if e.text and e.text.strip())
                    if _t:
                        props[child_tag] = _t
                for _ak, _av in child.attrib.items():
                    _akl = _ak.split("}")[-1]
                    if _av and _av.strip() and _akl not in props:
                        props[_akl] = _av.strip()

            # Geschachtelte Felder (z.B. CharacterString, LocalisedCharacterString)
            for desc in child.iter():
                dtag = desc.tag.split("}")[-1] if "}" in desc.tag else desc.tag
                if dtag in ("CharacterString", "LocalisedCharacterString",
                            "localName", "codeSpace") and desc.text:
                    if child_tag not in props:
                        props[child_tag] = desc.text.strip()
                    break

        if geom_wkt:
            features.append({"props": props, "wkt": geom_wkt})

    return features


def _gml_to_wkt(geom_elem) -> str | None:
    """
    Einfacher GML→WKT-Konverter für Polygone, MultiPolygone und Punkte.
    Fallback: None.
    """
    def _coords(coord_text: str) -> list:
        nums = coord_text.split()
        pts = []
        for i in range(0, len(nums) - 1, 2):
            try:
                pts.append((float(nums[i]), float(nums[i + 1])))
            except ValueError:
                pass
        return pts

    for elem in geom_elem.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag in ("posList", "coordinates") and elem.text:
            pts = _coords(elem.text.strip())
            if not pts:
                return None
            # Polygon
            ring = ", ".join(f"{x} {y}" for x, y in pts)
            return f"POLYGON(({ring}))"
        if tag == "pos" and elem.text:
            c = elem.text.strip().split()
            if len(c) >= 2:
                return f"POINT({c[0]} {c[1]})"
    return None


# ── OGC-API-Abruf (Flurstücke) ────────────────────────────────────────────────

def _fetch_ogcapi(cfg: dict, bbox_wgs84: tuple, timeout=60) -> list[dict]:
    """
    Ruft Features über OGC-API Features (GeoJSON) mit bbox-Parameter ab.
    Paginierung über 'next'-Link.
    """
    lon_min, lat_min, lon_max, lat_max = bbox_wgs84
    url = cfg["url"]
    no_crs = cfg.get("no_crs_params", False)
    params = {
        "bbox":  f"{lon_min},{lat_min},{lon_max},{lat_max}",
        "f":     "json",
        "limit": 500,
    }
    if not no_crs:
        params["bbox-crs"] = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
        params["crs"]      = "http://www.opengis.net/def/crs/EPSG/0/25832"

    features = []
    while url:
        r = _requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        for feat in data.get("features", []):
            props = feat.get("properties", {})
            geom  = feat.get("geometry")
            wkt   = _geojson_geom_to_wkt(geom)
            if wkt:
                features.append({"props": props, "wkt": wkt})

        # Paginierung
        url    = None
        params = {}   # Nur für erste Anfrage
        for link in data.get("links", []):
            if link.get("rel") == "next":
                url = link.get("href")
                break

    return features


def _geojson_geom_to_wkt(geom: dict | None) -> str | None:
    if not geom:
        return None
    gtype = geom.get("type", "")
    coords = geom.get("coordinates")
    if not coords:
        return None

    if gtype == "Point":
        return f"POINT({coords[0]} {coords[1]})"
    elif gtype == "Polygon":
        rings = []
        for ring in coords:
            r = ", ".join(f"{p[0]} {p[1]}" for p in ring)
            rings.append(f"({r})")
        return f"POLYGON({', '.join(rings)})"
    elif gtype == "MultiPolygon":
        polys = []
        for poly in coords:
            rings = []
            for ring in poly:
                r = ", ".join(f"{p[0]} {p[1]}" for p in ring)
                rings.append(f"({r})")
            polys.append(f"({', '.join(rings)})")
        return f"MULTIPOLYGON({', '.join(polys)})"
    return None


# ── GPKG-Schreiber ────────────────────────────────────────────────────────────

def _write_to_gpkg(gpkg_path: str, layer_name: str,
                   features: list[dict], cfg: dict,
                   crs: QgsCoordinateReferenceSystem,
                   append: bool = False):
    """Schreibt Feature-Liste in GPKG-Layer (nutzt SaveVectorOptions korrekt)."""
    if not features:
        return 0

    # Felder definieren
    qfields = QgsFields()
    qfields.append(QgsField("quelle", QVariant.String))
    if cfg.get("felder_all"):
        # Attributschema dynamisch aus den vorhandenen Properties ableiten
        _keys = []
        for _it in features:
            for _k in _it.get("props", {}).keys():
                if _k and _k not in _keys:
                    _keys.append(_k)
        felder_list = [(k, QVariant.String, k) for k in _keys]
    else:
        felder_list = cfg.get("felder", [])
    for src, qtype, alias in felder_list:
        f = QgsField(src, qtype)
        f.setAlias(alias)
        qfields.append(f)

    # Geometrietyp aus WKT ableiten
    geom_type = QgsWkbTypes.Type.MultiPolygon   # Default
    for feat in features[:20]:
        wkt = feat.get("wkt", "").upper()
        if wkt.startswith("POINT"):
            geom_type = QgsWkbTypes.Type.Point; break
        elif "LINESTRING" in wkt or "MULTILINESTRING" in wkt:
            geom_type = QgsWkbTypes.Type.MultiLineString; break
        elif "POLYGON" in wkt:
            geom_type = QgsWkbTypes.Type.MultiPolygon; break

    # SaveVectorOptions korrekt verwenden
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName   = "GPKG"
    opts.layerName    = layer_name
    opts.fileEncoding = "UTF-8"
    if not os.path.exists(gpkg_path):
        opts.actionOnExistingFile = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
    elif append:
        # AppendToLayerNoNewFields nur wenn Layer schon existiert
        try:
            from osgeo import ogr as _ogr2
            _ds = _ogr2.Open(gpkg_path)
            _layer_exists = _ds and _ds.GetLayerByName(layer_name) is not None
            _ds = None
        except Exception:
            _layer_exists = False
        opts.actionOnExistingFile = (
            QgsVectorFileWriter.ActionOnExistingFile.AppendToLayerNoNewFields
            if _layer_exists else
            QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
        )
    else:
        opts.actionOnExistingFile = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer

    # Temporären In-Memory-Layer als Quelle für writeAsVectorFormatV3
    mem_uri = f"{'Point' if geom_type == QgsWkbTypes.Type.Point else 'MultiLineString' if geom_type == QgsWkbTypes.Type.MultiLineString else 'MultiPolygon'}?crs=EPSG:25832"
    mem_lyr = QgsVectorLayer(mem_uri, layer_name, "memory")
    mem_lyr.dataProvider().addAttributes(qfields.toList())
    mem_lyr.updateFields()

    mem_feats = []
    for item in features:
        feat = QgsFeature(mem_lyr.fields())
        geom = QgsGeometry.fromWkt(item["wkt"])
        if not geom or geom.isEmpty():
            continue
        feat.setGeometry(geom)
        feat["quelle"] = cfg["label"]
        props = item.get("props", {})
        for src, _, _ in felder_list:
            val = props.get(src)
            if val is None:   # case-insensitiver Fallback
                sl = src.lower()
                for k, v in props.items():
                    if k.lower() == sl: val = v; break
            if val is not None:
                try: feat[src] = val
                except: pass
        mem_feats.append(feat)

    mem_lyr.dataProvider().addFeatures(mem_feats)

    err, msg, _, _ = QgsVectorFileWriter.writeAsVectorFormatV3(
        mem_lyr, gpkg_path,
        QgsCoordinateTransformContext(), opts)

    if err != QgsVectorFileWriter.WriterError.NoError:
        raise RuntimeError(f"GPKG-Schreiben fehlgeschlagen: {msg}")

    return len(mem_feats)


# ── Worker ────────────────────────────────────────────────────────────────────

# ── LOD-2 CityGML Download ─────────────────────────────────────────────────────

LOD2_TILE_M = 1000   # Kachelgröße 1×1 km


def _lod2_tiles(e_min, n_min, e_max, n_max):
    """Gibt Liste von (e_km, n_km)-Kacheln für das Gebiet zurück."""
    e0 = int(e_min / LOD2_TILE_M) * LOD2_TILE_M
    n0 = int(n_min / LOD2_TILE_M) * LOD2_TILE_M
    tiles = []
    e = e0
    while e < e_max:
        n = n0
        while n < n_max:
            tiles.append((int(e / 1000), int(n / 1000)))
            n += LOD2_TILE_M
        e += LOD2_TILE_M
    return tiles


def _lod2_kachel_url(e_km, n_km):
    """Download-URL für eine LOD-2-Kachel (NRW OpenGeoData)."""
    return (f"https://www.opengeodata.nrw.de/produkte/geobasis/3dg/lod2/"
            f"lod2_{e_km}_{n_km}_1_nw.gml.gz")


def _safe_float(s):
    try: return float(s)
    except: return None


def _fetch_lod2(cfg, bbox_wgs84, out_gpkg, worker=None):
    """
    Lädt LOD-2 CityGML-Kacheln und extrahiert Gebäudegrundflächen.
    Gibt Anzahl extrahierter Gebäude zurück.
    """
    import gzip as _gz
    import xml.etree.ElementTree as _ET

    def _log(msg):
        if worker: worker.progress.emit(-1, f"  [LOD-2] {msg}")

    if not _REQUESTS_OK:
        _log("requests fehlt")
        return 0

    lon_min, lat_min, lon_max, lat_max = bbox_wgs84
    e_min, n_min, e_max, n_max = _wgs84_to_utm32(lon_min, lat_min, lon_max, lat_max)
    tiles = _lod2_tiles(e_min, n_min, e_max, n_max)
    _log(f"{len(tiles)} Kachel(n)")

    try:
        from osgeo import ogr as _og, osr as _os
    except ImportError:
        _log("GDAL fehlt"); return 0

    drv = _og.GetDriverByName("GPKG")
    ds  = _og.Open(out_gpkg, 1) if os.path.exists(out_gpkg)           else drv.CreateDataSource(out_gpkg)
    sr  = _os.SpatialReference(); sr.ImportFromEPSG(25832)

    lyr_name = "lod2_gebaeude"
    lyr = ds.GetLayerByName(lyr_name)
    if lyr is None:
        lyr = ds.CreateLayer(lyr_name, sr, _og.wkbMultiPolygon)
        for fname, _ftype, _falias in cfg.get("felder", []):
            lyr.CreateField(_og.FieldDefn(fname, _og.OFTString
                            if "str" in str(_ftype).lower() else _og.OFTReal))

    NS_BLDG = "http://www.opengis.net/citygml/building/2.0"
    NS_GML  = "http://www.opengis.net/gml"

    n_total = 0
    for i, (e_km, n_km) in enumerate(tiles):
        url = _lod2_kachel_url(e_km, n_km)
        _log(f"Kachel {i+1}/{len(tiles)}: {e_km}_{n_km}")
        try:
            resp = _requests.get(url, timeout=60)
            if resp.status_code == 404:
                _log(f"  leer"); continue
            resp.raise_for_status()
            raw  = _gz.decompress(resp.content)
            root = _ET.fromstring(raw)

            for bldg in root.iter(f"{{{NS_BLDG}}}Building"):
                gml_id  = bldg.get(f"{{{NS_GML}}}id", "")
                h_grund = h_traufe = h_first = None

                # Geländehöhe / Firsthöhe
                for hm in bldg.findall(f".//{{{NS_BLDG}}}measuredHeight"):
                    h_first = _safe_float(hm.text)

                # GroundSurface → Grundfläche
                gs_polys = []
                for ps in bldg.findall(
                        f".//{{{NS_BLDG}}}groundSurface//{{{NS_GML}}}posList"):
                    raw_c = ps.text.strip().split()
                    coords = [(float(raw_c[j]), float(raw_c[j+1]), float(raw_c[j+2]))
                              for j in range(0, len(raw_c)-2, 3)]
                    if len(coords) < 3: continue
                    if h_grund is None: h_grund = coords[0][2]
                    ring = _og.Geometry(_og.wkbLinearRing)
                    for e_, n_, z_ in coords: ring.AddPoint(e_, n_, z_)
                    ring.CloseRings()
                    poly = _og.Geometry(_og.wkbPolygon); poly.AddGeometry(ring)
                    gs_polys.append(poly)

                if not gs_polys: continue
                mp = _og.Geometry(_og.wkbMultiPolygon)
                for p in gs_polys: mp.AddGeometry(p)

                feat = _og.Feature(lyr.GetLayerDefn())
                feat.SetGeometry(mp)
                feat.SetField("gml_id",       gml_id)
                feat.SetField("hoehe_grund",  h_grund  or 0.0)
                feat.SetField("hoehe_traufe", h_traufe or 0.0)
                feat.SetField("hoehe_first",  h_first  or 0.0)
                lyr.CreateFeature(feat)
                n_total += 1

        except Exception as _e:
            _log(f"Fehler: {_e}")

    ds.FlushCache(); ds = None
    _log(f"✓ {n_total} Gebäude → {out_gpkg}")
    return n_total




_LOD2_FUNKTION = {
    # ── 4-stellige ALKIS-Codes (ALKIS WFS, ATKIS) ─────────────────────────
    # Wohnen
    "1000": "Wohngebäude",
    "1010": "Wohnhaus",
    "1020": "Wohnheim",
    "1021": "Kinderheim",
    "1022": "Seniorenheim",
    "1023": "Schwesternwohnheim",
    "1024": "Studenten-/Schülerwohnheim",
    "1025": "Schullandheim",
    "1100": "Gemischt genutztes Gebäude mit Wohnen",
    "1210": "Land-/forstwirtschaftliches Wohngebäude",
    "1220": "Land-/forstwirtschaftliches Wohn- und Betriebsgebäude",
    "1223": "Forsthaus",
    "1310": "Gebäude zur Freizeitgestaltung",
    "1311": "Ferienhaus",
    "1312": "Wochenendhaus",
    "1313": "Gartenhaus",
    # Wirtschaft/Gewerbe
    "2000": "Gebäude für Wirtschaft oder Gewerbe",
    "2010": "Gewerbe- und Industriegebäude",
    "2020": "Fabrik",
    "2030": "Werkstatt",
    "2040": "Lagergebäude",
    "2050": "Halle",
    "2060": "Betriebsgebäude zur Infrastruktur",
    "2070": "Gebäude für Beherbergung",
    "2071": "Hotel",
    "2072": "Motel",
    "2073": "Jugendherberge",
    "2080": "Gebäude für Bewirtung",
    "2081": "Gaststätte/Restaurant",
    "2090": "Gebäude für Handel und Dienstleistungen",
    "2091": "Kaufhaus/Warenhaus",
    "2092": "Einkaufszentrum",
    "2093": "Markt",
    "2100": "Gebäude für Gewerbe und Industrie",
    "2110": "Fabrikgebäude",
    "2120": "Kraftwerk",
    "2121": "Kernkraftwerk",
    "2130": "Wasserwerk",
    "2131": "Pumpstation",
    "2140": "Gebäude für Vorratshaltung",
    "2141": "Kühlhaus",
    "2142": "Silo",
    "2150": "Umspannwerk",
    "2160": "Gebäude für Forschungszwecke",
    "2170": "Gebäude für Grundstoffgewinnung",
    "2180": "Gebäude für betriebliche Sozialeinrichtung",
    "2190": "Tiefgarage",
    "2200": "Parkhaus",
    "2210": "Tankstelle",
    "2220": "Werkstatt Kfz",
    "2250": "Bahngebäude",
    "2251": "Empfangsgebäude",
    "2260": "Flughafengebäude",
    "2270": "Hafengebäude",
    "2310": "Messe/Ausstellung",
    "2320": "Schlachthof",
    "2510": "Gebäude für Versorgung",
    "2520": "Gebäude für Entsorgung",
    "2530": "Kläranlage",
    "2540": "Gebäude für Fernmeldewesen",
    "2550": "Gebäude an unterirdischen Leitungen",
    "2560": "Gebäude der Abfalldeponie",
    "2600": "Bunker",
    "2610": "Militärisches Gebäude",
    "2620": "Kaserne",
    # Öffentliche Zwecke
    "3000": "Gebäude für öffentliche Zwecke",
    "3010": "Rathaus",
    "3020": "Gebäude für Bildung und Forschung",
    "3021": "Schule",
    "3022": "Hochschule/Universität",
    "3023": "Berufsschule",
    "3024": "Sonderschule",
    "3025": "Kindergarten/Kita",
    "3026": "Kinderkrippe",
    "3030": "Gebäude für kulturelle Zwecke",
    "3031": "Theater/Oper",
    "3032": "Kino",
    "3033": "Museum/Galerie",
    "3034": "Bibliothek",
    "3035": "Veranstaltungsgebäude",
    "3036": "Mehrzweckhalle",
    "3040": "Gebäude für religiöse Zwecke",
    "3041": "Kirche/Kapelle",
    "3042": "Kloster",
    "3043": "Moschee",
    "3044": "Synagoge",
    "3045": "Sakralbau",
    "3050": "Gebäude für Gesundheitswesen",
    "3051": "Krankenhaus",
    "3052": "Pflegeheim/Altenheim",
    "3053": "Arztpraxis/Poliklinik",
    "3054": "Apotheke",
    "3055": "Rehazentrum",
    "3060": "Gebäude für soziale Zwecke",
    "3061": "Jugendheim",
    "3062": "Obdachlosenheim",
    "3070": "Gebäude für Sicherheit und Ordnung",
    "3071": "Polizei",
    "3072": "Feuerwache",
    "3073": "Rettungswache",
    "3074": "Gericht",
    "3075": "Gefängnis/JVA",
    "3080": "Verwaltungsgebäude",
    "3081": "Bundesbehörde",
    "3082": "Landesbehörde",
    "3083": "Kommunalbehörde",
    "3090": "Post/Kommunikation",
    "3100": "Gebäude für öffentliche Zwecke mit Wohnen",
    "3200": "Gebäude für Erholungszwecke",
    "3210": "Gebäude für Sportzwecke",
    "3211": "Sporthalle",
    "3212": "Hallenbad",
    "3213": "Stadion",
    "3220": "Gebäude im Freibad",
    "3230": "Saunagebäude",
    "3240": "Gebäude für Kurbetrieb",
    "3241": "Kurhaus",
    "3270": "Gewächshaus/Treibhaus",
    "3280": "Gebäude für andere Erholungseinrichtung",
    # Land-/Forstwirtschaft
    "9900": "Wirtschaftsgebäude zur Land- und Forstwirtschaft",
    "9910": "Scheune",
    "9920": "Stall",
    "9930": "Gewächshaus",
    "9940": "Silo (Landwirtschaft)",
    # Garagen/Nebengebäude
    "9998": "Garage",
    "9999": "Nebengebäude",

    # ── 5-stellige CityGML LOD-2-Codes (NRW 3D-Gebäudemodell) ─────────────
    # Wohnen
    "31001": "Wohngebäude",
    "31002": "Wohn-/Geschäftsgebäude",
    "31003": "Wohnheim",
    "31051": "Wohngebäude mit Gemeinbedarf",
    # Gewerbe/Industrie
    "32001": "Gewerbe-/Industriegebäude",
    "32002": "Fabrik",
    "32003": "Werkstatt",
    "32004": "Lagergebäude",
    "32005": "Kühlhaus",
    "32006": "Kraftwerk",
    "32007": "Umspannwerk",
    "32008": "Wasserwerk",
    "32009": "Kläranlage",
    "32010": "Pumpstation",
    "32011": "Bunker",
    "32051": "Handel u. Dienstleistung",
    # Handel
    "33001": "Handels-/Dienstleistungsgebäude",
    "33011": "Kaufhaus/Warenhaus",
    "33012": "Einkaufszentrum",
    "33021": "Ausstellungsgebäude",
    "33031": "Gaststätte/Restaurant",
    "33041": "Freizeitgebäude",
    "33051": "Übernachtungsgebäude",
    # Büro/Bank
    "34001": "Bürogebäude",
    "34002": "Bankgebäude",
    "34003": "Versicherungsgebäude",
    # Hotel
    "35001": "Hotel/Motel",
    "35002": "Jugendherberge",
    "35003": "Camping/Ferienhaus",
    # Sakral
    "36001": "Kirche/Kapelle",
    "36002": "Kloster",
    "36003": "Moschee",
    "36004": "Synagoge",
    "36005": "Sakralbau",
    # Gesundheit
    "37001": "Krankenhaus",
    "37002": "Pflegeheim/Altenheim",
    "37003": "Arztpraxis/Poliklinik",
    # Bildung
    "38001": "Schule",
    "38002": "Hochschule/Universität",
    "38003": "Kindergarten/Kita",
    "38004": "Berufsschule",
    "38005": "Sonderschule",
    "38006": "Verwaltung Bildung",
    "38007": "Sporthalle",
    "38008": "Hallenbad",
    "38009": "Kultur-/Veranstaltungsgebäude",
    "38010": "Bibliothek",
    "38011": "Museum/Galerie",
    # Verwaltung
    "39001": "Verwaltungsgebäude",
    "39002": "Rathaus",
    "39003": "Gericht",
    "39004": "Polizei",
    "39005": "Feuerwache",
    # Landwirtschaft
    "41001": "Landwirtschaftsgebäude",
    "41002": "Stall",
    "41003": "Scheune",
    "41004": "Gewächshaus",
    "41005": "Treibhaus",
    # Verkehr
    "42001": "Bahngebäude",
    "42002": "Flughafengebäude",
    "42003": "Busbahnhof",
    "42004": "Parkhaus",
    "42005": "Tiefgarage",
    "42006": "Tankstelle",
    "42007": "Kfz-Werkstatt",
    # Nebengebäude
    "44001": "Garage",
    "44002": "Carport",
    "45001": "Nebengebäude",
    "45002": "Gartenhaus",
    "99999": "Sonstiges",
}


def _decode_lod2_funktion(raw) -> str:
    """Dekodiert ALKIS-Gebäudefunktions-Code in Klartext.
    Unterstützte Formate: "31001", "31001_2463", "31001 2463", 31001 (int)
    """
    if not raw and raw != 0: return ""
    s = str(raw).strip()
    if not s: return ""
    # Bereits Klartext (kein Digit am Anfang)
    if not s[0].isdigit(): return s
    # Code: erster Block aus Ziffern (vor _, Leerzeichen etc.)
    code = ""
    for ch in s:
        if ch.isdigit(): code += ch
        else: break
    # 5-stellig: direkt in Tabelle nachschlagen
    if len(code) == 5:
        return _LOD2_FUNKTION.get(code, f"Code {code}")
    # 4-stellig: fehlende führende Ziffer ergänzen
    if len(code) == 4:
        for prefix in ("3", "4"):
            full = prefix + code
            if full in _LOD2_FUNKTION:
                return _LOD2_FUNKTION[full]
    # Unbekannt: Rohwert
    return s

def _fetch_lod2_ogcapi(cfg: dict, bbox_wgs84: tuple, timeout=60) -> list[dict]:
    """
    LOD-2 Gebäude via Direktdownload der CityGML-Kacheln von opengeodata.nrw.de.
    Schema: LoD2_32_<RW_km>_<HW_km>_1_NW.gml (1km^2 Kacheln, UTM32)
    Workflow: Kacheln berechnen -> herunterladen -> parsen -> loeschen.
    """
    import tempfile, os as _os, math as _math
    from concurrent.futures import ThreadPoolExecutor, as_completed

    lon_min, lat_min, lon_max, lat_max = bbox_wgs84
    e_min, n_min, e_max, n_max = _wgs84_to_utm32(lon_min, lat_min, lon_max, lat_max)

    rw_start = int(_math.floor(e_min / 1000))
    rw_end   = int(_math.floor(e_max / 1000))
    hw_start = int(_math.floor(n_min / 1000))
    hw_end   = int(_math.floor(n_max / 1000))

    base_url = "https://www.opengeodata.nrw.de/produkte/geobasis/3dg/lod2_gml/lod2_gml"
    tiles = [(rw, hw)
             for rw in range(rw_start, rw_end + 1)
             for hw in range(hw_start, hw_end + 1)]

    def _fetch_tile(tile):
        rw, hw   = tile
        fname    = f"LoD2_32_{rw}_{hw}_1_NW.gml"
        url      = f"{base_url}/{fname}"
        tmp_path = _os.path.join(tempfile.gettempdir(), fname)
        try:
            r = _requests.get(url, timeout=timeout, stream=True)
            if r.status_code == 404:
                return [], ""
            if r.status_code != 200:
                return [], f"HTTP {r.status_code} fuer {fname}"
            with open(tmp_path, "wb") as fh:
                for chunk in r.iter_content(chunk_size=65536):
                    fh.write(chunk)
            return _parse_citygml_file(tmp_path), ""
        except Exception as _e:
            return [], str(_e)
        finally:
            try: _os.unlink(tmp_path)
            except: pass

    all_feats = []; seen_ids = set(); errors = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(_fetch_tile, t): t for t in tiles}
        for fut in as_completed(futures):
            tile_feats, err = fut.result()
            if err: errors.append(err)
            for feat in tile_feats:
                gid = feat["props"].get("gml_id", "")
                if gid not in seen_ids:
                    all_feats.append(feat)
                    if gid: seen_ids.add(gid)

    if not all_feats:
        raise RuntimeError(
            f"LOD-2 GML: 0 Gebaeude aus {len(tiles)} Kacheln. "
            f"Fehler: {'; '.join(errors[:3]) or 'alle Kacheln leer/404'}")
    return all_feats


def _parse_citygml_file(path: str) -> list[dict]:
    """Extrahiert Gebaeude-Grundflaechen aus einer CityGML-Datei."""
    import xml.etree.ElementTree as _ET

    BLDG = "http://www.opengis.net/citygml/building/1.0"
    GML  = "http://www.opengis.net/gml"

    try:
        tree = _ET.parse(path)
        root = tree.getroot()
    except Exception:
        return []

    feats = []
    seen  = set()
    # Building UND BuildingPart (Kloster, Schule, Altenheim etc.)
    types = [f"{{{BLDG}}}Building", f"{{{BLDG}}}BuildingPart"]
    all_bldgs = [b for t in types for b in root.iter(t)]

    for bldg in all_bldgs:
        gml_id = bldg.get(f"{{{GML}}}id", "")
        if gml_id in seen:
            continue
        seen.add(gml_id)

        h_el   = next((ch for ch in bldg if ch.tag == f"{{{BLDG}}}measuredHeight"), None)
        h      = float(h_el.text) if h_el is not None and h_el.text else 0.0
        # Nur direkte function-Kinder suchen (nicht verschachtelte BuildingParts)
        fn_el  = next((ch for ch in bldg if ch.tag == f"{{{BLDG}}}function"), None)
        fn     = fn_el.text.strip() if fn_el is not None and fn_el.text else ""
        props  = {
            "gml_id":         gml_id,
            "measuredHeight": h,
            "storeysAbove":   0,
            "function":       _decode_lod2_funktion(fn),
            "function_code":  fn,
        }

        # 1. Versuch: GroundSurface
        wkt = None
        for gs in bldg.iter(f"{{{BLDG}}}GroundSurface"):
            for pl in gs.iter(f"{{{GML}}}posList"):
                nums = (pl.text or "").split()
                step = 3 if len(nums) % 3 == 0 and len(nums) > 3 else 2
                pts  = [f"{float(nums[i]):.2f} {float(nums[i+1]):.2f}"
                        for i in range(0, len(nums) - step + 1, step)]
                if len(pts) >= 3:
                    wkt = "MULTIPOLYGON(((" + ", ".join(pts) + ")))"
                    break
            if wkt:
                break

        # 2. Fallback: niedrigste Flaeche aus allen posList
        if not wkt:
            best_z = float("inf"); best_pts = None
            for pl in bldg.iter(f"{{{GML}}}posList"):
                nums = (pl.text or "").split()
                step = 3 if len(nums) % 3 == 0 and len(nums) > 3 else 2
                if step == 2:
                    continue
                pts_3d = []
                for i in range(0, len(nums) - 2, 3):
                    try:
                        pts_3d.append((float(nums[i]), float(nums[i+1]), float(nums[i+2])))
                    except ValueError:
                        continue
                if len(pts_3d) < 3:
                    continue
                z_avg = sum(p[2] for p in pts_3d) / len(pts_3d)
                if z_avg < best_z:
                    best_z = z_avg
                    best_pts = [f"{p[0]:.2f} {p[1]:.2f}" for p in pts_3d]
            if best_pts and len(best_pts) >= 3:
                wkt = "MULTIPOLYGON(((" + ", ".join(best_pts) + ")))"


        if wkt:
            feats.append({"props": props, "wkt": wkt})
    return feats

def _parse_cityjson(cj: dict) -> list[dict]:
    """Extrahiert Gebäude-Grundflächen aus einem CityJSON-Objekt.
    Solid: semantics.values = [[sh0_su0, sh0_su1, ...], [sh1_su0, ...]]
    MultiSurface: semantics.values = [su0, su1, ...]
    """
    verts = cj.get("vertices", [])
    tf    = cj.get("transform", {})
    scale = tf.get("scale",     [1.0, 1.0, 1.0])
    trans = tf.get("translate", [0.0, 0.0, 0.0])

    # CRS aus Metadaten bestimmen
    meta = cj.get("metadata", {})
    ref_sys = meta.get("referenceSystem", "") or ""
    is_geographic = "CRS84" in ref_sys or "4326" in ref_sys or "4258" in ref_sys
    # Erster Vertex als Plausibilitätsprüfung
    if not is_geographic and verts:
        v0 = verts[0]
        x0 = v0[0] * scale[0] + trans[0]
        y0 = v0[1] * scale[1] + trans[1]
        if -180 <= x0 <= 180 and -90 <= y0 <= 90:
            is_geographic = True   # sieht nach lon/lat aus

    # Reprojektions-Funktion CRS84 → UTM32 (EPSG:25832)
    def _wgs84_to_utm32_pt(lon, lat):
        import math
        # Näherungsformel Transverse Mercator UTM Zone 32N
        lon_rad = math.radians(lon)
        lat_rad = math.radians(lat)
        lon0    = math.radians(9.0)   # Zentralmeridian Zone 32
        a = 6378137.0; f = 1/298.257223563
        b = a*(1-f); e2 = 1-(b/a)**2
        k0 = 0.9996; E0 = 500000.0; N0 = 0.0
        n  = (a-b)/(a+b)
        nu = a / math.sqrt(1-e2*math.sin(lat_rad)**2)
        dL = lon_rad - lon0
        A0 = 1 - e2/4 - 3*e2**2/64 - 5*e2**3/256
        A2 = 3/8*(e2 + e2**2/4 + 15*e2**3/128)
        A4 = 15/256*(e2**2 + 3*e2**3/4)
        A6 = 35*e2**3/3072
        M  = a*(A0*lat_rad - A2*math.sin(2*lat_rad)
               + A4*math.sin(4*lat_rad) - A6*math.sin(6*lat_rad))
        T  = math.tan(lat_rad)**2
        C  = e2/(1-e2)*math.cos(lat_rad)**2
        A  = math.cos(lat_rad)*dL
        easting  = E0 + k0*nu*(A + (1-T+C)*A**3/6
                   + (5-18*T+T**2+72*C-58*e2/(1-e2))*A**5/120)
        northing = N0 + k0*(M + nu*math.tan(lat_rad)*
                   (A**2/2 + (5-T+9*C+4*C**2)*A**4/24
                   + (61-58*T+T**2+600*C-330*e2/(1-e2))*A**6/720))
        return (easting, northing)

    def _v(i):
        v = verts[i]
        x = v[0]*scale[0]+trans[0]
        y = v[1]*scale[1]+trans[1]
        if is_geographic:
            return _wgs84_to_utm32_pt(x, y)   # lon, lat → E, N
        return (x, y)

    def _surf_type(surf_vals, surf_types, sh_idx, su_idx):
        if not surf_vals or not surf_types:
            return ""
        try:
            val = surf_vals[sh_idx]
            # Solid: val ist Liste von Indizes pro Shell
            vi = val[su_idx] if isinstance(val, list) else val
            if isinstance(vi, int) and vi < len(surf_types):
                return surf_types[vi].get("type", "")
        except (IndexError, TypeError):
            pass
        return ""

    feats = []
    for obj_id, obj in cj.get("CityObjects", {}).items():
        if obj.get("type") not in ("Building", "BuildingPart"):
            continue
        attrs = obj.get("attributes", {})
        props = {
            "gml_id":        obj_id,
            "measuredHeight": attrs.get("measuredHeight", 0) or 0,
            "storeysAbove":   attrs.get("storeysAboveGround", 0) or 0,
            "function":       _decode_lod2_funktion(attrs.get("function", "")),
            "function_code":  str(attrs.get("function", "")),
        }
        for geom in obj.get("geometry", []):
            g_type    = geom.get("type", "")
            bounds    = geom.get("boundaries", [])
            semantics = geom.get("semantics") or {}
            surf_types = semantics.get("surfaces", [])
            surf_vals  = semantics.get("values",   [])

            # Solid: bounds=[shell,...], shell=[surface,...]
            # MultiSurface: bounds=[surface,...]
            shells = bounds if g_type == "Solid" else [bounds]

            found = False
            for sh_idx, shell in enumerate(shells):
                for su_idx, surf in enumerate(shell):
                    s_type = _surf_type(surf_vals, surf_types, sh_idx, su_idx)
                    # ring: erste Koordinaten-Liste
                    ring = surf[0] if (surf and isinstance(surf[0], list)) else surf
                    if not ring:
                        continue
                    try:
                        pts = [_v(i) for i in ring]
                        wkt = "POLYGON((" +                               ", ".join(f"{p[0]:.2f} {p[1]:.2f}" for p in pts) + "))"
                        if s_type == "GroundSurface":
                            feats.append({"props": props, "wkt": wkt})
                            found = True; break
                    except Exception:
                        continue
                if found:
                    break

            # Fallback ohne Semantik: niedrigste Z-Fläche
            if not found and not surf_types:
                best_wkt = None; best_z = float("inf")
                for shell in shells:
                    for surf in shell:
                        ring = surf[0] if (surf and isinstance(surf[0], list)) else surf
                        if not ring:
                            continue
                        try:
                            z = sum(verts[i][2]*scale[2]+trans[2]
                                    for i in ring) / len(ring)
                            if z < best_z:
                                best_z = z
                                pts = [_v(i) for i in ring]
                                best_wkt = "POLYGON((" +                                     ", ".join(f"{p[0]:.2f} {p[1]:.2f}" for p in pts) + "))"
                        except Exception:
                            continue
                if best_wkt:
                    feats.append({"props": props, "wkt": best_wkt})
    return feats


# ── ATKIS Basis-DLM WFS Abruf ──────────────────────────────────────────────────

def _fetch_atkis_wfs(cfg: dict, bbox_wgs84: tuple, timeout=90) -> list[dict]:
    """ATKIS Basis-DLM WFS - adv: Typnamen, EPSG:25832."""
    import io as _io

    lon_min, lat_min, lon_max, lat_max = bbox_wgs84
    e_min, n_min, e_max, n_max = _wgs84_to_utm32(lon_min, lat_min, lon_max, lat_max)
    buf      = 50
    srsname  = cfg.get("srsname", "EPSG:25832")
    bbox_crs = f"{e_min-buf},{n_min-buf},{e_max+buf},{n_max+buf},{srsname}"
    typenames = cfg.get("typenames") or [cfg.get("typename", "")]
    ns_url    = cfg.get("ns", "http://www.adv-online.de/NAS/15/Anwendungsschema")
    ns_prefix = typenames[0].split(":")[0] if typenames else "adv"
    all_feats = []
    debug_info = []   # Sammelt Diagnosedaten

    for typename in typenames:
        ns_prefix = typename.split(":")[0]

        # WFS 2.0 mit NAMESPACES
        params = {
            "SERVICE":    "WFS",
            "VERSION":    "2.0.0",
            "REQUEST":    "GetFeature",
            "TYPENAMES":  typename,
            "BBOX":       bbox_crs,
            "NAMESPACES": f"xmlns({ns_prefix},{ns_url})",
            "COUNT":      "10000",
        }
        raw = b""
        status = 0
        try:
            r = _requests.get(cfg["url"], params=params, timeout=timeout)
            status = r.status_code
            raw    = r.content
        except Exception as _e:
            debug_info.append(f"WFS2 {typename}: Verbindungsfehler {_e}")

        if status == 200 and b"<" in raw[:200]:
            sub_cfg = dict(cfg)
            sub_cfg["typename"]      = typename
            sub_cfg["alt_localnames"] = [typename.split(":")[-1]]
            feats = _parse_wfs_gml(raw, sub_cfg)
            if feats:
                all_feats.extend(feats)
                continue
            # GML vorhanden aber 0 Features geparst → Snippet für Diagnose
            debug_info.append(
                f"WFS2 {typename}: HTTP {status}, GML: {raw[:400].decode('utf-8','replace')}")
        elif status != 200:
            pass   # WFS 2.0 nicht unterstützt → WFS 1.1 Fallback
        else:
            pass   # Keine XML-Antwort

        # Fallback WFS 1.1
        params11 = {
            "SERVICE": "WFS", "VERSION": "1.1.0", "REQUEST": "GetFeature",
            "TYPENAME": typename, "BBOX": bbox_crs, "MAXFEATURES": "10000",
        }
        raw11 = b""; status11 = 0
        try:
            r11 = _requests.get(cfg["url"], params=params11, timeout=timeout)
            status11 = r11.status_code; raw11 = r11.content
        except Exception as _e:
            debug_info.append(f"WFS1 {typename}: {_e}")
        if status11 == 200 and b"<" in raw11[:200]:
            sub_cfg = dict(cfg)
            sub_cfg["typename"]       = typename
            sub_cfg["alt_localnames"] = [typename.split(":")[-1]]
            feats = _parse_wfs_gml(raw11, sub_cfg)
            if feats:
                all_feats.extend(feats)
                continue
            debug_info.append(
                f"WFS1 {typename}: HTTP {status11}, GML: {raw11[:200].decode('utf-8','replace')}")

    # 0 Features = normales Ergebnis wenn kein Vorkommen im Gebiet
    return all_feats

# ── Centerline aus Polygon (für breite Fließgewässer ohne Mittelachse) ─────────

def _centerline_from_polygon_wkt(wkt: str, sample_dist_m: float = 75.0) -> str:
    """
    Berechnet Mittellinie via Voronoi-Skeleton + BFS-Diameter.
    Algorithmus:
      1. Randpunkte samplen
      2. Voronoi → Kanten innerhalb Polygon = Skeleton-Graph
      3. BFS-Diameter: doppelter BFS findet garantiert den längsten Pfad
         (kein Greedy der in Sackgassen läuft)
    """
    try:
        import numpy as _np
        from scipy.spatial import Voronoi as _Vor
        from collections import deque as _deque
        import re as _re

        # Koordinaten aus erstem Ring
        clean = _re.sub(r'MULTI|POLYGON|\(|\)', ' ', wkt)
        nums  = _re.findall(r'[-\d.eE+]+', clean)
        if len(nums) < 6: return ""
        coords = _np.array([(float(nums[i]), float(nums[i+1]))
                            for i in range(0, len(nums)-1, 2)])

        # Randpunkte samplen
        pts = []
        for i in range(len(coords)-1):
            p0, p1 = coords[i], coords[i+1]
            d = _np.linalg.norm(p1 - p0)
            n = max(2, int(d / sample_dist_m))
            for j in range(n):
                pts.append(p0 + (p1 - p0) * j / n)
        pts = _np.array(pts)
        if len(pts) < 4: return ""

        vor = _Vor(pts)

        def _pip(px, py, poly):
            n, inside = len(poly), False
            j = n - 1
            for i in range(n):
                xi, yi = poly[i]; xj, yj = poly[j]
                if ((yi > py) != (yj > py) and
                        px < (xj - xi) * (py - yi) / (yj - yi + 1e-12) + xi):
                    inside = not inside
                j = i
            return inside

        PREC = 1.0
        def _rnd(v): return (round(v[0]/PREC)*PREC, round(v[1]/PREC)*PREC)

        adj = {}
        for i, ridge in enumerate(vor.ridge_vertices):
            if -1 in ridge: continue
            v0 = vor.vertices[ridge[0]]
            v1 = vor.vertices[ridge[1]]
            mid = (v0 + v1) / 2
            if not _pip(mid[0], mid[1], coords): continue

            # ── Querkanten-Filter ────────────────────────────────────────
            # Eine Voronoi-Kante ist eine Querkante wenn ihre Länge
            # größer ist als 1.5× der lokalen Flussbreite.
            # Lokale Breite = 2 × Distanz Voronoi-Vertex → nächster Randpunkt
            # (das ist exakt der Einkreisradius des Voronoi-Skeletts)
            edge_len = _np.linalg.norm(v1 - v0)
            p_near = vor.points[vor.ridge_points[i][0]]
            local_radius = _np.linalg.norm(v0 - p_near)
            if local_radius > 0 and edge_len > 3.0 * (2 * local_radius):
                continue   # Querkante (>3× lokale Breite) → überspringen
            # ────────────────────────────────────────────────────────────

            k0 = _rnd(v0); k1 = _rnd(v1)
            if k0 == k1: continue
            adj.setdefault(k0, set()).add(k1)
            adj.setdefault(k1, set()).add(k0)

        # Wenn Querkanten-Filter zu aggressiv → ohne Filter wiederholen
        if not adj:
            for i, ridge in enumerate(vor.ridge_vertices):
                if -1 in ridge: continue
                v0 = vor.vertices[ridge[0]]
                v1 = vor.vertices[ridge[1]]
                mid = (v0 + v1) / 2
                if not _pip(mid[0], mid[1], coords): continue
                k0 = _rnd(v0); k1 = _rnd(v1)
                if k0 == k1: continue
                adj.setdefault(k0, set()).add(k1)
                adj.setdefault(k1, set()).add(k0)

        if not adj: return ""

        # ── Branch-Pruning ────────────────────────────────────────────────
        # Entfernt kurze Seitenäste die zu echten Verzweigungen (Grad>=3) führen.
        # Echte Endpunkte (Flussterminus) werden NICHT entfernt.
        MIN_BRANCH = max(3, int(500 / sample_dist_m))  # ~500m in Graph-Hops
        pruned = True
        while pruned:
            pruned = False
            for node in list(adj.keys()):
                if len(adj.get(node, set())) != 1:
                    continue   # kein Blatt
                # Verfolge den Ast bis zur nächsten Verzweigung oder echtem Ende
                branch = [node]
                prev = None; cur = node
                junction = None
                while True:
                    nbs = adj.get(cur, set()) - ({prev} if prev is not None else set())
                    if not nbs: break
                    if len(nbs) >= 2:   # echte Verzweigung
                        junction = cur; break
                    nxt = next(iter(nbs))
                    deg_nxt = len(adj.get(nxt, set()))
                    if deg_nxt >= 3:    # Verzweigung am Ende des Astes
                        junction = nxt; branch.append(nxt); break
                    if deg_nxt == 1:    # anderer Endpunkt → kein Ast sondern Stamm
                        break
                    branch.append(nxt); prev = cur; cur = nxt
                # Nur entfernen wenn Ast zu echter Verzweigung führt UND kurz
                if junction is not None and len(branch) <= MIN_BRANCH:
                    remove = branch[:-1] if branch[-1] == junction else branch[:-1]
                    for n in remove:
                        for nb in list(adj.get(n, set())):
                            adj.get(nb, set()).discard(n)
                        adj.pop(n, None)
                    pruned = bool(remove)

        if not adj: return ""

        # BFS-Diameter: garantiert längster Pfad (kein Greedy!)
        def _bfs_farthest(start):
            dist = {start: 0}; prev = {start: None}
            q = _deque([start]); farthest = start
            while q:
                cur = q.popleft()
                if dist[cur] > dist[farthest]: farthest = cur
                for nb in adj.get(cur, set()):
                    if nb not in dist:
                        dist[nb] = dist[cur] + 1
                        prev[nb] = cur
                        q.append(nb)
            return farthest, prev

        # 1. BFS von beliebigem Start → finde u
        start = next(iter(adj))
        u, _ = _bfs_farthest(start)
        # 2. BFS von u → finde v (entgegengesetzter Endpunkt) + Pfad
        v, prev = _bfs_farthest(u)

        # Pfad rekonstruieren
        path = []
        cur = v
        while cur is not None:
            path.append(cur)
            cur = prev[cur]

        if len(path) < 2: return ""

        # ── Post-Processing ──────────────────────────────────────────────
        import math as _math

        # 1. Winkelfilter: Richtungsumkehrungen entfernen (mehrere Durchläufe)
        MAX_ANGLE = 100   # Grad – strenger für glattere Linie
        for _ in range(10):
            if len(path) < 3: break
            new_path = [path[0]]; changed = False; i = 1
            while i < len(path) - 1:
                dx1 = path[i][0]-path[i-1][0]; dy1 = path[i][1]-path[i-1][1]
                dx2 = path[i+1][0]-path[i][0]; dy2 = path[i+1][1]-path[i][1]
                m1  = _math.sqrt(dx1**2+dy1**2)
                m2  = _math.sqrt(dx2**2+dy2**2)
                if m1*m2 > 0:
                    cos_a = max(-1.0, min(1.0, (dx1*dx2+dy1*dy2)/(m1*m2)))
                    if _math.degrees(_math.acos(cos_a)) > MAX_ANGLE:
                        changed = True; i += 1; continue
                new_path.append(path[i]); i += 1
            new_path.append(path[-1])
            path = new_path
            if not changed: break

        # 2. Chaikin-Glättung: natürliche Kurven
        for _ in range(3):
            if len(path) < 3: break
            sm = [path[0]]
            for i in range(len(path)-1):
                p0, p1 = path[i], path[i+1]
                sm.append((0.75*p0[0]+0.25*p1[0], 0.75*p0[1]+0.25*p1[1]))
                sm.append((0.25*p0[0]+0.75*p1[0], 0.25*p0[1]+0.75*p1[1]))
            sm.append(path[-1])
            path = sm

        # 3. Moving-Average: lokale Ausreißer wegmitteln (Fenster 7)
        W = 3   # Halbfenster = 3 → Fensterbreite 7
        smooth2 = []
        for i in range(len(path)):
            s = max(0, i-W); e = min(len(path), i+W+1)
            wx = [path[j][0] for j in range(s, e)]
            wy = [path[j][1] for j in range(s, e)]
            smooth2.append((sum(wx)/len(wx), sum(wy)/len(wy)))
        path = smooth2

        # 4. Ausdünnen: max. 500 Punkte
        if len(path) > 500:
            step = max(1, len(path) // 500)
            path = path[::step] + [path[-1]]

        pts_str = ", ".join(f"{x:.1f} {y:.1f}" for x, y in path)
        return f"LINESTRING({pts_str})"

    except Exception:
        return ""


def _compute_missing_centerlines(
        fliessgewaesser_feats: list,
        achse_feats: list,
        min_area_m2: float = 50000.0,
        sample_dist_m: float = 75.0) -> list:
    """
    Berechnet fehlende Gewässermittelachsen aus AX_Fliessgewaesser-Polygonen.

    Für jedes breite Fließgewässer-Polygon (area > min_area_m2) das keine
    passende Mittelachse hat, wird eine Centerline via Voronoi berechnet.

    Gibt Liste von Feature-Dicts zurück (gleich wie _fetch_atkis_wfs).
    """
    try:
        import numpy as _np
        import re as _re

        def _polygon_area(wkt):
            inner = _re.search(r"\(([^)]+)\)", wkt.replace("((", "(").replace("))", ")"))
            if not inner:
                return 0
            nums = _re.findall(r"[-\d.eE+]+", inner.group(1))
            coords = [(float(nums[i]), float(nums[i+1]))
                      for i in range(0, len(nums)-1, 2)]
            n = len(coords)
            area = abs(sum(coords[i][0] * coords[(i+1)%n][1] -
                           coords[(i+1)%n][0] * coords[i][1]
                           for i in range(n))) / 2
            return area

        # Achsen-Mittelpunkte aus WFS für Überschneidungsprüfung
        def _line_midpoints(wkt_line):
            nums = _re.findall(r"[-\d.eE+]+", wkt_line.replace("(", " ").replace(")", " "))
            coords = [(float(nums[i]), float(nums[i+1]))
                      for i in range(0, len(nums)-2, 2)
                      if i+1 < len(nums)]
            if not coords: return []
            # Mittelpunkt der Linie
            mid_idx = len(coords)//2
            return [coords[mid_idx]]

        def _pip_simple(px, py, wkt_poly):
            """Punkt-in-Polygon für WKT-String."""
            nums = _re.findall(r"[-\d.eE+]+", wkt_poly.replace("(", " ").replace(")", " "))
            poly = [(float(nums[i]), float(nums[i+1]))
                    for i in range(0, len(nums)-2, 2)
                    if i+1 < len(nums)]
            if not poly: return False
            n, inside = len(poly), False
            j = n - 1
            for i in range(n):
                xi, yi = poly[i]; xj, yj = poly[j]
                if ((yi > py) != (yj > py) and
                        px < (xj-xi)*(py-yi)/(yj-yi+1e-12)+xi):
                    inside = not inside
                j = i
            return inside

        new_feats = []
        for feat in fliessgewaesser_feats:
            wkt = feat.get("wkt", "")
            if "POLYGON" not in wkt.upper():
                continue  # Nur Polygone (breite Gewässer)
            area = _polygon_area(wkt)
            if area < min_area_m2:
                continue  # Kleines Gewässer – hat WFS-Mittelachse
            # Prüfe ob bereits eine WFS-Achse in diesem Polygon liegt
            has_axis = False
            for achse in achse_feats:
                for mx, my in _line_midpoints(achse.get("wkt", "")):
                    if _pip_simple(mx, my, wkt):
                        has_axis = True; break
                if has_axis: break
            if has_axis:
                continue   # WFS-Achse vorhanden → keine Centerline nötig
            cl_wkt = _centerline_from_polygon_wkt(wkt, sample_dist_m)
            if not cl_wkt:
                continue

            # Snap: Centerline-Endpunkte an nächste AX_Gewaesserachse anhängen
            # → nahtloser Übergang im Wechselbereich Linie↔Polygon
            nums_cl = _re.findall(r"-?\d+\.?\d*(?:[eE][+-]?\d+)?", cl_wkt)
            if "EMPTY" in cl_wkt.upper() or len(nums_cl) < 4:
                continue
            if len(nums_cl) >= 4:
                # Erste und letzte Koordinate der Centerline
                cx0, cy0 = float(nums_cl[0]), float(nums_cl[1])
                cx1, cy1 = float(nums_cl[-2]), float(nums_cl[-1])
                snap_dist = sample_dist_m * 3   # max. Snap-Radius
                for achse in achse_feats:
                    a_nums = _re.findall(r"[-\d.eE+]+", achse.get("wkt",""))
                    if len(a_nums) < 4: continue
                    # Nächster Punkt auf der Achse zu Centerline-Anfang
                    for i in range(0, len(a_nums)-1, 2):
                        ax, ay = float(a_nums[i]), float(a_nums[i+1])
                        d0 = ((ax-cx0)**2+(ay-cy0)**2)**0.5
                        d1 = ((ax-cx1)**2+(ay-cy1)**2)**0.5
                        if d0 < snap_dist:
                            # Verbindungssegment am Anfang einfügen
                            cl_wkt = cl_wkt.replace(
                                f"{cx0:.2f} {cy0:.2f}",
                                f"{ax:.2f} {ay:.2f}, {cx0:.2f} {cy0:.2f}", 1)
                            snap_dist = d0   # enger für weiteren Snap
                        if d1 < snap_dist:
                            # Verbindungssegment am Ende anhängen
                            cl_wkt = cl_wkt[:cl_wkt.rfind(f"{cx1:.2f} {cy1:.2f}")] \
                                     + f"{cx1:.2f} {cy1:.2f}, {ax:.2f} {ay:.2f})"
                            snap_dist = d1

            new_feats.append({
                "props": {
                    "gml_id":           feat["props"].get("gml_id", "") + "_cl",
                    "nam":              feat["props"].get("nam", ""),
                    "gewaesserkennzahl":feat["props"].get("gewaesserkennzahl", ""),
                    "funktion":         feat["props"].get("funktion", ""),
                    "widmung":          feat["props"].get("widmung", ""),
                    "quelle":           "AX_Fliessgewaesser-Centerline",
                },
                "wkt": cl_wkt,
            })
        return new_feats

    except Exception as _e:
        raise RuntimeError(f"_compute_missing_centerlines Fehler: {_e}")



def _fetch_atkis_wfs(cfg: dict, bbox_wgs84: tuple, timeout=90) -> list[dict]:
    """ATKIS Basis-DLM WFS - adv: Typnamen, EPSG:25832."""
    import io as _io

    lon_min, lat_min, lon_max, lat_max = bbox_wgs84
    e_min, n_min, e_max, n_max = _wgs84_to_utm32(lon_min, lat_min, lon_max, lat_max)
    buf      = 50
    srsname  = cfg.get("srsname", "EPSG:25832")
    bbox_crs = f"{e_min-buf},{n_min-buf},{e_max+buf},{n_max+buf},{srsname}"
    typenames = cfg.get("typenames") or [cfg.get("typename", "")]
    ns_url    = cfg.get("ns", "http://www.adv-online.de/NAS/15/Anwendungsschema")
    ns_prefix = typenames[0].split(":")[0] if typenames else "adv"
    all_feats = []
    debug_info = []   # Sammelt Diagnosedaten

    for typename in typenames:
        ns_prefix = typename.split(":")[0]

        # WFS 2.0 mit NAMESPACES
        params = {
            "SERVICE":    "WFS",
            "VERSION":    "2.0.0",
            "REQUEST":    "GetFeature",
            "TYPENAMES":  typename,
            "BBOX":       bbox_crs,
            "NAMESPACES": f"xmlns({ns_prefix},{ns_url})",
            "COUNT":      "10000",
        }
        raw = b""
        status = 0
        try:
            r = _requests.get(cfg["url"], params=params, timeout=timeout)
            status = r.status_code
            raw    = r.content
        except Exception as _e:
            debug_info.append(f"WFS2 {typename}: Verbindungsfehler {_e}")

        if status == 200 and b"<" in raw[:200]:
            sub_cfg = dict(cfg)
            sub_cfg["typename"]      = typename
            sub_cfg["alt_localnames"] = [typename.split(":")[-1]]
            feats = _parse_wfs_gml(raw, sub_cfg)
            if feats:
                all_feats.extend(feats)
                continue
            # GML vorhanden aber 0 Features geparst → Snippet für Diagnose
            debug_info.append(
                f"WFS2 {typename}: HTTP {status}, GML: {raw[:400].decode('utf-8','replace')}")
        elif status != 200:
            pass   # WFS 2.0 nicht unterstützt → WFS 1.1 Fallback
        else:
            pass   # Keine XML-Antwort

        # Fallback WFS 1.1
        params11 = {
            "SERVICE": "WFS", "VERSION": "1.1.0", "REQUEST": "GetFeature",
            "TYPENAME": typename, "BBOX": bbox_crs, "MAXFEATURES": "10000",
        }
        raw11 = b""; status11 = 0
        try:
            r11 = _requests.get(cfg["url"], params=params11, timeout=timeout)
            status11 = r11.status_code; raw11 = r11.content
        except Exception as _e:
            debug_info.append(f"WFS1 {typename}: {_e}")
        if status11 == 200 and b"<" in raw11[:200]:
            sub_cfg = dict(cfg)
            sub_cfg["typename"]       = typename
            sub_cfg["alt_localnames"] = [typename.split(":")[-1]]
            feats = _parse_wfs_gml(raw11, sub_cfg)
            if feats:
                all_feats.extend(feats)
                continue
            debug_info.append(
                f"WFS1 {typename}: HTTP {status11}, GML: {raw11[:200].decode('utf-8','replace')}")

    # 0 Features = normales Ergebnis wenn kein Vorkommen im Gebiet
    return all_feats

# ── Centerline aus Polygon (für breite Fließgewässer ohne Mittelachse) ─────────



def _wgs84_bbox(lon_min, lat_min, lon_max, lat_max):
    return lon_min, lat_min, lon_max, lat_max


def _wgs84_to_utm32(lon_min, lat_min, lon_max=None, lat_max=None):
    """Transformiert WGS84 nach UTM32N (EPSG:25832).
    Mit 2 Args: (lon, lat) → (e, n)
    Mit 4 Args: (lon_min, lat_min, lon_max, lat_max) → (e_min, n_min, e_max, n_max)
    """
    _single = lon_max is None   # 2-Argument-Modus
    if not _QGIS_OK:
        # Naehreungsformel ohne QGIS
        import math
        lon0 = math.radians(9.0)
        def _merc(lon, lat):
            lr = math.radians(lat)
            ll = math.radians(lon)
            e  = 0.9996 * 6378137.0
            N  = e / math.sqrt(1 - 0.00669438 * math.sin(lr)**2)
            dl = ll - lon0
            E  = 500000 + 0.9996 * N * math.cos(lr) * dl
            M  = e * (lr - 0.00251882 * math.sin(2*lr))
            return E, 0.9996 * M
        sw = _merc(lon_min, lat_min)
        if _single: return sw[0], sw[1]
        ne = _merc(lon_max, lat_max)
        return sw[0], sw[1], ne[0], ne[1]
    from qgis.core import (QgsCoordinateReferenceSystem,
                           QgsCoordinateTransform,
                           QgsCoordinateTransformContext, QgsPointXY)
    wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
    utm32 = QgsCoordinateReferenceSystem("EPSG:25832")
    tr    = QgsCoordinateTransform(wgs84, utm32,
                                   QgsCoordinateTransformContext())
    sw = tr.transform(QgsPointXY(lon_min, lat_min))
    if _single: return sw.x(), sw.y()
    ne = tr.transform(QgsPointXY(lon_max, lat_max))
    return sw.x(), sw.y(), ne.x(), ne.y()


# ── WFS-Abruf ─────────────────────────────────────────────────────────────────

def _fetch_ffh_lrt(cfg: dict, bbox_wgs84: tuple, timeout=90) -> list[dict]:
    """
    FFH-LRT Abruf:
      1. GML-ZIP (primär, zuverlässig)
      2. WFS 2.0 Fallback
      3. WFS 1.1 Fallback
    """
    import io, zipfile
    lon_min, lat_min, lon_max, lat_max = bbox_wgs84
    debug_info = []

    # ── Stufe 1: GML-ZIP ─────────────────────────────────────────────────────
    zip_url = cfg.get("zip_url", "")
    if zip_url and _REQUESTS_OK:
        shp_path = None
        try:
            r = _requests.get(zip_url, timeout=300, stream=True)
            r.raise_for_status()
            import tempfile as _tmp
            tmp = _tmp.NamedTemporaryFile(suffix=".zip", delete=False)
            tmp.write(r.content); tmp.close()
            with zipfile.ZipFile(tmp.name) as zf:
                all_shps = [n for n in zf.namelist() if n.lower().endswith(".shp")]
                for pref in ("polygon", "flaeche", "area"):
                    for n in all_shps:
                        if pref in n.lower(): shp_path = n; break
                    if shp_path: break
                if not shp_path and all_shps: shp_path = all_shps[0]
            debug_info.append(f"ZIP HTTP {r.status_code}, {len(r.content)//1024} KB, shp={shp_path}")
            if shp_path:
                from osgeo import ogr as _og2, osr as _os2
                e_min_u, n_min_u, e_max_u, n_max_u = _wgs84_to_utm32(lon_min, lat_min, lon_max, lat_max)
                ds = _og2.Open(f"/vsizip/{tmp.name}/{shp_path}")
                if ds:
                    lyr = ds.GetLayer(0)
                    lyr.SetSpatialFilterRect(e_min_u, n_min_u, e_max_u, n_max_u)
                    feats_out = []
                    for feat in lyr:
                        geom = feat.GetGeometryRef()
                        if not geom: continue
                        props = {}
                        fd = feat.GetDefnRef()
                        for i in range(fd.GetFieldCount()):
                            name = fd.GetFieldDefn(i).GetName()
                            v = feat.GetField(i)
                            if v is not None: props[name] = str(v)
                        # Feldnamen-Normalisierung (Shapefile: max 10 Zeichen)
                        # Alle Felder case-insensitiv mappen
                        _plc = {k.lower(): (k, v) for k, v in props.items()}
                        # LRT-Code: alle Feldnamen die "code" oder "lrt" enthalten
                        if "referenceHabitatTypeCode" not in props:
                            for _lc_key, (_orig, _val) in _plc.items():
                                if any(x in _lc_key for x in
                                       ("lrt_c", "lrtco", "hab_cod", "habitatco",
                                        "code", "lrt_t", "typ_nr", "typ_cod")):
                                    props["referenceHabitatTypeCode"] = _val; break
                        # LRT-Name: alle Felder die "name" oder "bezeichn" enthalten
                        if "referenceHabitatTypeName" not in props:
                            for _lc_key, (_orig, _val) in _plc.items():
                                if any(x in _lc_key for x in
                                       ("lrt_n", "lrtna", "hab_nam", "habitatna",
                                        "bezeichn", "benennu", "typ_nam")):
                                    props["referenceHabitatTypeName"] = _val; break
                        # Fallback: ersten String-Wert als Code, zweiten als Name
                        _str_fields = [(k,v) for k,v in props.items()
                                       if isinstance(v,str) and v.strip()
                                       and k not in ("quelle",)]
                        if "referenceHabitatTypeCode" not in props and _str_fields:
                            props["referenceHabitatTypeCode"] = _str_fields[0][1]
                        if "referenceHabitatTypeName" not in props and len(_str_fields) > 1:
                            props["referenceHabitatTypeName"] = _str_fields[1][1]
                        # Debug: logge was im ZIP steht
                        if not any("referenceHabitat" in k for k in props):
                            debug_info.append(f"FFH-Felder: {list(props.keys())[:8]}")
                        feats_out.append({"props": props, "wkt": geom.ExportToWkt()})
                    ds = None
                    debug_info.append(f"ZIP BBOX-Filter: {len(feats_out)} Features")
                    import os as _os; _os.unlink(tmp.name)
                    if feats_out: return feats_out
                else:
                    debug_info.append(f"ZIP: OGR konnte Shapefile nicht öffnen: /vsizip/{tmp.name}/{shp_path}")
            else:
                debug_info.append(f"ZIP: kein .shp im Archiv gefunden. Dateien: {all_shps[:5]}")
        except Exception as _e:
            debug_info.append(f"ZIP-Fehler: {_e}")
            try:
                import os as _os; _os.unlink(tmp.name)
            except: pass

    # ── Stufe 2: WFS 2.0 ─────────────────────────────────────────────────────
    candidates = cfg.get("typename_candidates", [cfg.get("typename", "")])
    for tn in candidates:
        raw = b""; status = 0
        try:
            params = {"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
                      "TYPENAMES": tn, "COUNT": "5000",
                      "BBOX": f"{lon_min},{lat_min},{lon_max},{lat_max},urn:ogc:def:crs:OGC:1.3:CRS84"}
            r = _requests.get(cfg["url"], params=params, timeout=timeout)
            status = r.status_code; raw = r.content
        except Exception as _e:
            debug_info.append(f"WFS2 {tn}: {_e}"); continue
        if status == 200 and b"<" in raw[:200]:
            sub = dict(cfg); sub["typename"] = tn
            feats = _parse_wfs_gml(raw, sub)
            if feats: return feats
            debug_info.append(f"WFS2 {tn}: HTTP {status}, GML: {raw[:200].decode('utf-8','replace')}")
        else:
            debug_info.append(f"WFS2 {tn}: HTTP {status}")

    # ── Stufe 3: WFS 1.1 ─────────────────────────────────────────────────────
    for tn in candidates:
        raw = b""; status = 0
        try:
            params = {"SERVICE": "WFS", "VERSION": "1.1.0", "REQUEST": "GetFeature",
                      "TYPENAME": tn, "MAXFEATURES": "5000",
                      "SRSNAME": "urn:ogc:def:crs:EPSG::4326",
                      "BBOX": f"{lat_min},{lon_min},{lat_max},{lon_max},urn:ogc:def:crs:EPSG::4326"}
            r = _requests.get(cfg["url"], params=params, timeout=timeout)
            status = r.status_code; raw = r.content
        except Exception as _e:
            debug_info.append(f"WFS1 {tn}: {_e}"); continue
        if status == 200 and b"<" in raw[:200]:
            sub = dict(cfg); sub["typename"] = tn
            feats = _parse_wfs_gml(raw, sub)
            if feats: return feats
            debug_info.append(f"WFS1 {tn}: HTTP {status}, GML: {raw[:300].decode('utf-8','replace')}")
        else:
            debug_info.append(f"WFS1 {tn}: HTTP {status}")

    # Alle Stufen gescheitert → Diagnose als Exception
    if debug_info:
        raise RuntimeError("FFH-LRT 0 Features: " + " | ".join(debug_info[:4]))
    return []

def _is_float(s):
    try: float(s); return True
    except ValueError: return False


def _fetch_wfs(cfg: dict, bbox_wgs84: tuple, timeout=60) -> list[dict]:
    """
    Ruft Features über WFS 2.0 GetFeature mit BBOX-Filter ab.
    Gibt Liste von {props: dict, wkt: str} zurück.
    """
    lon_min, lat_min, lon_max, lat_max = bbox_wgs84
    params = {
        "SERVICE":      "WFS",
        "VERSION":      "2.0.0",
        "REQUEST":      "GetFeature",
        "TYPENAMES":    cfg["typename"],
        "BBOX":         f"{lon_min},{lat_min},{lon_max},{lat_max},urn:ogc:def:crs:EPSG::4326",
        "OUTPUTFORMAT": "application/gml+xml; version=3.2",
        "COUNT":        "2000",
    }

    r = _requests.get(cfg["url"], params=params, timeout=timeout)
    r.raise_for_status()
    return _parse_wfs_gml(r.content, cfg)


def _parse_wfs_gml(xml_bytes: bytes, cfg: dict) -> list[dict]:
    """Parst GML-Antwort und extrahiert Features."""
    features = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        raise RuntimeError(f"GML-Parse-Fehler: {e}")

    # Namespace-Map für XPath
    ns_tag = cfg.get("typename", "").split(":")[0]
    # Alle Member-Elemente durchsuchen
    for member in root.iter():
        tag = member.tag.split("}")[-1] if "}" in member.tag else member.tag
        if tag in ("member", "featureMember", "featureMembers"):
            continue
        if "}" not in member.tag:
            continue
        # Feature-Elemente: alle bekannten Varianten des Elementnamens
        feature_localname = cfg["typename"].split(":")[-1]
        alt_names = cfg.get("alt_localnames", [])
        valid_names = {feature_localname} | set(alt_names)
        # Auch Variante ohne abschließendes "Type" prüfen
        if feature_localname.endswith("Type"):
            valid_names.add(feature_localname[:-4])
        if tag not in valid_names:
            continue

        props = {}
        geom_wkt = None

        for child in member:
            child_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

            # Geometrie extrahieren – alle bekannten Feld-Namen
            if child_tag in ("geometry", "the_geom", "geom", "shape",
                             "extent", "location", "position",
                             "geometrie", "punktGeometrie",
                             "msGeometry", "ogr_geometry"):
                wkt_candidate = _gml_to_wkt(child)
                if wkt_candidate:
                    geom_wkt = wkt_candidate
                continue
            # Fallback: Kind-Element enthält direkt GML-Geometrie?
            if geom_wkt is None:
                for gml_tag in ("MultiSurface", "Polygon", "Point",
                                "MultiPolygon", "LineString", "MultiLineString"):
                    for desc in child.iter():
                        dtag = desc.tag.split("}")[-1] if "}" in desc.tag else desc.tag
                        if dtag == gml_tag:
                            wkt_candidate = _gml_to_wkt(desc)
                            if wkt_candidate:
                                geom_wkt = wkt_candidate
                            break
                    if geom_wkt:
                        break

            # Einfache Felder extrahieren (direkter Text + verschachtelte Elemente)
            for src_name, _, _ in cfg.get("felder", []):
                if child_tag.lower() == src_name.lower() and src_name not in props:
                    txt = child.text.strip() if child.text and child.text.strip() else ""
                    if not txt:
                        txt = " ".join(
                            (e.text or "").strip() for e in child.iter()
                            if e.text and e.text.strip()
                        )
                    if txt:
                        props[src_name] = txt

            # felder_all: ALLE Attribute generisch übernehmen – direkter Text,
            # verschachtelter Text UND XML-Attribute (für Dienste mit
            # unbekanntem Schema, z. B. DVG).
            if cfg.get("felder_all"):
                if child_tag not in props:
                    _t = child.text.strip() if child.text and child.text.strip() else ""
                    if not _t:
                        _t = " ".join((e.text or "").strip() for e in child.iter()
                                      if e.text and e.text.strip())
                    if _t:
                        props[child_tag] = _t
                for _ak, _av in child.attrib.items():
                    _akl = _ak.split("}")[-1]
                    if _av and _av.strip() and _akl not in props:
                        props[_akl] = _av.strip()

            # Geschachtelte Felder (z.B. CharacterString, LocalisedCharacterString)
            for desc in child.iter():
                dtag = desc.tag.split("}")[-1] if "}" in desc.tag else desc.tag
                if dtag in ("CharacterString", "LocalisedCharacterString",
                            "localName", "codeSpace") and desc.text:
                    if child_tag not in props:
                        props[child_tag] = desc.text.strip()
                    break

        if geom_wkt:
            features.append({"props": props, "wkt": geom_wkt})

    return features



def _fetch_ogcapi(cfg: dict, bbox_wgs84: tuple, timeout=60) -> list[dict]:
    """
    Ruft Features über OGC-API Features (GeoJSON) mit bbox-Parameter ab.
    Paginierung über 'next'-Link.
    """
    lon_min, lat_min, lon_max, lat_max = bbox_wgs84
    url = cfg["url"]
    no_crs = cfg.get("no_crs_params", False)
    params = {
        "bbox":  f"{lon_min},{lat_min},{lon_max},{lat_max}",
        "f":     "json",
        "limit": 500,
    }
    if not no_crs:
        params["bbox-crs"] = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
        params["crs"]      = "http://www.opengis.net/def/crs/EPSG/0/25832"

    features = []
    while url:
        r = _requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        for feat in data.get("features", []):
            props = feat.get("properties", {})
            geom  = feat.get("geometry")
            wkt   = _geojson_geom_to_wkt(geom)
            if wkt:
                features.append({"props": props, "wkt": wkt})

        # Paginierung
        url    = None
        params = {}   # Nur für erste Anfrage
        for link in data.get("links", []):
            if link.get("rel") == "next":
                url = link.get("href")
                break

    return features



def _lod2_tiles(e_min, n_min, e_max, n_max):
    """Gibt Liste von (e_km, n_km)-Kacheln für das Gebiet zurück."""
    e0 = int(e_min / LOD2_TILE_M) * LOD2_TILE_M
    n0 = int(n_min / LOD2_TILE_M) * LOD2_TILE_M
    tiles = []
    e = e0
    while e < e_max:
        n = n0
        while n < n_max:
            tiles.append((int(e / 1000), int(n / 1000)))
            n += LOD2_TILE_M
        e += LOD2_TILE_M
    return tiles


def _lod2_kachel_url(e_km, n_km):
    """Download-URL für eine LOD-2-Kachel (NRW OpenGeoData)."""
    return (f"https://www.opengeodata.nrw.de/produkte/geobasis/3dg/lod2/"
            f"lod2_{e_km}_{n_km}_1_nw.gml.gz")


def _safe_float(s):
    try: return float(s)
    except: return None


def _fetch_lod2(cfg, bbox_wgs84, out_gpkg, worker=None):
    """
    Lädt LOD-2 CityGML-Kacheln und extrahiert Gebäudegrundflächen.
    Gibt Anzahl extrahierter Gebäude zurück.
    """
    import gzip as _gz
    import xml.etree.ElementTree as _ET

    def _log(msg):
        if worker: worker.progress.emit(-1, f"  [LOD-2] {msg}")

    if not _REQUESTS_OK:
        _log("requests fehlt")
        return 0

    lon_min, lat_min, lon_max, lat_max = bbox_wgs84
    e_min, n_min, e_max, n_max = _wgs84_to_utm32(lon_min, lat_min, lon_max, lat_max)
    tiles = _lod2_tiles(e_min, n_min, e_max, n_max)
    _log(f"{len(tiles)} Kachel(n)")

    try:
        from osgeo import ogr as _og, osr as _os
    except ImportError:
        _log("GDAL fehlt"); return 0

    drv = _og.GetDriverByName("GPKG")
    ds  = _og.Open(out_gpkg, 1) if os.path.exists(out_gpkg)           else drv.CreateDataSource(out_gpkg)
    sr  = _os.SpatialReference(); sr.ImportFromEPSG(25832)

    lyr_name = "lod2_gebaeude"
    lyr = ds.GetLayerByName(lyr_name)
    if lyr is None:
        lyr = ds.CreateLayer(lyr_name, sr, _og.wkbMultiPolygon)
        for fname, _ftype, _falias in cfg.get("felder", []):
            lyr.CreateField(_og.FieldDefn(fname, _og.OFTString
                            if "str" in str(_ftype).lower() else _og.OFTReal))

    NS_BLDG = "http://www.opengis.net/citygml/building/2.0"
    NS_GML  = "http://www.opengis.net/gml"

    n_total = 0
    for i, (e_km, n_km) in enumerate(tiles):
        url = _lod2_kachel_url(e_km, n_km)
        _log(f"Kachel {i+1}/{len(tiles)}: {e_km}_{n_km}")
        try:
            resp = _requests.get(url, timeout=60)
            if resp.status_code == 404:
                _log(f"  leer"); continue
            resp.raise_for_status()
            raw  = _gz.decompress(resp.content)
            root = _ET.fromstring(raw)

            for bldg in root.iter(f"{{{NS_BLDG}}}Building"):
                gml_id  = bldg.get(f"{{{NS_GML}}}id", "")
                h_grund = h_traufe = h_first = None

                # Geländehöhe / Firsthöhe
                for hm in bldg.findall(f".//{{{NS_BLDG}}}measuredHeight"):
                    h_first = _safe_float(hm.text)

                # GroundSurface → Grundfläche
                gs_polys = []
                for ps in bldg.findall(
                        f".//{{{NS_BLDG}}}groundSurface//{{{NS_GML}}}posList"):
                    raw_c = ps.text.strip().split()
                    coords = [(float(raw_c[j]), float(raw_c[j+1]), float(raw_c[j+2]))
                              for j in range(0, len(raw_c)-2, 3)]
                    if len(coords) < 3: continue
                    if h_grund is None: h_grund = coords[0][2]
                    ring = _og.Geometry(_og.wkbLinearRing)
                    for e_, n_, z_ in coords: ring.AddPoint(e_, n_, z_)
                    ring.CloseRings()
                    poly = _og.Geometry(_og.wkbPolygon); poly.AddGeometry(ring)
                    gs_polys.append(poly)

                if not gs_polys: continue
                mp = _og.Geometry(_og.wkbMultiPolygon)
                for p in gs_polys: mp.AddGeometry(p)

                feat = _og.Feature(lyr.GetLayerDefn())
                feat.SetGeometry(mp)
                feat.SetField("gml_id",       gml_id)
                feat.SetField("hoehe_grund",  h_grund  or 0.0)
                feat.SetField("hoehe_traufe", h_traufe or 0.0)
                feat.SetField("hoehe_first",  h_first  or 0.0)
                lyr.CreateFeature(feat)
                n_total += 1

        except Exception as _e:
            _log(f"Fehler: {_e}")

    ds.FlushCache(); ds = None
    _log(f"✓ {n_total} Gebäude → {out_gpkg}")
    return n_total



def _fetch_atkis_wfs(cfg: dict, bbox_wgs84: tuple, timeout=90) -> list[dict]:
    """ATKIS Basis-DLM WFS - adv: Typnamen, EPSG:25832."""
    import io as _io

    lon_min, lat_min, lon_max, lat_max = bbox_wgs84
    e_min, n_min, e_max, n_max = _wgs84_to_utm32(lon_min, lat_min, lon_max, lat_max)
    buf      = 50
    srsname  = cfg.get("srsname", "EPSG:25832")
    bbox_crs = f"{e_min-buf},{n_min-buf},{e_max+buf},{n_max+buf},{srsname}"
    typenames = cfg.get("typenames") or [cfg.get("typename", "")]
    ns_url    = cfg.get("ns", "http://www.adv-online.de/NAS/15/Anwendungsschema")
    ns_prefix = typenames[0].split(":")[0] if typenames else "adv"
    all_feats = []
    debug_info = []   # Sammelt Diagnosedaten

    for typename in typenames:
        ns_prefix = typename.split(":")[0]

        # WFS 2.0 mit NAMESPACES
        params = {
            "SERVICE":    "WFS",
            "VERSION":    "2.0.0",
            "REQUEST":    "GetFeature",
            "TYPENAMES":  typename,
            "BBOX":       bbox_crs,
            "NAMESPACES": f"xmlns({ns_prefix},{ns_url})",
            "COUNT":      "10000",
        }
        raw = b""
        status = 0
        try:
            r = _requests.get(cfg["url"], params=params, timeout=timeout)
            status = r.status_code
            raw    = r.content
        except Exception as _e:
            debug_info.append(f"WFS2 {typename}: Verbindungsfehler {_e}")

        if status == 200 and b"<" in raw[:200]:
            sub_cfg = dict(cfg)
            sub_cfg["typename"]      = typename
            sub_cfg["alt_localnames"] = [typename.split(":")[-1]]
            feats = _parse_wfs_gml(raw, sub_cfg)
            if feats:
                all_feats.extend(feats)
                continue
            # GML vorhanden aber 0 Features geparst → Snippet für Diagnose
            debug_info.append(
                f"WFS2 {typename}: HTTP {status}, GML: {raw[:400].decode('utf-8','replace')}")
        elif status != 200:
            pass   # WFS 2.0 nicht unterstützt → WFS 1.1 Fallback
        else:
            pass   # Keine XML-Antwort

        # Fallback WFS 1.1
        params11 = {
            "SERVICE": "WFS", "VERSION": "1.1.0", "REQUEST": "GetFeature",
            "TYPENAME": typename, "BBOX": bbox_crs, "MAXFEATURES": "10000",
        }
        raw11 = b""; status11 = 0
        try:
            r11 = _requests.get(cfg["url"], params=params11, timeout=timeout)
            status11 = r11.status_code; raw11 = r11.content
        except Exception as _e:
            debug_info.append(f"WFS1 {typename}: {_e}")
        if status11 == 200 and b"<" in raw11[:200]:
            sub_cfg = dict(cfg)
            sub_cfg["typename"]       = typename
            sub_cfg["alt_localnames"] = [typename.split(":")[-1]]
            feats = _parse_wfs_gml(raw11, sub_cfg)
            if feats:
                all_feats.extend(feats)
                continue
            debug_info.append(
                f"WFS1 {typename}: HTTP {status11}, GML: {raw11[:200].decode('utf-8','replace')}")

    # 0 Features = normales Ergebnis wenn kein Vorkommen im Gebiet
    return all_feats

# ── Centerline aus Polygon (für breite Fließgewässer ohne Mittelachse) ─────────



def _fetch_atkis_wfs(cfg: dict, bbox_wgs84: tuple, timeout=90) -> list[dict]:
    """ATKIS Basis-DLM WFS - adv: Typnamen, EPSG:25832."""
    import io as _io

    lon_min, lat_min, lon_max, lat_max = bbox_wgs84
    e_min, n_min, e_max, n_max = _wgs84_to_utm32(lon_min, lat_min, lon_max, lat_max)
    buf      = 50
    srsname  = cfg.get("srsname", "EPSG:25832")
    bbox_crs = f"{e_min-buf},{n_min-buf},{e_max+buf},{n_max+buf},{srsname}"
    typenames = cfg.get("typenames") or [cfg.get("typename", "")]
    ns_url    = cfg.get("ns", "http://www.adv-online.de/NAS/15/Anwendungsschema")
    ns_prefix = typenames[0].split(":")[0] if typenames else "adv"
    all_feats = []
    debug_info = []   # Sammelt Diagnosedaten

    for typename in typenames:
        ns_prefix = typename.split(":")[0]

        # WFS 2.0 mit NAMESPACES
        params = {
            "SERVICE":    "WFS",
            "VERSION":    "2.0.0",
            "REQUEST":    "GetFeature",
            "TYPENAMES":  typename,
            "BBOX":       bbox_crs,
            "NAMESPACES": f"xmlns({ns_prefix},{ns_url})",
            "COUNT":      "10000",
        }
        raw = b""
        status = 0
        try:
            r = _requests.get(cfg["url"], params=params, timeout=timeout)
            status = r.status_code
            raw    = r.content
        except Exception as _e:
            debug_info.append(f"WFS2 {typename}: Verbindungsfehler {_e}")

        if status == 200 and b"<" in raw[:200]:
            sub_cfg = dict(cfg)
            sub_cfg["typename"]      = typename
            sub_cfg["alt_localnames"] = [typename.split(":")[-1]]
            feats = _parse_wfs_gml(raw, sub_cfg)
            if feats:
                all_feats.extend(feats)
                continue
            # GML vorhanden aber 0 Features geparst → Snippet für Diagnose
            debug_info.append(
                f"WFS2 {typename}: HTTP {status}, GML: {raw[:400].decode('utf-8','replace')}")
        elif status != 200:
            pass   # WFS 2.0 nicht unterstützt → WFS 1.1 Fallback
        else:
            pass   # Keine XML-Antwort

        # Fallback WFS 1.1
        params11 = {
            "SERVICE": "WFS", "VERSION": "1.1.0", "REQUEST": "GetFeature",
            "TYPENAME": typename, "BBOX": bbox_crs, "MAXFEATURES": "10000",
        }
        raw11 = b""; status11 = 0
        try:
            r11 = _requests.get(cfg["url"], params=params11, timeout=timeout)
            status11 = r11.status_code; raw11 = r11.content
        except Exception as _e:
            debug_info.append(f"WFS1 {typename}: {_e}")
        if status11 == 200 and b"<" in raw11[:200]:
            sub_cfg = dict(cfg)
            sub_cfg["typename"]       = typename
            sub_cfg["alt_localnames"] = [typename.split(":")[-1]]
            feats = _parse_wfs_gml(raw11, sub_cfg)
            if feats:
                all_feats.extend(feats)
                continue
            debug_info.append(
                f"WFS1 {typename}: HTTP {status11}, GML: {raw11[:200].decode('utf-8','replace')}")

    # 0 Features = normales Ergebnis wenn kein Vorkommen im Gebiet
    return all_feats

# ── Centerline aus Polygon (für breite Fließgewässer ohne Mittelachse) ─────────



def _fetch_dvg_geojson(cfg: dict, bbox_wgs84: tuple, timeout=90) -> list[dict]:
    """
    DVG-Verwaltungsgrenzen über WFS 2.0 GetFeature mit OUTPUTFORMAT=GeoJSON.
    GeoJSON liefert die Attribute zuverlässig (anders als das GML-Parsing) –
    die Properties werden 1:1 als props übernommen. Geometrie in EPSG:25832.
    """
    lon_min, lat_min, lon_max, lat_max = bbox_wgs84
    e_min, n_min, e_max, n_max = _wgs84_to_utm32(lon_min, lat_min, lon_max, lat_max)
    buf       = 50
    srsname   = cfg.get("srsname", "EPSG:25832")
    bbox_crs  = f"{e_min-buf},{n_min-buf},{e_max+buf},{n_max+buf},{srsname}"
    typenames = cfg.get("typenames") or [cfg.get("typename", "")]
    out = []
    for typename in typenames:
        data = None
        for out_fmt in ("application/json; subtype=geojson", "application/json"):
            params = {
                "SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
                "TYPENAMES": typename, "SRSNAME": srsname, "BBOX": bbox_crs,
                "OUTPUTFORMAT": out_fmt, "COUNT": "10000",
            }
            try:
                r = _requests.get(cfg["url"], params=params, timeout=timeout)
                r.raise_for_status()
                data = r.json()
                break
            except Exception:
                data = None
        if not data:
            continue
        for feat in data.get("features", []):
            wkt = _geojson_geom_to_wkt(feat.get("geometry"))
            if wkt:
                out.append({"props": feat.get("properties", {}) or {}, "wkt": wkt})
    return out
