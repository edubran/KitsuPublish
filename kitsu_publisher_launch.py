# kitsu_publisher_launch.py
# -*- coding: utf-8 -*-
# Launcher for Kitsu Publisher.
# Works in Nuke, Maya, Houdini, Blender and standalone Python.
#
# Usage (shelf button / menu item — same for all DCCs):
#
#   import sys
#   sys.path.insert(0, "/path/to/your/scripts/folder")
#   import kitsu_publisher_launch, importlib
#   importlib.reload(kitsu_publisher_launch)
#   kitsu_publisher_launch.launch()

import sys
import os
import importlib


def launch():
    # Ensure the folder containing this file is on sys.path
    # so kitsu_publisher_panel.py and its siblings are always found.
    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in sys.path:
        sys.path.insert(0, _here)

    try:
        import kitsu_context_detection
        import kitsu_publisher_dcc_integrations
        import kitsu_publisher_panel

        importlib.reload(kitsu_context_detection)
        importlib.reload(kitsu_publisher_dcc_integrations)
        importlib.reload(kitsu_publisher_panel)

    except ImportError as e:
        msg = "KitsuPublisher: could not import required module: " + str(e)
        print(msg)
        try:
            import maya.cmds as cmds
            cmds.confirmDialog(title="Import Error", message=msg)
            return
        except ImportError:
            pass
        try:
            import hou
            hou.ui.displayMessage(msg, severity=hou.severityType.Error)
            return
        except ImportError:
            pass
        try:
            import bpy
            print(msg)  # Blender: surfaces in console
            return
        except ImportError:
            pass
        return

    kitsu_publisher_panel.show_kitsu_publisher()


if __name__ == "__main__":
    launch()
