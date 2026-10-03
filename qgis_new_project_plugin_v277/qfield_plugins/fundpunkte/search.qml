/**
 * search.qml – Fundpunkte Tierarten Suche v3 (Hintergrundthread)
 * Korrekt: LayerUtils.createFeatureIteratorFromExpression + it.close()
 */
import QtQuick
import org.qfield

Item {
    signal prepareResult(var details)
    signal fetchResultsEnded()

    function fetchResults(searchString, context, parameters) {
        var layers = qgisProject.mapLayersByName("Arten")
        if (layers.length === 0) { fetchResultsEnded(); return }

        var layer = layers[0]
        var term  = searchString.toLowerCase().trim()
        var count = 0

        try {
            var expression = "\"parentid\" != 'nan'"
            if (term.length > 0) {
                expression += " AND (lower(\"term\") LIKE '%" + term + "%'"
                           +  " OR lower(\"Name_deutsch\") LIKE '%" + term + "%')"
            }

            var it = LayerUtils.createFeatureIteratorFromExpression(layer, expression)
            while (it.hasNext() && count < 50) {
                var feat    = it.next()
                var wiss    = feat.attribute("term")         || ""
                var de      = feat.attribute("Name_deutsch") || ""
                var eid     = String(feat.attribute("entityid") || "")
                var pid     = String(feat.attribute("parentid") || "")
                var display = de || wiss

                var score = 0.5
                if (de.toLowerCase().indexOf(term) === 0)   score = 1.0
                else if (wiss.toLowerCase().indexOf(term) === 0) score = 0.85

                prepareResult({
                    "displayString": display,
                    "description":   de ? wiss : "",
                    "score":         score,
                    "group":         "Fundpunkte Tiere",
                    "groupScore":    1,
                    "userData": {
                        "entityid":     eid,
                        "term":         wiss,
                        "Name_deutsch": de,
                        "parentid":     pid
                    }
                })
                count++
            }
            it.close()   // CRITICAL
        } catch(e) {}
        fetchResultsEnded()
    }
}
