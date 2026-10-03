/**
 * panel.qml – Fundpunkte Tierarten Panel (v1.86)
 */
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.qfield
import org.qgis
import Theme

Rectangle {
    id: panelFrame
    anchors.fill: parent
    color: "#CC000000"

    signal closed()

    property var  allGruppen:      []
    property var  allSpecies:      []
    property var  filteredSpecies: []
    property string activeGruppeId:   ""
    property string activeGruppeName: "Alle Gruppen"
    property bool   gruppenVisible:   false

    MouseArea { anchors.fill: parent; onClicked: panelFrame.closed() }

    // Artenlisten-Fenster
    Rectangle {
        visible: !panelFrame.gruppenVisible
        anchors.centerIn: parent
        width:  Math.min(520, parent.width  - 32)
        height: Math.min(660, parent.height - 80)
        color: Theme.mainBackgroundColor; radius: 10
        border.color: Theme.mainColor; border.width: 1; clip: true
        MouseArea { anchors.fill: parent; onClicked: {} }

        ColumnLayout {
            anchors { fill: parent; margins: 12 }; spacing: 8

            RowLayout {
                Layout.fillWidth: true
                Text { text: "Tierart wählen"; font.pixelSize: 18; font.weight: Font.Medium; color: Theme.mainTextColor; Layout.fillWidth: true }
                Button { text: "✕"; flat: true; padding: 6; onClicked: panelFrame.closed()
                    contentItem: Text { text: parent.text; font.pixelSize: 18; color: Theme.mainTextColor; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter } }
            }

            TextField {
                id: searchField; Layout.fillWidth: true
                placeholderText: "Wissenschaftlich / Deutsch …"; font.pixelSize: 15
                onTextChanged: filterLocal(text)
                Component.onCompleted: forceActiveFocus()
                background: Rectangle { color: Theme.controlBackgroundColor; border.color: Theme.mainColor; border.width: searchField.activeFocus ? 2 : 1; radius: 6 }
            }

            RowLayout {
                Layout.fillWidth: true; spacing: 6
                Text { text: "Gruppe: " + panelFrame.activeGruppeName; font.pixelSize: 12; color: Theme.mainTextColor; Layout.fillWidth: true; elide: Text.ElideRight }
                Button { text: "Wählen"; font.pixelSize: 11; padding: 6; onClicked: panelFrame.gruppenVisible = true
                    background: Rectangle { color: Theme.mainColor; radius: 12 }
                    contentItem: Text { text: parent.text; color: "white"; font: parent.font; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter } }
                Button { visible: panelFrame.activeGruppeId !== ""; text: "✕"; flat: true; padding: 4
                    onClicked: { panelFrame.activeGruppeId = ""; panelFrame.activeGruppeName = "Alle Gruppen"; filterLocal(searchField.text) }
                    contentItem: Text { text: parent.text; color: Theme.errorColor; font: parent.font } }
            }

            Text { text: panelFrame.filteredSpecies.length + " Arten"; font.pixelSize: 11; color: Theme.secondaryTextColor; Layout.alignment: Qt.AlignRight }

            ListView {
                id: list; Layout.fillWidth: true; Layout.fillHeight: true
                model: panelFrame.filteredSpecies; clip: true
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                delegate: ItemDelegate {
                    width: list.width; height: 52
                    onClicked: { setSpecies(modelData); panelFrame.closed() }
                    ColumnLayout {
                        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: 10; rightMargin: 10 }; spacing: 1
                        Text { text: modelData.Name_deutsch || modelData.term; font.pixelSize: 14; font.weight: Font.Medium; color: Theme.mainTextColor; Layout.fillWidth: true; elide: Text.ElideRight }
                        Text { text: modelData.term; font.pixelSize: 11; font.italic: true; color: Theme.secondaryTextColor; Layout.fillWidth: true; elide: Text.ElideRight }
                    }
                    Rectangle { anchors { left: parent.left; right: parent.right; bottom: parent.bottom }; height: 1; color: Theme.controlBorderColor; opacity: 0.3 }
                }
                Text { anchors.centerIn: parent; visible: list.count === 0; text: panelFrame.allSpecies.length === 0 ? "Lade …" : "Keine Treffer"; color: Theme.secondaryTextColor; font.pixelSize: 13 }
            }
        }
    }

    // Gruppen-Fenster
    Rectangle {
        visible: panelFrame.gruppenVisible
        anchors.centerIn: parent
        width:  Math.min(400, parent.width  - 32)
        height: Math.min(540, parent.height - 80)
        color: Theme.mainBackgroundColor; radius: 10
        border.color: Theme.mainColor; border.width: 1; clip: true
        MouseArea { anchors.fill: parent; onClicked: {} }

        ColumnLayout {
            anchors { fill: parent; margins: 12 }; spacing: 0
            RowLayout {
                Layout.fillWidth: true
                Text { text: "Artengruppe"; font.pixelSize: 18; font.weight: Font.Medium; color: Theme.mainTextColor; Layout.fillWidth: true }
                Button { text: "✕"; flat: true; padding: 6; onClicked: panelFrame.gruppenVisible = false
                    contentItem: Text { text: parent.text; font.pixelSize: 18; color: Theme.mainTextColor; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter } }
            }
            ItemDelegate {
                Layout.fillWidth: true; height: 44
                onClicked: { panelFrame.activeGruppeId = ""; panelFrame.activeGruppeName = "Alle Gruppen"; filterLocal(""); panelFrame.gruppenVisible = false }
                Text { anchors { left: parent.left; leftMargin: 12; verticalCenter: parent.verticalCenter }; text: "★  Alle Gruppen"; font.pixelSize: 14; font.weight: Font.Medium; color: panelFrame.activeGruppeId === "" ? Theme.mainColor : Theme.mainTextColor }
            }
            ListView {
                Layout.fillWidth: true; Layout.fillHeight: true; clip: true; model: panelFrame.allGruppen
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                delegate: ItemDelegate {
                    width: ListView.view.width; height: 44; highlighted: panelFrame.activeGruppeId === modelData.listitemid
                    onClicked: { panelFrame.activeGruppeId = modelData.listitemid; panelFrame.activeGruppeName = modelData.term; filterLocal(""); panelFrame.gruppenVisible = false }
                    property int anz: panelFrame.allSpecies.filter(function(s){ return s.parentid === modelData.listitemid }).length
                    RowLayout { anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: 12; rightMargin: 10 }
                        Text { text: modelData.term; font.pixelSize: 13; color: parent.parent.highlighted ? Theme.mainColor : Theme.mainTextColor; Layout.fillWidth: true; elide: Text.ElideRight }
                        Text { text: anz + " Arten"; font.pixelSize: 11; color: Theme.secondaryTextColor }
                    }
                    Rectangle { anchors { left: parent.left; right: parent.right; bottom: parent.bottom }; height: 1; color: Theme.controlBorderColor; opacity: 0.3 }
                }
            }
        }
    }

    function filterLocal(term) {
        var t = term.toLowerCase().trim(), gp = panelFrame.activeGruppeId
        panelFrame.filteredSpecies = panelFrame.allSpecies.filter(function(sp) {
            if (gp && sp.parentid !== gp) return false
            if (!t) return true
            var az = (sp.anzeigename || (sp.Name_deutsch ? sp.Name_deutsch + " " + sp.term : sp.term)).toLowerCase()
            return az.indexOf(t) >= 0
        })
    }

    function setSpecies(sp) {
        var drawer = iface.findItemByObjectName("overlayFeatureFormDrawer")
        if (drawer && drawer.featureModel) {
            try {
                var feat = drawer.featureModel.feature, fields = feat.fields
                var setF = function(n,v){ var i=fields.indexOf(n); if(i>=0) feat.setAttribute(i,v) }
                setF("Artname", sp.entityid); setF("Artname_deutsch", sp.Name_deutsch)
                setF("Artname_wiss", sp.term); setF("Artengruppe", sp.parentid)
                drawer.featureModel.feature = feat
                iface.mainWindow().displayToast("✓ " + (sp.Name_deutsch || sp.term))
            } catch(e) { iface.mainWindow().displayToast("Fehler: " + e) }
        } else { iface.mainWindow().displayToast("Kein Formular offen") }
    }
}
