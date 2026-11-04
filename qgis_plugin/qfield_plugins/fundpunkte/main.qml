pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import org.qfield
import org.qgis
import Theme

Item {
    id: plugin
    objectName: "fundArtenAliasSearch"

    property string targetLayerName: "Fund"
    property string targetFieldName: "Artname"
    property string speciesLayerName: "Arten"
    property string synonymLayerName: "Arten_Synonyme"
    property string speciesIdField: "entityid"
    property string speciesDisplayField: "anzeigename"
    property string synonymTermField: "synonym_term"
    property string synonymRefField: "akzeptiert_entityid"

    property int maximumResults: 100
    property var idToDisplay: ({})
    property var idToValue: ({})
    property var idToAliases: ({})
    property var displayNormToAliases: ({})
    property var displayNormToSpeciesId: ({})
    property var speciesEntries: []
    property bool indexReady: false
    property var activeEditorLoader: null
    property string currentSpeciesId: ""
    property string targetFieldEditorLoaderObjectName: "attributeEditorLoaderArtname"
    property var loaderContexts: []
    property var hookedButtons: []
    property var hookedPopups: []
    property var suppressedNativePopups: []
    property var contextualEntriesCache: []
    property var contextualCacheLoader: null
    property var contextualCacheModel: null
    property bool contextualCacheReady: false
    property bool refreshHooksScheduled: false
    property bool resultsUpdateScheduled: false
    property var mainWindowContent: null
    property var overlayDrawerObserved: null
    property var overlayFeatureFormObserved: null
    property var observedLoaders: []
    property var reopenForm: null
    property var reopenDrawer: null
    property var reopenNavigationBar: null
    property var reopenButton: null
    property bool pendingReopen: false
    property var pendingReopenLayer: null
    property var pendingReopenDrawer: null
    property var pendingReopenToolbar: null
    property bool pendingReopenConfirmed: false
    property int reopenGeneration: 0

    Component.onCompleted: {
        plugin.updateObservedUiTargets();
        plugin.requestRefreshLoaderHooks();
    }

    Component.onDestruction: {
        if (plugin.reopenButton && plugin.reopenButton.pluginRef === plugin) {
            plugin.reopenButton.enabled = false;
            plugin.reopenButton.destroy();
        }
    }

    Connections {
        target: plugin.reopenButton

        function onClicked() {
            plugin.saveAndReopen();
        }
    }

    Connections {
        target: iface

        function onLoadProjectEnded() {
            plugin.rebuildIndex();
            plugin.updateObservedUiTargets();
            plugin.requestRefreshLoaderHooks();
        }
    }

    Connections {
        target: plugin.mainWindowContent

        function onChildrenChanged() {
            plugin.updateObservedUiTargets();
            plugin.requestRefreshLoaderHooks();
        }
    }

    Connections {
        target: plugin.overlayDrawerObserved

        function onChildrenChanged() {
            plugin.updateObservedUiTargets();
            plugin.requestRefreshLoaderHooks();
        }

        function onFeatureFormChanged() {
            plugin.updateObservedUiTargets();
            plugin.requestRefreshLoaderHooks();
        }

        function onVisibleChanged() {
            plugin.requestRefreshLoaderHooks();
        }
    }

    Connections {
        target: plugin.overlayFeatureFormObserved

        function onChildrenChanged() {
            plugin.requestRefreshLoaderHooks();
        }
    }

    Connections {
        target: plugin.reopenForm
        ignoreUnknownSignals: true

        function onConfirmed() {
            if (plugin.pendingReopen && plugin.pendingReopenDrawer
                && plugin.reopenForm === plugin.pendingReopenDrawer.featureForm)
                plugin.pendingReopenConfirmed = true;
        }

        function onCancelled() {
            plugin.clearPendingReopen();
        }
    }

    Connections {
        target: plugin.reopenDrawer

        function onClosed() {
            plugin.scheduleReopenAfterClose();
        }
    }

    function logWarn(message) {
        iface.logMessage("[FundArtenAliasSearch][WARN] " + message);
    }

    function showMessage(message) {
        const mainWindow = iface.mainWindow();
        if (mainWindow && mainWindow.displayToast)
            mainWindow.displayToast(message);
        else
            iface.logMessage("[FundArtenAliasSearch] " + message);
    }

    function installReopenButton() {
        reopenDrawer = iface.findItemByObjectName("overlayFeatureFormDrawer");
        const form = reopenDrawer ? reopenDrawer.featureForm : null;
        let bar = null;
        try {
            if (form && form.header && form.header.objectName === "toolbar")
                bar = form.header;
        } catch (error) {}
        if (!bar)
            bar = findDescendantByObjectName(form, "toolbar", 0);
        if (!bar || !form)
            return;

        reopenForm = form;
        if (reopenButton && reopenNavigationBar === bar && reopenButton.pluginRef === plugin)
            return;

        const buttonCode = ''
            + 'import org.qfield\n'
            + 'import org.qgis\n'
            + 'import Theme\n'
            + 'QfToolButton {\n'
            + '  objectName: "fundArtenAliasSearchReopenButton"\n'
            + '  property var pluginRef\n'
            + '  property bool hardValid: !!(pluginRef && pluginRef.reopenForm && pluginRef.reopenForm.model && pluginRef.reopenForm.model.constraintsHardValid)\n'
            + '  property bool softValid: !!(pluginRef && pluginRef.reopenForm && pluginRef.reopenForm.model && pluginRef.reopenForm.model.constraintsSoftValid)\n'
            + '  property bool hasConstraints: !!(pluginRef && pluginRef.reopenForm && pluginRef.reopenForm.model && pluginRef.reopenForm.model.hasConstraints)\n'
            + '  property bool additionLocked: !!(pluginRef && pluginRef.reopenForm && pluginRef.reopenForm.model && pluginRef.reopenForm.model.featureModel && pluginRef.reopenForm.model.featureModel.featureAdditionLocked)\n'
            + '  anchors.top: parent.top\n'
            + '  anchors.topMargin: 10\n'
            + '  width: 48\n'
            + '  height: 48\n'
            + '  z: 10\n'
            + '  round: true\n'
            + '  roundborder: true\n'
            + '  clip: true\n'
            + '  iconSource: Theme.getThemeVectorIcon("ic_add_white_24dp")\n'
            + '  iconColor: additionLocked || !hardValid ? Theme.mainOverlayColor : Theme.mainTextColor\n'
            + '  bgcolor: additionLocked || !hardValid ? Theme.errorColor : !softValid ? Theme.warningColor : hasConstraints ? Theme.goodColor : "transparent"\n'
            + '  borderColor: Theme.mainBackgroundColor\n'
            + '  visible: pluginRef && pluginRef.reopenForm && pluginRef.reopenForm.state === "Add" && pluginRef.reopenForm.model.featureModel.currentLayer && pluginRef.reopenForm.model.featureModel.currentLayer.name === pluginRef.targetLayerName\n'
            + '  x: 52\n'
            + '}';
        try {
            if (reopenButton) {
                reopenButton.enabled = false;
                reopenButton.visible = false;
                reopenButton.objectName = "fundArtenAliasSearchRetiredReopenButton";
                reopenButton.destroy();
                reopenButton = null;
            }
            const children = Array.from(bar.children);
            for (let index = 0; index < children.length; index++) {
                const child = children[index];
                if (child.objectName !== "fundArtenAliasSearchReopenButton")
                    continue;
                child.enabled = false;
                child.visible = false;
                child.objectName = "fundArtenAliasSearchRetiredReopenButton";
                child.destroy();
            }
            reopenButton = Qt.createQmlObject(buttonCode, bar, "FundArtenAliasSearchReopenButton");
            reopenButton.pluginRef = plugin;
            reopenNavigationBar = bar;
        } catch (error) {
            reopenButton = null;
            logWarn("Failed to install save-and-reopen button: " + error);
        }
    }

    function clearPendingReopen() {
        pendingReopen = false;
        pendingReopenConfirmed = false;
        pendingReopenLayer = null;
        pendingReopenDrawer = null;
        pendingReopenToolbar = null;
        reopenGeneration++;
    }

    function canStartNativePoint(drawer, toolbar, layer) {
        return !!(drawer && toolbar && layer && layer.name === targetLayerName
            && drawer.featureModel.currentLayer === layer
            && !drawer.featureModel.featureAdditionLocked
            && !toolbar.geometryRequested && toolbar.rubberbandModel
            && toolbar.rubberbandModel.vectorLayer === layer
            && toolbar.rubberbandModel.geometryType === Qgis.GeometryType.Point
            && typeof toolbar.triggerAddVertex === "function");
    }

    function saveAndReopen() {
        if (pendingReopenConfirmed)
            return;
        clearPendingReopen();
        const form = reopenForm;
        const drawer = reopenDrawer;
        try {
            if (!form || !isEditableTargetForm(form) || form.state !== "Add"
                || !drawer || drawer.featureForm !== form)
                return;
            const layer = form.model.featureModel.currentLayer;
            const toolbar = drawer.digitizingToolbar;
            if (!canStartNativePoint(drawer, toolbar, layer)) {
                showMessage("QFields native Punkterfassung ist derzeit nicht verfuegbar.");
                return;
            }
            pendingReopenLayer = layer;
            pendingReopenDrawer = drawer;
            pendingReopenToolbar = toolbar;
            pendingReopen = true;
            form.confirm();
        } catch (error) {
            clearPendingReopen();
            logWarn("Native save-and-reopen failed: " + error);
        }
    }

    function scheduleReopenAfterClose() {
        if (!pendingReopen || reopenDrawer !== pendingReopenDrawer)
            return;
        const generation = reopenGeneration;
        Qt.callLater(function () {
            if (!plugin.pendingReopen || generation !== plugin.reopenGeneration)
                return;
            const confirmed = plugin.pendingReopenConfirmed;
            const drawer = plugin.pendingReopenDrawer;
            const toolbar = plugin.pendingReopenToolbar;
            const layer = plugin.pendingReopenLayer;
            plugin.clearPendingReopen();
            if (!confirmed)
                return;
            try {
                if (drawer.visible || drawer.digitizingToolbar !== toolbar
                    || !plugin.canStartNativePoint(drawer, toolbar, layer)) {
                    plugin.logWarn("Native reopen skipped: digitizing context changed.");
                    return;
                }
                toolbar.triggerAddVertex();
            } catch (error) {
                plugin.logWarn("Starting native point capture failed: " + error);
                plugin.showMessage("Gespeichert, aber die neue Punkterfassung konnte nicht gestartet werden.");
            }
        });
    }

    function norm(value) {
        return value === null || value === undefined ? "" : ("" + value).toLowerCase().trim();
    }

    function updateObservedUiTargets() {
        const mainWindow = iface.mainWindow();
        mainWindowContent = mainWindow && mainWindow.contentItem ? mainWindow.contentItem : null;

        const overlay = iface.findItemByObjectName("overlayFeatureFormDrawer");
        overlayDrawerObserved = overlay || null;
        try {
            overlayFeatureFormObserved = overlay && overlay.featureForm ? overlay.featureForm : null;
        } catch (error) {
            overlayFeatureFormObserved = null;
        }
    }

    function requestRefreshLoaderHooks() {
        if (refreshHooksScheduled)
            return;
        refreshHooksScheduled = true;
        Qt.callLater(function () {
            refreshHooksScheduled = false;
            refreshLoaderHooks();
        });
    }

    function splitTerms(normalizedValue) {
        return normalizedValue.length ? normalizedValue.split(/\s+/) : [];
    }

    function regexEscape(value) {
        return ("" + value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    }

    function getLayerByName(name) {
        try {
            const layers = qgisProject.mapLayersByName(name);
            return layers && layers.length ? layers[0] : null;
        } catch (error) {
            return null;
        }
    }

    function rebuildIndex() {
        idToDisplay = ({});
        idToValue = ({});
        idToAliases = ({});
        displayNormToAliases = ({});
        displayNormToSpeciesId = ({});
        speciesEntries = [];
        clearContextualCache();
        indexReady = false;

        const speciesLayer = getLayerByName(speciesLayerName);
        const synonymLayer = getLayerByName(synonymLayerName);
        if (!speciesLayer) {
            logWarn("Layer not found: " + speciesLayerName);
            return;
        }
        if (!synonymLayer) {
            logWarn("Layer not found: " + synonymLayerName);
            return;
        }

        const aliasSeenBySpeciesId = ({});

        try {
            const speciesIterator = LayerUtils.createFeatureIterator(speciesLayer);
            while (speciesIterator.hasNext()) {
                const feature = speciesIterator.next();
                const idValue = feature.attribute(speciesIdField);
                const id = idValue === null || idValue === undefined ? "" : "" + idValue;
                const displayValue = feature.attribute(speciesDisplayField);
                if (!id.length || displayValue === null || displayValue === undefined)
                    continue;
                idToValue[id] = idValue;
                idToDisplay[id] = "" + displayValue;
                idToAliases[id] = [];
                aliasSeenBySpeciesId[id] = ({});
            }
            speciesIterator.close();
        } catch (error) {
            logWarn("Failed reading " + speciesLayerName + ": " + error);
            return;
        }

        try {
            const synonymIterator = LayerUtils.createFeatureIterator(synonymLayer);
            while (synonymIterator.hasNext()) {
                const feature = synonymIterator.next();
                const alias = norm(feature.attribute(synonymTermField));
                const referenceValue = feature.attribute(synonymRefField);
                const reference = referenceValue === null || referenceValue === undefined ? "" : "" + referenceValue;
                if (!alias.length || !reference.length || !idToDisplay[reference])
                    continue;
                if (aliasSeenBySpeciesId[reference][alias])
                    continue;
                aliasSeenBySpeciesId[reference][alias] = true;
                idToAliases[reference].push(alias);
            }
            synonymIterator.close();
        } catch (error) {
            logWarn("Failed reading " + synonymLayerName + ": " + error);
            return;
        }

        const entries = [];
        const ids = Object.keys(idToDisplay);
        for (let index = 0; index < ids.length; index++) {
            const id = ids[index];
            const aliases = idToAliases[id] || [];
            const normalizedDisplay = norm(idToDisplay[id]);
            displayNormToAliases[normalizedDisplay] = aliases;
            if (displayNormToSpeciesId[normalizedDisplay] === undefined)
                displayNormToSpeciesId[normalizedDisplay] = id;
            entries.push(searchEntry(id, idToDisplay[id], aliases));
        }
        entries.sort(function (left, right) {
            return left.normalizedDisplay.localeCompare(right.normalizedDisplay);
        });

        speciesEntries = entries;
        indexReady = true;
    }

    function isEffectivelyVisible(item) {
        let current = item;
        while (current) {
            try {
                if (current.visible === false)
                    return false;
            } catch (error) {}
            current = current.parent;
        }
        return true;
    }

    function isEditableTargetForm(item) {
        try {
            if (!item || !item.model || typeof item.model.changeAttribute !== "function")
                return false;
            if (item.state !== "Add" && item.state !== "Edit")
                return false;

            const featureModel = item.model.featureModel;
            const layer = featureModel ? featureModel.currentLayer : null;
            return !!layer && layer.name === targetLayerName && isEffectivelyVisible(item);
        } catch (error) {
            return false;
        }
    }

    function resolveTargetForm() {
        const overlay = iface.findItemByObjectName("overlayFeatureFormDrawer");
        try {
            if (overlay && isEditableTargetForm(overlay.featureForm))
                return overlay.featureForm;
        } catch (error) {}

        const featureForm = iface.findItemByObjectName("featureForm");
        return isEditableTargetForm(featureForm) ? featureForm : null;
    }

    function formForLoader(loader) {
        let current = loader;
        while (current) {
            if (isEditableTargetForm(current))
                return current;
            try {
                current = current.parent;
            } catch (error) {
                break;
            }
        }
        return resolveTargetForm();
    }

    function findDescendantWithSearchPopup(root, depth) {
        return findDescendant(root, function (item) { return !!item.searchPopup; }, depth);
    }

    function findDescendantByObjectName(root, objectName, depth) {
        return findDescendant(root, function (item) { return item.objectName === objectName; }, depth);
    }

    function findDescendant(root, matches, depth) {
        if (!root || depth > 60)
            return null;
        try {
            if (matches(root))
                return root;
        } catch (error) {}

        try {
            const children = root.children;
            if (children) {
                for (let index = 0; index < children.length; index++) {
                    const match = findDescendant(children[index], matches, depth + 1);
                    if (match)
                        return match;
                }
            }
        } catch (error) {}

        try {
            if (root.contentItem && root.contentItem !== root) {
                const contentMatch = findDescendant(root.contentItem, matches, depth + 1);
                if (contentMatch)
                    return contentMatch;
            }
        } catch (error) {}

        return null;
    }

    function inlineMatches(model, rawQuery) {
        const query = norm(rawQuery);
        if (!model || !query.length)
            return [];

        const matches = Array.from(model.findDisplayValueMatches(rawQuery));
        if (!indexReady)
            rebuildIndex();
        if (!indexReady)
            return matches;

        const prefixRows = new Set(matches);
        const entries = [];
        const rows = model.rowCount();
        for (let row = 0; row < rows; row++) {
            if (prefixRows.has(row))
                continue;
            const key = keyForModelRow(model, row);
            if (key === null || key === undefined || key === "")
                continue;
            const display = displayForModelRow(model, row);
            const entry = searchEntry(key, display);
            entry.row = row;
            entries.push(entry);
        }
        return matches.concat(matchingEntries(entries, query).map(function (entry) { return entry.row; }));
    }

    function highlightSearchTerms(text, rawQuery) {
        const terms = splitTerms(norm(rawQuery));
        if (!terms.length)
            return escapeHtml(text);
        terms.sort(function (left, right) { return right.length - left.length; });
        const expression = new RegExp("(" + terms.map(regexEscape).join("|") + ")", "ig");
        const parts = ("" + text).split(expression);
        return parts.map(function (part, index) {
            const escaped = escapeHtml(part);
            return index % 2 ? '<span style="text-decoration:underline;">' + escaped + '</span>' : escaped;
        }).join("");
    }

    function inlineSuggestion(model, row, rawQuery) {
        const key = keyForModelRow(model, row);
        const display = displayForModelRow(model, row);
        const label = resultLabel(searchEntry(key, display), norm(rawQuery));
        return {
            keyValue: key,
            display: display,
            label: label,
            renderedText: highlightSearchTerms(label, rawQuery)
        };
    }

    function findInlineSearchField(root, depth) {
        if (!root || depth > 60)
            return null;
        if (typeof root.applyAutoCompletion === "function" && root.typedFilter !== undefined)
            return root;
        const children = root.children || [];
        for (let index = 0; index < children.length; index++) {
            const match = findInlineSearchField(children[index], depth + 1);
            if (match)
                return match;
        }
        return null;
    }

    function inlineSearchEnabled(loader, relationHost) {
        return !!(loader && relationHost && relationHost.useCompleter
            && relationHost.featureListModel && !relationHost.featureListModel.allowMulti
            && isEditableTargetForm(formForLoader(loader)));
    }

    function updateInlineCompletion(loader, relationHost, textField, label) {
        if (!textField || !textField.activeFocus || !inlineSearchEnabled(loader, relationHost))
            return;
        const query = textField.text.trim();
        const model = relationHost.featureListModel;
        if (!query.length) {
            textField.suggestions = [];
            label.completer = "";
            textField.color = Theme.mainTextColor;
            return;
        }
        const matches = inlineMatches(model, query);
        textField.suggestions = matches.map(function (row) {
            return inlineSuggestion(model, row, query);
        });
        if (!matches.length) {
            label.completer = "";
            textField.color = Theme.warningColor;
            return;
        }
        const suggestion = textField.suggestions[0];
        const display = suggestion.display;
        const suffix = norm(display).indexOf(norm(query)) === 0
            ? suggestion.label.substring(query.length) : " (" + suggestion.label + ")";
        label.completer = '<span style="color:transparent;">' + escapeHtml(textField.text)
            + '</span><span style="font-weight:' + (matches.length === 1 ? 'bold' : 'normal')
            + ';">' + highlightSearchTerms(suffix, query) + '</span>';
        textField.color = Theme.mainTextColor;
    }

    function selectInlineSuggestion(editor, suggestion) {
        if (!inlineSearchEnabled(editor.loaderRef, editor.relationHost))
            return false;
        const model = editor.relationHost.featureListModel;
        const row = model.findKey(suggestion.keyValue);
        if (row < 0 || row >= model.rowCount())
            return false;
        const key = keyForModelRow(model, row);
        const bothNull = model.addNull && (key === null || key === undefined)
            && (suggestion.keyValue === null || suggestion.keyValue === undefined);
        if (!bothNull && !valuesEqual(key, suggestion.keyValue))
            return false;
        editor.selectingSuggestion = true;
        try {
            editor.text = "";
            editor.comboBox.currentIndex = row;
            editor.completionLabel.completer = editor.comboBox.displayText;
            editor.committed = true;
        } finally {
            editor.selectingSuggestion = false;
        }
        return true;
    }

    function completeInlineSearch(editor, resetIfNone) {
        if (!inlineSearchEnabled(editor.loaderRef, editor.relationHost))
            return false;
        const model = editor.relationHost.featureListModel;
        const query = editor.text.trim();
        if (!query.length) {
            if (resetIfNone && model.addNull)
                editor.comboBox.currentIndex = 0;
            return false;
        }
        const matches = inlineMatches(model, query);
        if (!matches.length) {
            if (resetIfNone)
                editor.text = "";
            return false;
        }
        return selectInlineSuggestion(editor, inlineSuggestion(model, matches[0], query));
    }

    Component {
        id: inlineEditorComponent

        TextField {
            id: inlineEditor
            objectName: "fundArtenAliasInlineEditor"
            required property var nativeField
            required property var loaderRef
            required property var relationHost
            required property var comboBox
            required property var completionLabel
            property bool committed: false
            property var suggestions: []
            property bool searching: false
            property bool selectingSuggestion: false

            anchors.fill: nativeField
            visible: relationHost.useCompleter && !relationHost.featureListModel.allowMulti
            font: nativeField.font
            leftPadding: nativeField.leftPadding
            rightPadding: nativeField.rightPadding
            topPadding: nativeField.topPadding
            bottomPadding: nativeField.bottomPadding
            inputMethodHints: nativeField.inputMethodHints
            color: Theme.mainTextColor
            background: Rectangle { color: "transparent" }

            onTextChanged: {
                if (!selectingSuggestion)
                    committed = false;
                nativeField.text = text;
                plugin.updateInlineCompletion(loaderRef, relationHost, inlineEditor, completionLabel);
            }

            onTextEdited: {
                searching = true;
                suggestionsList.currentIndex = suggestions.length ? 0 : -1;
                Qt.callLater(refreshSuggestions);
            }

            onSuggestionsChanged: Qt.callLater(refreshSuggestions)

            onActiveFocusChanged: {
                completionLabel.useCompleter = activeFocus;
                if (activeFocus) {
                    searching = false;
                    committed = false;
                    text = relationHost.featureListModel.addNull && comboBox.currentIndex === 0
                        ? "" : comboBox.displayText;
                    completionLabel.completer = "";
                } else {
                    searching = false;
                    suggestionsPopup.close();
                    if (!committed && !selectingSuggestion)
                        plugin.completeInlineSearch(inlineEditor, true);
                    completionLabel.completer = comboBox.displayText;
                }
            }

            onAccepted: acceptSuggestion()

            Keys.onReturnPressed: event => {
                acceptSuggestion();
                event.accepted = true;
            }
            Keys.onEnterPressed: event => {
                acceptSuggestion();
                event.accepted = true;
            }

            Keys.onDownPressed: event => {
                moveSuggestion(1);
                event.accepted = true;
            }
            Keys.onUpPressed: event => {
                moveSuggestion(-1);
                event.accepted = true;
            }
            Keys.onEscapePressed: event => {
                if (suggestionsPopup.visible) {
                    searching = false;
                    suggestionsPopup.close();
                    event.accepted = true;
                } else {
                    event.accepted = false;
                }
            }

            function acceptSuggestion() {
                if (committed)
                    return;
                if (suggestionsPopup.visible && suggestionsList.currentIndex >= 0
                    && suggestionsList.currentIndex < suggestions.length) {
                    chooseSuggestion(suggestions[suggestionsList.currentIndex]);
                } else if (plugin.completeInlineSearch(inlineEditor, false)) {
                    searching = false;
                    suggestionsPopup.close();
                }
            }

            function chooseSuggestion(suggestion) {
                if (!suggestion)
                    return;
                if (plugin.selectInlineSuggestion(inlineEditor, suggestion)) {
                    searching = false;
                    suggestionsPopup.close();
                } else {
                    plugin.updateInlineCompletion(loaderRef, relationHost, inlineEditor, completionLabel);
                }
            }

            function moveSuggestion(direction) {
                if (!suggestions.length)
                    return;
                searching = true;
                refreshSuggestions();
                suggestionsList.currentIndex = Math.max(0,
                    Math.min(suggestions.length - 1, suggestionsList.currentIndex + direction));
                suggestionsList.positionViewAtIndex(suggestionsList.currentIndex, ListView.Contain);
            }

            function refreshSuggestions() {
                if (!activeFocus || !visible || !searching || !text.trim().length || !suggestions.length) {
                    suggestionsPopup.close();
                    return;
                }
                if (suggestionsList.currentIndex < 0 || suggestionsList.currentIndex >= suggestions.length)
                    suggestionsList.currentIndex = 0;
                const content = iface.mainWindow().contentItem;
                const position = mapToItem(content, 0, 0);
                const keyboardTop = Qt.inputMethod.visible && Qt.inputMethod.keyboardRectangle.height > 0
                    ? Qt.inputMethod.keyboardRectangle.y : content.height;
                const availableHeight = Math.min(content.height, keyboardTop);
                const below = Math.max(0, availableHeight - position.y - height - 10);
                const above = Math.max(0, Math.min(position.y, availableHeight) - 10);
                const placeBelow = below >= Math.min(240, above);
                suggestionsPopup.width = Math.max(0, Math.min(Math.max(width, 280), content.width - 20));
                const listHeight = Math.max(suggestionsList.contentHeight, suggestions.length * 48);
                suggestionsPopup.height = Math.min(288, listHeight + 4, placeBelow ? below : above);
                suggestionsPopup.x = Math.max(10 - position.x,
                    Math.min(0, content.width - 10 - position.x - suggestionsPopup.width));
                suggestionsPopup.y = placeBelow ? height : -suggestionsPopup.height;
                if (suggestionsPopup.height >= 48)
                    suggestionsPopup.open();
                else
                    suggestionsPopup.close();
            }

            onVisibleChanged: {
                if (!visible)
                    suggestionsPopup.close();
            }

            Connections {
                target: inlineEditor.relationHost.featureListModel

                function onModelReset() {
                    plugin.updateInlineCompletion(inlineEditor.loaderRef, inlineEditor.relationHost,
                        inlineEditor, inlineEditor.completionLabel);
                }
            }

            Connections {
                target: Qt.inputMethod

                function onKeyboardRectangleChanged() {
                    Qt.callLater(inlineEditor.refreshSuggestions);
                }
            }

            Connections {
                target: iface.mainWindow().contentItem

                function onHeightChanged() {
                    Qt.callLater(inlineEditor.refreshSuggestions);
                }

                function onWidthChanged() {
                    Qt.callLater(inlineEditor.refreshSuggestions);
                }
            }

            Popup {
                id: suggestionsPopup
                parent: inlineEditor
                padding: 2
                margins: 10
                modal: false
                dim: false
                focus: false
                z: 11000
                closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
                onClosed: inlineEditor.searching = false

                background: Rectangle {
                    color: Theme.mainBackgroundColor
                    border.color: Theme.controlBorderColor
                    radius: 3
                }

                contentItem: ListView {
                    id: suggestionsList
                    model: inlineEditor.suggestions
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: QfScrollBar { focusPolicy: Qt.NoFocus }

                    onContentHeightChanged: Qt.callLater(inlineEditor.refreshSuggestions)

                    delegate: ItemDelegate {
                        id: suggestionDelegate
                        required property var modelData
                        required property int index
                        width: ListView.view.width
                        height: Math.max(suggestionLabel.implicitHeight + 20, 48)
                        padding: 10
                        focusPolicy: Qt.NoFocus

                        background: Rectangle {
                            color: suggestionDelegate.index === suggestionsList.currentIndex
                                ? Qt.rgba(Theme.mainColor.r, Theme.mainColor.g, Theme.mainColor.b, 0.2)
                                : Theme.mainBackgroundColor
                        }

                        contentItem: Text {
                            id: suggestionLabel
                            text: suggestionDelegate.modelData.renderedText
                            textFormat: Text.RichText
                            wrapMode: Text.Wrap
                            font: inlineEditor.font
                            color: Theme.mainTextColor
                        }

                        onClicked: inlineEditor.chooseSuggestion(modelData)
                    }
                }
            }
        }
    }

    function installInlineSearchHook(loader, relationHost) {
        if (!relationHost)
            return;
        if (findDescendantByObjectName(relationHost, "fundArtenAliasInlineEditor", 0))
            return;
        const textField = findInlineSearchField(relationHost, 0);
        const comboBox = findDescendantByObjectName(relationHost, "relationComboBox", 0);
        let label = null;
        const siblings = textField && textField.parent ? textField.parent.children : [];
        for (let index = 0; index < siblings.length; index++) {
            if (siblings[index].completer !== undefined && siblings[index].useCompleter !== undefined) {
                label = siblings[index];
                break;
            }
        }
        if (!textField || !comboBox || !label) {
            logWarn("Inline search controls not found; keeping native completion.");
            return;
        }

        try {
            const editor = inlineEditorComponent.createObject(textField.parent, {
                nativeField: textField,
                loaderRef: loader,
                relationHost: relationHost,
                comboBox: comboBox,
                completionLabel: label
            });
            if (!editor)
                throw new Error("Could not create inline editor");
            textField.focus = false;
            textField.visible = Qt.binding(function () {
                return !relationHost.useCompleter || relationHost.featureListModel.allowMulti;
            });
        } catch (error) {
            logWarn("Failed to install inline alias completion: " + error);
        }
    }

    function installSearchButtonInterceptor(button, loader) {
        if (!button || hookedButtons.indexOf(button) !== -1)
            return;

        const interceptCode = ''
            + 'import QtQuick\n'
            + 'MouseArea {\n'
            + '  anchors.fill: parent\n'
            + '  acceptedButtons: Qt.LeftButton\n'
            + '  preventStealing: true\n'
            + '  propagateComposedEvents: false\n'
            + '  z: 9999\n'
            + '  onPressed: mouse => { mouse.accepted = true }\n'
            + '  onClicked: mouse => { mouse.accepted = true; plugin.openPicker(loaderRef) }\n'
            + '  property var loaderRef\n'
            + '}';

        try {
            const interceptor = Qt.createQmlObject(interceptCode, button, "FundArtnameSearchInterceptor");
            interceptor.loaderRef = loader;
            hookedButtons.push(button);
        } catch (error) {
            logWarn("Failed to install search button interceptor: " + error);
        }
    }

    function hookFieldEditorLoader(loader) {
        if (!loader)
            return;

        const relationHost = loader.item ? findDescendantWithSearchPopup(loader.item, 0) : null;

        if (loader.item) {
            const searchButton = findDescendantByObjectName(loader.item, "openSearchFeaturePopupButton", 0);
            if (searchButton)
                installSearchButtonInterceptor(searchButton, loader);
        }

        setLoaderContext(loader, relationHost);

        if (!relationHost || !relationHost.searchPopup)
            return;

        const nativePopup = relationHost.searchPopup;
        if (hookedPopups.indexOf(nativePopup) !== -1)
            return;

        installInlineSearchHook(loader, relationHost);
        hookedPopups.push(nativePopup);
        const openAliasPicker = function () {
            if (!isEffectivelyVisible(loader))
                return;
            suppressNativePopup(nativePopup);
            Qt.callLater(function () {
                openPicker(loader);
            });
        };
        try {
            nativePopup.aboutToShow.connect(openAliasPicker);
        } catch (error) {}
        nativePopup.opened.connect(openAliasPicker);
    }

    function setLoaderContext(loader, relationHost) {
        if (!loader)
            return;
        for (let index = 0; index < loaderContexts.length; index++) {
            if (loaderContexts[index].loader === loader) {
                loaderContexts[index].relationHost = relationHost;
                return;
            }
        }
        loaderContexts.push({
            loader: loader,
            relationHost: relationHost
        });
    }

    function observeLoader(loader) {
        if (!loader || observedLoaders.indexOf(loader) !== -1)
            return;
        observedLoaders.push(loader);
        try {
            loader.itemChanged.connect(function () {
                plugin.requestRefreshLoaderHooks();
            });
        } catch (error) {}
        try {
            loader.statusChanged.connect(function () {
                plugin.requestRefreshLoaderHooks();
            });
        } catch (error) {}
        try {
            loader.visibleChanged.connect(function () {
                plugin.requestRefreshLoaderHooks();
            });
        } catch (error) {}
    }

    function relationHostForLoader(loader) {
        for (let index = 0; index < loaderContexts.length; index++) {
            if (loaderContexts[index].loader === loader)
                return loaderContexts[index].relationHost;
        }
        return null;
    }

    function clearContextualCache() {
        contextualCacheLoader = null;
        contextualCacheModel = null;
        contextualEntriesCache = [];
        contextualCacheReady = false;
    }

    function compactHooks() {
        const isLive = function (item) {
            try {
                return !!item;
            } catch (error) { return false; }
        };
        hookedButtons = hookedButtons.filter(isLive);
        hookedPopups = hookedPopups.filter(isLive);
        loaderContexts = loaderContexts.filter(function (context) {
            try {
                return !!(context && context.loader);
            } catch (error) { return false; }
        });
    }

    function keyForModelRow(model, row) {
        let keyValue = undefined;
        try {
            if (typeof QfFeatureListModel !== "undefined" && QfFeatureListModel.KeyFieldRole !== undefined)
                keyValue = model.dataFromRowIndex(row, QfFeatureListModel.KeyFieldRole);
            else if (typeof FeatureListModel !== "undefined" && FeatureListModel.KeyFieldRole !== undefined)
                keyValue = model.dataFromRowIndex(row, FeatureListModel.KeyFieldRole);
        } catch (error) {}
        try {
            if ((keyValue === undefined || keyValue === null || keyValue === "") && typeof model.dataFromRowIndex === "function")
                keyValue = model.dataFromRowIndex(row, "keyFieldValue");
        } catch (error) {}
        return keyValue;
    }

    function displayForModelRow(model, row) {
        let displayValue = undefined;
        try {
            if (typeof QfFeatureListModel !== "undefined" && QfFeatureListModel.DisplayStringRole !== undefined)
                displayValue = model.dataFromRowIndex(row, QfFeatureListModel.DisplayStringRole);
            else if (typeof FeatureListModel !== "undefined" && FeatureListModel.DisplayStringRole !== undefined)
                displayValue = model.dataFromRowIndex(row, FeatureListModel.DisplayStringRole);
        } catch (error) {}
        try {
            if ((displayValue === undefined || displayValue === null) && typeof model.dataFromRowIndex === "function")
                displayValue = model.dataFromRowIndex(row, "displayString");
        } catch (error) {}
        try {
            if ((displayValue === undefined || displayValue === null) && typeof model.dataFromRowIndex === "function")
                displayValue = model.dataFromRowIndex(row, "display");
        } catch (error) {}
        return displayValue;
    }

    function entriesForActiveContext() {
        const loader = activeEditorLoader;
        if (!loader)
            return speciesEntries;

        let relationHost = relationHostForLoader(loader);
        if (!relationHost && loader.item)
            relationHost = findDescendantWithSearchPopup(loader.item, 0);
        if (!relationHost || !relationHost.featureListModel)
            return speciesEntries;

        const model = relationHost.featureListModel;
        if (typeof model.rowCount !== "function")
            return speciesEntries;

        if (contextualCacheReady && contextualCacheLoader === loader && contextualCacheModel === model)
            return contextualEntriesCache;

        const contextualEntries = [];
        const seen = ({});
        try {
            const rows = model.rowCount();
            for (let row = 0; row < rows; row++) {
                const keyValue = keyForModelRow(model, row);
                const key = keyValue === null || keyValue === undefined ? "" : "" + keyValue;
                if (!key.length)
                    continue;
                if (seen[key])
                    continue;
                seen[key] = true;

                const displayValue = displayForModelRow(model, row);
                const display = displayValue === null || displayValue === undefined || ("" + displayValue).length === 0
                    ? (idToDisplay[key] || key)
                    : "" + displayValue;
                const canonicalKey = idToDisplay[key] !== undefined ? key : speciesIdForSelection(display);
                const aliases = idToAliases[key] || displayNormToAliases[norm(display)] || [];
                contextualEntries.push(searchEntry(canonicalKey, display, aliases));
            }
        } catch (error) {
            return speciesEntries;
        }

        contextualCacheLoader = loader;
        contextualCacheModel = model;
        contextualEntriesCache = contextualEntries.length ? contextualEntries : speciesEntries;
        contextualCacheReady = true;
        return contextualEntriesCache;
    }

    function scanForFieldEditorLoaders(root, depth, visited) {
        if (!root || depth > 60)
            return 0;
        if (!visited)
            visited = new Set();
        if (visited.has(root))
            return 0;
        visited.add(root);

        let found = 0;
        try {
            if (root.objectName === targetFieldEditorLoaderObjectName) {
                observeLoader(root);
                hookFieldEditorLoader(root);
                found++;
            }

            const children = root.children;
            if (children) {
                for (let index = 0; index < children.length; index++)
                    found += scanForFieldEditorLoaders(children[index], depth + 1, visited);
            }
        } catch (error) {}

        try {
            if (root.contentItem && root.contentItem !== root)
                found += scanForFieldEditorLoaders(root.contentItem, depth + 1, visited);
        } catch (error) {}

        return found;
    }

    function refreshLoaderHooks() {
        updateObservedUiTargets();
        compactHooks();
        installReopenButton();

        const direct = iface.findItemByObjectName(targetFieldEditorLoaderObjectName);
        if (direct) {
            observeLoader(direct);
            hookFieldEditorLoader(direct);
        }

        let foundCount = 0;
        const overlay = iface.findItemByObjectName("overlayFeatureFormDrawer");
        if (overlay) {
            foundCount += scanForFieldEditorLoaders(overlay, 0);
            try {
                if (overlay.featureForm)
                    foundCount += scanForFieldEditorLoaders(overlay.featureForm, 0);
            } catch (error) {}
        }

        if (foundCount === 0) {
            const mainWindow = iface.mainWindow();
            scanForFieldEditorLoaders(mainWindow, 0);
        }
    }

    function openPicker(editorLoader) {
        if (!indexReady)
            rebuildIndex();
        if (!indexReady) {
            showMessage("Die Artenliste konnte nicht geladen werden.");
            return;
        }
        if (!editorLoader || !isEffectivelyVisible(editorLoader)) {
            showMessage("Bitte zuerst einen Fund zum Bearbeiten oder Erfassen oeffnen.");
            return;
        }
        suppressAllNativePopups();
        activeEditorLoader = editorLoader;
        clearContextualCache();
        currentSpeciesId = readCurrentSpeciesId(editorLoader);
        picker.open();
    }

    function readCurrentSpeciesId(loader) {
        let relationHost = relationHostForLoader(loader);
        if (!relationHost && loader && loader.item)
            relationHost = findDescendantWithSearchPopup(loader.item, 0);
        try {
            const value = relationHost ? relationHost.currentKeyValue : undefined;
            return value === null || value === undefined ? "" : "" + value;
        } catch (error) {
            return "";
        }
    }

    function suppressNativePopup(nativePopup) {
        if (!nativePopup)
            return;
        if (suppressedNativePopups.indexOf(nativePopup) === -1)
            suppressedNativePopups.push(nativePopup);
        try {
            nativePopup.close();
        } catch (error) {}
        try {
            nativePopup.opacity = 0;
        } catch (error) {}
        try {
            nativePopup.enabled = false;
        } catch (error) {}
    }

    function suppressAllNativePopups() {
        for (let index = 0; index < hookedPopups.length; index++)
            suppressNativePopup(hookedPopups[index]);
    }

    function restoreSuppressedNativePopups() {
        for (let index = 0; index < suppressedNativePopups.length; index++) {
            try {
                suppressedNativePopups[index].opacity = 1;
            } catch (error) {}
            try {
                suppressedNativePopups[index].enabled = true;
            } catch (error) {}
        }
        suppressedNativePopups = [];
    }

    function searchEntry(speciesId, display, aliases) {
        const normalizedDisplay = norm(display);
        aliases = aliases || idToAliases["" + speciesId] || displayNormToAliases[normalizedDisplay] || [];
        return {
            speciesId: speciesId,
            display: display,
            aliases: aliases,
            normalizedDisplay: normalizedDisplay,
            searchText: norm(normalizedDisplay + " " + aliases.join(" "))
        };
    }

    function matchingEntries(entries, query) {
        const terms = splitTerms(query);
        if (!terms.length)
            return entries;
        return entries.filter(function (entry) {
            return terms.every(function (term) { return entry.searchText.indexOf(term) !== -1; });
        }).map(function (entry) {
            return {entry: entry, score: scoreEntry(entry, query)};
        }).sort(function (left, right) {
            return left.score - right.score
                || left.entry.normalizedDisplay.localeCompare(right.entry.normalizedDisplay);
        }).map(function (match) { return match.entry; });
    }

    function scoreEntry(entry, preparedQuery) {
        if (!preparedQuery.length)
            return 10;
        if (entry.normalizedDisplay === preparedQuery)
            return 0;
        if (entry.normalizedDisplay.indexOf(preparedQuery) === 0)
            return 1;
        if (entry.normalizedDisplay.indexOf(preparedQuery) !== -1)
            return 2;

        for (let index = 0; index < entry.aliases.length; index++) {
            if (entry.aliases[index] === preparedQuery)
                return 3;
            if (entry.aliases[index].indexOf(preparedQuery) === 0)
                return 4;
        }
        return 5;
    }

    function aliasesForResult(entry, preparedQuery) {
        for (let index = 0; index < entry.aliases.length; index++) {
            if (!preparedQuery.length || entry.aliases[index].indexOf(preparedQuery) !== -1)
                return entry.aliases[index];
        }
        return "";
    }

    function resultLabel(entry, preparedQuery) {
        const aliasPreview = aliasesForResult(entry, preparedQuery);
        return aliasPreview.length && entry.normalizedDisplay.indexOf(preparedQuery) === -1
            ? entry.display + " (Synonym: " + aliasPreview + ")" : entry.display;
    }

    function escapeHtml(text) {
        const source = text === null || text === undefined ? "" : "" + text;
        return source
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/\"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function updateResults(rawQuery) {
        resultModel.clear();
        const query = norm(rawQuery);
        const matches = matchingEntries(entriesForActiveContext(), query);
        const count = Math.min(matches.length, maximumResults);
        for (let matchIndex = 0; matchIndex < count; matchIndex++) {
            const entry = matches[matchIndex];
            const label = resultLabel(entry, query);
            resultModel.append({
                speciesId: entry.speciesId,
                renderedText: highlightSearchTerms(label, query)
            });
        }
    }

    function scheduleResultUpdate(rawQuery) {
        pendingSearchTerm = rawQuery;
        if (resultsUpdateScheduled)
            return;
        resultsUpdateScheduled = true;
        Qt.callLater(function () {
            resultsUpdateScheduled = false;
            plugin.updateResults(plugin.pendingSearchTerm);
        });
    }

    function valuesEqual(left, right) {
        if (left === null || left === undefined || right === null || right === undefined)
            return false;
        return ("" + left) === ("" + right);
    }

    function fieldValue(form) {
        try {
            if (form && form.model && typeof form.model.attribute === "function")
                return form.model.attribute(targetFieldName);
        } catch (error) {
            logWarn("Reading " + targetFieldName + " failed: " + error);
        }
        return undefined;
    }

    function speciesIdForSelection(selection) {
        const candidate = selection === null || selection === undefined ? "" : "" + selection;
        if (idToValue[candidate] !== undefined)
            return candidate;

        const normalizedCandidate = norm(candidate);
        if (displayNormToSpeciesId[normalizedCandidate] !== undefined)
            return displayNormToSpeciesId[normalizedCandidate];
        return candidate;
    }

    function changeFormAttribute(form, value) {
        try {
            if (form && form.model && typeof form.model.changeAttribute === "function") {
                const changed = form.model.changeAttribute(targetFieldName, value);
                return changed;
            }
        } catch (error) {
            logWarn("changeAttribute failed: " + error);
        }
        return false;
    }

    function applyViaRelationCombobox(loader, value) {
        let relationHost = relationHostForLoader(loader);
        if (!relationHost && loader.item)
            relationHost = findDescendantWithSearchPopup(loader.item, 0);
        if (!relationHost || !relationHost.featureListModel)
            return;

        try {
            const row = relationHost.featureListModel.findKey(value);
            if (row < 0)
                return;

            const comboBox = findDescendantByObjectName(loader.item, "relationComboBox", 0);
            if (comboBox)
                comboBox.currentIndex = row;
        } catch (error) {
            logWarn("Relation combo box selection failed: " + error);
        }
    }

    function selectSpecies(speciesId) {
        const loader = activeEditorLoader;
        if (!loader || !isEffectivelyVisible(loader)) {
            picker.close();
            showMessage("Das Fundformular ist nicht mehr geoeffnet.");
            return;
        }

        const resolvedSpeciesId = speciesIdForSelection(speciesId);
        const value = idToValue[resolvedSpeciesId] !== undefined ? idToValue[resolvedSpeciesId] : resolvedSpeciesId;
        if (value === undefined || value === null) {
            showMessage("Die ausgewaehlte Art ist nicht mehr verfuegbar.");
            return;
        }

        const form = formForLoader(loader);
        let applied = valuesEqual(fieldValue(form), value);

        if (!applied)
            applied = changeFormAttribute(form, value);

        if (!applied) {
            try {
                if (loader.item && loader.item.valueChangeRequested) {
                    loader.item.valueChangeRequested(value, false);
                    applied = true;
                }
            } catch (error) {
                logWarn("valueChangeRequested failed: " + error);
            }
        }

        if (!applied) {
            showMessage("Artname konnte nicht gesetzt werden.");
            return;
        }

        applyViaRelationCombobox(loader, value);

        currentSpeciesId = "" + resolvedSpeciesId;
        picker.close();
    }

    property string pendingSearchTerm: ""

    ListModel {
        id: resultModel
    }

    function selectSingleResult() {
        if (resultModel.count === 1)
            selectSpecies(resultModel.get(0).speciesId);
    }

    QfPopup {
        id: picker

        readonly property int horizontalMargin: 10
        readonly property int verticalMargin: 20

        parent: iface.mainWindow().contentItem
        x: horizontalMargin
        y: (parent.height - height) / 2
        width: parent.width - horizontalMargin * 2
        height: Math.max(parent.height - verticalMargin * 2, 200)
        padding: 5
        modal: true
        dim: true
        focus: true
        z: 12000
        closePolicy: Popup.CloseOnEscape

        onOpened: {
            searchBar.setSearchTerm("");
            searchBar.focusOnTextField();
            updateResults("");
            plugin.suppressAllNativePopups();
        }

        onClosed: {
            plugin.activeEditorLoader = null;
            plugin.clearContextualCache();
            plugin.restoreSuppressedNativePopups();
        }

        background: Rectangle {
            color: Theme.mainBackgroundColor
            radius: 5
        }

        Item {
            anchors.fill: parent

            QfPageHeader {
                id: pageHeader
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                title: plugin.targetFieldName
                showBackButton: false
                showApplyButton: false
                showCancelButton: true
                onCancel: picker.close()
            }

            Item {
                id: searchHost
                anchors.top: pageHeader.bottom
                anchors.left: parent.left
                anchors.right: parent.right
                height: 48

                QfSearchBar {
                    id: searchBar
                    objectName: "fundArtenAliasSearchBar"
                    anchors.fill: parent
                    placeHolderText: ""

                    onSearchTermChanged: {
                        plugin.scheduleResultUpdate(searchTerm);
                    }

                    onSearchTriggered: {
                        plugin.selectSingleResult();
                    }
                }
            }

            ListView {
                id: resultsList
                anchors.top: searchHost.bottom
                anchors.topMargin: 5
                anchors.bottom: parent.bottom
                anchors.left: parent.left
                anchors.right: parent.right
                clip: true
                model: resultModel
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: QfScrollBar {}

                onMovementStarted: Qt.inputMethod.hide()

                delegate: ItemDelegate {
                    id: resultDelegate

                    required property string speciesId
                    required property string renderedText

                    readonly property bool isCurrent: speciesId === plugin.currentSpeciesId

                    width: ListView.view.width
                    height: Math.max(resultLabel.implicitHeight + 20, 48)
                    padding: 10

                    background: Rectangle {
                        color: resultDelegate.isCurrent ? Theme.mainColor : resultDelegate.pressed ? Qt.rgba(Theme.mainColor.r, Theme.mainColor.g, Theme.mainColor.b, 0.2) : "transparent"

                        Rectangle {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            height: 1
                            color: Theme.controlBorderColor
                        }
                    }

                    contentItem: Text {
                        id: resultLabel
                        leftPadding: 5
                        text: resultDelegate.renderedText
                        font.pointSize: Theme.defaultFont.pointSize
                        font.weight: resultDelegate.isCurrent ? Font.DemiBold : Font.Normal
                        color: Theme.mainTextColor
                        textFormat: Text.RichText
                        elide: Text.ElideRight
                        wrapMode: Text.WordWrap
                        verticalAlignment: Text.AlignVCenter
                    }

                    onClicked: plugin.selectSpecies(resultDelegate.speciesId)
                }
            }
        }
    }
}
