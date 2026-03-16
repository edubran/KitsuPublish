# kitsu_publisher_dcc_integrations.py
# -*- coding: utf-8 -*-
# Playblast integrations for Maya and Houdini — used by kitsu_publisher_panel.py
import os
import subprocess
import shutil

class PlayblastInterface:
    def get_cameras(self): raise NotImplementedError()
    def get_frame_range(self): raise NotImplementedError()
    def get_output_defaults(self): raise NotImplementedError()
    def generate_frames(self, settings): raise NotImplementedError()
    def find_ffmpeg(self):
        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path: return ffmpeg_path
        if os.name == 'nt':
            for path in [r"C:\ffmpeg\bin\ffmpeg.exe", r"C:\ffmpeg\ffmpeg.exe"]:
                if os.path.exists(path): return path
        raise RuntimeError("FFMPEG not found in PATH or C:\\ffmpeg. Set a custom path in config.")
    def convert_to_mp4(self, settings):
        ffmpeg_path = self.find_ffmpeg()
        ffmpeg_cmd = [
            ffmpeg_path, "-y", "-framerate", str(settings['frame_rate']),
            "-start_number", str(int(settings['start_frame'])), "-i", settings['ffmpeg_input_pattern'],
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
            settings['output_mp4_filepath']
        ]
        subprocess.run(ffmpeg_cmd, check=True, capture_output=True, text=True, encoding='utf-8')

class HoudiniPlayblast(PlayblastInterface):
    def __init__(self): import hou; self.hou = hou
    def get_cameras(self):
        cameras = []
        for node in self.hou.node("/obj").children():
            if node.type().category().name() == "Object" and node.parm("camswitcher") is None:
                if node.type().name() in ["cam", "stereocam"] or "camera" in node.type().name().lower():
                    cameras.append(node.path())
        return sorted(cameras)
    def get_frame_range(self):
        frange = self.hou.playbar.frameRange(); return frange.x(), frange.y()
    def get_output_defaults(self):
        hip_dir = self.hou.getenv('HIP'); hip_name = self.hou.getenv('HIPNAME')
        return {"path": hip_dir or os.path.expanduser("~"), "filename": f"{hip_name}_playblast" if hip_name else "playblast_output"}
    def generate_frames(self, settings):
        scene_viewer = self.hou.ui.paneTabOfType(self.hou.paneTabType.SceneViewer)
        if not scene_viewer:
             all_viewers = self.hou.ui.paneTabsOfType(self.hou.paneTabType.SceneViewer)
             if not all_viewers: raise RuntimeError("No Scene Viewer found in Houdini.")
             scene_viewer = all_viewers[0]
        viewport = scene_viewer.curViewport()
        viewport.setCamera(self.hou.node(settings['camera']))
        flip_settings = scene_viewer.flipbookSettings().stash()
        flip_settings.frameRange((settings['start_frame'], settings['end_frame']))
        flip_settings.output(settings['image_seq_pattern'])
        flip_settings.outputToMPlay(False); flip_settings.useResolution(True); flip_settings.resolution((1920, 1080))
        scene_viewer.flipbook(viewport, flip_settings)

class MayaPlayblast(PlayblastInterface):
    def __init__(self): import maya.cmds as cmds; self.cmds = cmds
    def get_cameras(self):
        all_cameras = self.cmds.ls(type='camera')
        startup_cameras = {'frontShape', 'perspShape', 'sideShape', 'topShape'}
        scene_cameras = [cam for cam in all_cameras if cam not in startup_cameras]
        valid_cameras = [self.cmds.listRelatives(cam, parent=True)[0] for cam in scene_cameras if self.cmds.listRelatives(cam, parent=True)]
        return sorted(valid_cameras)
    def get_frame_range(self):
        start = self.cmds.playbackOptions(q=True, minTime=True); end = self.cmds.playbackOptions(q=True, maxTime=True)
        return start, end
    def get_output_defaults(self):
        workspace_dir = self.cmds.workspace(q=True, rd=True)
        scene_name = self.cmds.file(q=True, sn=True, shn=True)
        filename = os.path.splitext(scene_name)[0] if scene_name else "playblast_output"
        movies_dir = os.path.join(workspace_dir, "movies")
        if not os.path.exists(movies_dir): os.makedirs(movies_dir)
        return {"path": movies_dir, "filename": filename}
    def generate_frames(self, settings):
        # --- [CORREÇÃO] Módulo 'mel' importado apenas quando necessário ---
        from maya import mel
        output_filename = settings['image_seq_pattern'].replace(".$F4.jpg", "").replace("\\", "/")
        panel = self.cmds.getPanel(withFocus=True)
        if not panel or self.cmds.getPanel(typeOf=panel) != 'modelPanel':
            panels = self.cmds.getPanel(type='modelPanel')
            if not panels: raise RuntimeError("No viewport (modelPanel) found in Maya.")
            panel = panels[0]
        original_camera = self.cmds.modelEditor(panel, query=True, camera=True)
        try:
            self.cmds.modelEditor(panel, edit=True, camera=settings['camera'])
            mel_command = (
                'playblast -format image' f' -filename "{output_filename}"'
                ' -sequenceTime 0 -clearCache 1 -viewer 0 -showOrnaments 1 -fp 4'
                ' -percent 100 -compression "jpg" -quality 100 -widthHeight 1920 1080'
                f" -startTime {settings['start_frame']} -endTime {settings['end_frame']}"
                ' -offScreen'
            )
            mel.eval(mel_command)
        finally:
            self.cmds.modelEditor(panel, edit=True, camera=original_camera)