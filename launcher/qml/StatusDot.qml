import QtQuick

// A small state dot with an optional slow halo while the launcher is preparing a launch.
Item {
    id: dot
    property color color: Theme.good
    property bool busy: false

    implicitWidth: 8
    implicitHeight: 8
    width: implicitWidth
    height: implicitHeight

    Rectangle {
        anchors.fill: parent
        radius: width / 2
        color: dot.color
        Behavior on color { ColorAnimation { duration: Theme.motionBase } }
    }
    Rectangle {
        anchors.centerIn: parent
        width: parent.width
        height: parent.height
        radius: width / 2
        color: dot.color
        visible: dot.busy
        opacity: 0
        scale: 1
        SequentialAnimation on opacity {
            running: dot.busy
            loops: Animation.Infinite
            NumberAnimation { from: 0.45; to: 0; duration: 1000; easing.type: Easing.OutCubic }
            PauseAnimation { duration: 300 }
        }
        NumberAnimation on scale {
            running: dot.busy
            loops: Animation.Infinite
            from: 1; to: 2.4
            duration: 1000; easing.type: Easing.OutCubic
        }
    }
}
