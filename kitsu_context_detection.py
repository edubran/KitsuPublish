# kitsu_context_detection.py
# -*- coding: utf-8 -*-
# Detects the active DCC environment.
# Shared by kitsu_publisher_panel.py and kitsu_task_panel.py.
# Returns: 'houdini', 'maya', 'nuke', 'blender' or 'standalone'.

def get_dcc_context():
    """
    Detect the current DCC by probing for DCC-specific modules.
    Returns a lowercase string identifying the host application.
    """
    try:
        import hou
        return "houdini"
    except ImportError:
        pass

    try:
        import maya.cmds
        return "maya"
    except ImportError:
        pass

    try:
        import nuke
        return "nuke"
    except ImportError:
        pass

    try:
        import bpy
        return "blender"
    except ImportError:
        pass

    return "standalone"
