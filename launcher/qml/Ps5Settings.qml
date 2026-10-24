import QtQuick
import QtQuick.Controls

// Full-screen PS5 settings: a category menu and one focused category at a time.
Item {
    id: root
    objectName: "settingsPage"
    signal openSetup(int step)
    property string activeCategory: ""
    property string activeSection: ""
    property bool ready: false
    property bool detailOpen: activeCategory !== ""

    property var categories: launcher.settingsCategories

    Component.onCompleted: Qt.callLater(function () { root.ready = true })

    onActiveCategoryChanged: {
        if (activeCategory !== "" && ready)
            categoryReveal.restart()
    }

    NumberAnimation {
        id: categoryReveal
        target: detailContent
        property: "opacity"
        from: 0.4; to: 1
        duration: Theme.motionBase
        easing.type: Easing.OutCubic
    }

    function categoryFor(key) {
        for (let i = 0; i < categories.length; i++)
            if (categories[i].key === key) return categories[i]
        return null
    }
    function activeInfo() { return categoryFor(activeCategory) }
    function showMenu() { activeCategory = ""; activeSection = "" }
    function openAt(key, section) {
        const category = categoryFor(key)
        if (!category) { showMenu(); return }
        activeCategory = key
        activeSection = section || ""
        Qt.callLater(scrollToTarget)
    }
    function scrollToTarget() {
        if (!activeSection) { detailScroll.contentY = 0; return }
        for (let i = 0; i < groupRepeater.count; i++) {
            const item = groupRepeater.itemAt(i)
            if (item && item.group && item.group.section === activeSection) {
                detailScroll.contentY = Math.max(0, item.y - 8)
                return
            }
        }
        detailScroll.contentY = 0
    }
    function fieldsFor(group) {
        let fields = launcher.sectionFields(group.category, group.section)
        if (group.keys && group.keys.length > 0)
            fields = fields.filter(function (field) { return group.keys.indexOf(field.key) >= 0 })
        return fields
    }

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#17151a" }
            GradientStop { position: 1.0; color: Theme.base }
        }
    }

    // Category menu.
    Flickable {
        anchors.fill: parent
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        contentWidth: width
        contentHeight: menuContent.implicitHeight + 56
        ScrollBar.vertical: AppScrollBar {}
        enabled: !root.detailOpen
        opacity: root.detailOpen ? 0 : 1
        visible: opacity > 0.01
        transform: Translate {
            x: root.detailOpen ? -10 : 0
            Behavior on x {
                enabled: root.ready
                NumberAnimation { duration: Theme.motionBase; easing.type: Easing.OutCubic }
            }
        }
        Behavior on opacity {
            enabled: root.ready
            NumberAnimation { duration: Theme.motionBase; easing.type: Easing.OutCubic }
        }

        Column {
            id: menuContent
            x: 56; y: 30
            width: Math.min(1120, root.width - 112)
            spacing: 0
            Text {
                text: "Settings"; color: Theme.text; font.family: Theme.sans
                font.pixelSize: 34; font.weight: Font.Normal
            }
            Item { width: 1; height: 22 }
            Repeater {
                model: root.categories
                delegate: Button {
                    id: categoryRow
                    width: menuContent.width; height: 62
                    hoverEnabled: true
                    focusPolicy: Qt.StrongFocus
                    onClicked: root.openAt(modelData.key, "")
                    background: Rectangle {
                        color: categoryRow.activeFocus ? Theme.surfaceActive
                               : categoryRow.hovered ? Theme.surfaceHover : "transparent"
                        Behavior on color { ColorAnimation { duration: Theme.motionFast } }
                        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }
                        Rectangle {
                            visible: categoryRow.activeFocus
                            width: 2; height: parent.height - 12; anchors.verticalCenter: parent.verticalCenter
                            color: Theme.accent
                        }
                    }
                    contentItem: Row {
                        anchors.left: parent.left; anchors.leftMargin: 16
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 18
                        NavIcon {
                            width: 21; height: 21; kind: modelData.icon
                            strokeColor: categoryRow.activeFocus ? Theme.text : Theme.textDim
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: modelData.label; color: categoryRow.activeFocus ? Theme.text : Theme.text
                            font.family: Theme.sans; font.pixelSize: 17
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                    Accessible.role: Accessible.PageTab
                    Accessible.name: modelData.label
                }
            }
        }
    }

    // Category detail.
    Column {
        anchors.fill: parent
        spacing: 0
        enabled: root.detailOpen
        opacity: root.detailOpen ? 1 : 0
        visible: opacity > 0.01
        transform: Translate {
            x: root.detailOpen ? 0 : 14
            Behavior on x {
                enabled: root.ready
                NumberAnimation { duration: Theme.motionBase; easing.type: Easing.OutCubic }
            }
        }
        Behavior on opacity {
            enabled: root.ready
            NumberAnimation { duration: Theme.motionBase; easing.type: Easing.OutCubic }
        }

        Row {
            width: parent.width; height: 52
            x: 36
            spacing: 14
            Button {
                text: "‹  Settings"
                flat: true; height: 34
                anchors.verticalCenter: parent.verticalCenter
                onClicked: root.showMenu()
                contentItem: Text {
                    text: parent.text; color: Theme.textDim
                    font.family: Theme.sans; font.pixelSize: 13
                    horizontalAlignment: Text.AlignLeft; verticalAlignment: Text.AlignVCenter
                }
                background: Rectangle { color: "transparent" }
            }
            Text {
                text: root.activeInfo() ? root.activeInfo().label : ""
                color: Theme.text; font.family: Theme.sans; font.pixelSize: 26
                anchors.verticalCenter: parent.verticalCenter
            }
        }

        Item {
            width: parent.width; height: parent.height - 52

            Flickable {
                id: detailScroll
                visible: !(root.activeInfo() && root.activeInfo().diagnostics === true)
                anchors.fill: parent
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                contentWidth: width
                contentHeight: detailContent.implicitHeight + 40
                ScrollBar.vertical: AppScrollBar {}
                onVisibleChanged: contentY = 0

                Column {
                    id: detailContent
                    x: Math.max(28, (detailScroll.width - width) / 2)
                    width: Math.min(1040, detailScroll.width - 56)
                    spacing: 0

                    Item { width: 1; height: 2 }
                    Text {
                        width: parent.width; wrapMode: Text.WordWrap
                        text: "Changes save as you make them. Restart options apply at the next launch."
                        color: Theme.textDim; font.family: Theme.sans; font.pixelSize: 11
                    }
                    Item { width: 1; height: 10 }

                    Repeater {
                        id: groupRepeater
                        model: root.activeInfo() ? root.activeInfo().groups : []
                        delegate: Column {
                            id: groupColumn
                            property var group: modelData
                            width: detailContent.width
                            spacing: 0

                            Item { width: 1; height: 12 }
                            Text {
                                text: groupColumn.group.title || groupColumn.group.section
                                color: Theme.text
                                font.family: Theme.sans; font.pixelSize: 15; font.weight: Font.DemiBold
                            }
                            Text {
                                property string hint: groupColumn.group.hint !== undefined
                                                      ? groupColumn.group.hint
                                                      : launcher.sectionHint(groupColumn.group.category,
                                                                             groupColumn.group.section)
                                visible: hint !== ""
                                width: parent.width; text: hint
                                color: Theme.textDim; font.family: Theme.sans; font.pixelSize: 11
                                wrapMode: Text.WordWrap; lineHeight: 1.3; topPadding: 3
                            }
                            Item { width: 1; height: 6 }

                            Repeater {
                                model: root.fieldsFor(groupColumn.group)
                                delegate: FieldRow { width: groupColumn.width; field: modelData }
                            }
                            SectionActions {
                                visible: groupColumn.group.actions !== false
                                width: groupColumn.width
                                category: groupColumn.group.category
                                section: groupColumn.group.section
                                onOpenSetup: (step) => root.openSetup(step)
                            }
                            Item { width: 1; height: 10 }
                            Rectangle { width: parent.width; height: 1; color: Theme.line }
                        }
                    }
                    Item { width: 1; height: 20 }
                }
            }

            DiagnosticsPage {
                visible: root.activeInfo() && root.activeInfo().diagnostics === true
                anchors.fill: parent
            }
        }
    }
}
