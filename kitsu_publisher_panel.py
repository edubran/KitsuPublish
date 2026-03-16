# kitsu_publisher_panel.py
# -*- coding: utf-8 -*-
#
# Kitsu Publisher
# Publish files and manage task status from Nuke, Maya, Houdini and Blender.
#
# Author : Eduardo Brandao <eduardo@bosonpost.com.br>
# License: MIT

import sys
import os
import json
import shutil
import subprocess
import time
from datetime import date

# ---------------------------------------------------------------------------
# CONFIG LOADER
# ---------------------------------------------------------------------------

_CONFIG_SEARCH_PATHS = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "kitsu_publisher_config.json"),
    os.path.join(os.path.expanduser("~"), ".kitsu_publisher_config.json"),
    os.path.join(os.path.expanduser("~"), "kitsu_publisher_config.json"),
]

def _load_config():
    """
    Load configuration from kitsu_publisher_config.json.
    Search order:
      1. Same folder as this script
      2. ~/.kitsu_publisher_config.json
      3. ~/kitsu_publisher_config.json
    Returns an empty dict if no config file is found.
    """
    for path in _CONFIG_SEARCH_PATHS:
        if os.path.isfile(path):
            try:
                with open(path, "r") as f:
                    cfg = json.load(f)
                print("KitsuPublisher: config loaded from " + path)
                return cfg
            except Exception as e:
                print("KitsuPublisher: failed to read config at " + path + " — " + str(e))
    print("KitsuPublisher: no config file found, using defaults.")
    return {}

CFG = _load_config()

# ---------------------------------------------------------------------------
# PATHS — add config-defined paths before importing gazu/requests
# ---------------------------------------------------------------------------

def ensure_paths():
    """Add config-defined paths to sys.path before importing gazu/requests."""
    for path in CFG.get("sys_paths", []):
        if path and path not in sys.path:
            sys.path.insert(0, path)

ensure_paths()

import requests
import gazu
import kitsu_context_detection
import kitsu_publisher_dcc_integrations

# ---------------------------------------------------------------------------
# KITSU HOST — set once from config, before any gazu call
# ---------------------------------------------------------------------------

_KITSU_HOST     = CFG.get("kitsu_host",     "http://localhost/api")
_KITSU_BASE_URL = CFG.get("kitsu_base_url", "http://localhost")

try:
    gazu.set_host(_KITSU_HOST)
    print("KitsuPublisher: Kitsu host set to " + _KITSU_HOST)
except Exception as e:
    print("KitsuPublisher: could not pre-configure Kitsu host — " + str(e))


USING_PYSIDE6 = False
try:
    from PySide6.QtWidgets import (QWidget, QVBoxLayout, QComboBox, QPushButton, QLabel, QFileDialog, QTextEdit, QMessageBox, QDialog, QLineEdit, QFormLayout, QDialogButtonBox, QTabWidget, QApplication, QProgressDialog, QListWidget, QStyleFactory, QSpinBox, QHBoxLayout, QCheckBox, QGroupBox, QSlider, QDoubleSpinBox)
    from PySide6.QtCore import Qt, Signal, QThread, QCoreApplication
    from PySide6.QtGui import QPalette, QColor
    USING_PYSIDE6 = True
except ImportError:
    from PySide2.QtWidgets import (QWidget, QVBoxLayout, QComboBox, QPushButton, QLabel, QFileDialog, QTextEdit, QMessageBox, QDialog, QLineEdit, QFormLayout, QDialogButtonBox, QTabWidget, QApplication, QProgressDialog, QListWidget, QStyleFactory, QSpinBox, QHBoxLayout, QCheckBox, QGroupBox, QSlider, QDoubleSpinBox)
    from PySide2.QtCore import Qt, Signal, QThread, QCoreApplication
    from PySide2.QtGui import QPalette, QColor

if USING_PYSIDE6:
    QT_WINDOW_FLAG, QT_HORIZONTAL, QT_ALIGN_CENTER, QT_WINDOW_MODAL = Qt.WindowType.Window, Qt.Orientation.Horizontal, Qt.AlignmentFlag.AlignCenter, Qt.WindowModality.WindowModal
    QT_DIALOG_OK_BUTTON, QT_DIALOG_CANCEL_BUTTON = QDialogButtonBox.StandardButton.Ok, QDialogButtonBox.StandardButton.Cancel
    QT_LINE_EDIT_PASSWORD, QT_APPLICATION_EXEC = QLineEdit.EchoMode.Password, QCoreApplication.exec
else:
    QT_WINDOW_FLAG, QT_HORIZONTAL, QT_ALIGN_CENTER, QT_WINDOW_MODAL = Qt.Window, Qt.Horizontal, Qt.AlignCenter, Qt.WindowModal
    QT_DIALOG_OK_BUTTON, QT_DIALOG_CANCEL_BUTTON = QDialogButtonBox.Ok, QDialogButtonBox.Cancel
    QT_LINE_EDIT_PASSWORD, QT_APPLICATION_EXEC = QLineEdit.Password, QCoreApplication.exec_

class KitsuWorker(QThread):
    finished, error, progress = Signal(object), Signal(str), Signal(int, int, str)
    def __init__(self, func, *args, **kwargs): super().__init__(); self.func, self.args, self.kwargs = func, args, kwargs
    def run(self):
        try: self.finished.emit(self.func(*self.args, **self.kwargs))
        except Exception as e:
            error_msg = str(e)
            if hasattr(e, 'response') and hasattr(e.response, 'json'):
                try: error_msg = e.response.json().get('detail', str(e))
                except Exception: pass
            self.error.emit(error_msg)

def notify_discord(task, user_info, file_paths, project_name, entity, entity_type, all_asset_types_from_publisher):
    """
    Send a publish notification to a Discord webhook.
    Only runs if 'discord_webhook_url' is set in kitsu_publisher_config.json.
    """
    webhook_url = CFG.get("discord_webhook_url", "")
    if not webhook_url:
        print("KitsuPublisher: Discord notification skipped (no webhook_url in config).")
        return
    kitsu_base_url = _KITSU_BASE_URL
    
    task_id = task.get("id")
    task_name = task.get("name", "Unknown Task")
    
    # Extract project ID from entity — most reliable source
    project_id = entity.get("project_id")
    entity_name = entity.get("name", "Unknown Entity")
    
    entity_type_lower = entity_type.lower()

    task_url = f"{kitsu_base_url}/tasks/{task_id}"  # safe fallback
    if project_id:
        if entity_type_lower == "shot":
            task_url = f"{kitsu_base_url}/productions/{project_id}/shots?task_id={task_id}"
        elif entity_type_lower == "asset":
            task_url = f"{kitsu_base_url}/productions/{project_id}/assets?task_id={task_id}"
    
    try:
        task_type_data = gazu.task.get_task_type(task["task_type_id"])
        task_type_name = task_type_data.get("name", "Unknown Type")
    except Exception as e: task_type_name = "Unknown Type"
    
    user = user_info.get("full_name", "Unknown User")
    file_names = [os.path.basename(p) for p in file_paths]
    files_text = "\n".join([f"📁 `{name}`" for name in file_names])
    files_header = f"**{len(file_names)} Files Published:**" if len(file_names) > 1 else "**File Published:**"
    content = (f"📦 **New Kitsu Publish!**\n"
               f"🧱 Project: **{project_name}**\n🔖 Type: **{entity_type}**\n🏷️ Name: **{entity_name}**\n"
               f"🎯 Task: [{task_type_name} / {task_name}]({task_url})\n"
               f"👤 Published by: {user}\n{files_header}\n{files_text}")
    try: requests.post(webhook_url, json={"content": content}).raise_for_status()
    except Exception as e: print(f"[DISCORD] Failed to send notification: {e}")

class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent); self.setWindowTitle("Kitsu Login")
        layout, self.email_input, self.password_input = QFormLayout(self), QLineEdit(self), QLineEdit(self)
        self.password_input.setEchoMode(QT_LINE_EDIT_PASSWORD)
        layout.addRow("Email:", self.email_input); layout.addRow("Password:", self.password_input)
        buttons = QDialogButtonBox(QT_DIALOG_OK_BUTTON | QT_DIALOG_CANCEL_BUTTON, QT_HORIZONTAL, self)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addRow(buttons)
    def get_credentials(self): return self.email_input.text(), self.password_input.text()

class KitsuPublisher(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Kitsu Publisher"); self.setObjectName("KitsuPublisher_Main_Window"); self.setWindowFlags(QT_WINDOW_FLAG); self.resize(500, 800)
        self.dcc_context, self.playblast_handler = kitsu_context_detection.get_dcc_context(), None
        if self.dcc_context == "maya": self.playblast_handler = kitsu_publisher_dcc_integrations.MayaPlayblast()
        elif self.dcc_context == "houdini": self.playblast_handler = kitsu_publisher_dcc_integrations.HoudiniPlayblast()
        self.kitsu_host = _KITSU_HOST
        self.worker, self.progress_dialog, self.is_logged_in = None, None, False
        self.authorized_statuses = CFG.get(
            "authorized_statuses",
            ["Waiting For Approval", "Work In Progress", "Slap Comp", "Published"]
        )
        self.user_tasks_details, self.show_only_user_tasks = [], True
        self.all_asset_types_names = set()
        self.projects, self.statuses, self.selected_files = [], [], []
        self.assets_cache, self.shots_cache, self.asset_tasks_cache, self.shot_tasks_cache = {}, {}, {}, {}
        self.current_kitsu_entity, self.current_kitsu_task, self.current_entity_type = None, None, ""
        main_layout = QVBoxLayout(self)
        self.login_status_label, self.login_button = QLabel("Not connected"), QPushButton("Kitsu Login")
        main_layout.addWidget(self.login_status_label); main_layout.addWidget(self.login_button)
        context_group = QGroupBox("Current Selection"); context_layout = QFormLayout(context_group)
        self.context_project_label, self.context_entity_label, self.context_task_label = QLabel("None"), QLabel("None"), QLabel("None")
        context_layout.addRow("Project:", self.context_project_label); context_layout.addRow("Entity:", self.context_entity_label); context_layout.addRow("Task:", self.context_task_label)
        main_layout.addWidget(context_group)
        self.filter_checkbox = QCheckBox("Show only my tasks"); self.filter_checkbox.setChecked(True); self.filter_checkbox.setEnabled(False)
        main_layout.addWidget(self.filter_checkbox)
        self.project_box = QComboBox(); self.project_box.setDisabled(True)
        main_layout.addWidget(QLabel("Project")); main_layout.addWidget(self.project_box)
        self.tab_widget = QTabWidget(); self.tab_widget.setDisabled(True)
        self.asset_tab, self.shot_tab = QWidget(), QWidget()
        self.playblast_tab = self.create_playblast_tab()
        self.tab_widget.addTab(self.asset_tab, "Asset"); self.tab_widget.addTab(self.shot_tab, "Shot"); self.tab_widget.addTab(self.playblast_tab, "Playblast")
        main_layout.addWidget(self.tab_widget)
        asset_layout = QVBoxLayout(self.asset_tab)
        self.asset_box = QComboBox(); asset_layout.addWidget(QLabel("Asset")); asset_layout.addWidget(self.asset_box)
        self.asset_task_box = QComboBox(); asset_layout.addWidget(QLabel("Task (Asset)")); asset_layout.addWidget(self.asset_task_box)
        asset_layout.addStretch()
        shot_layout = QVBoxLayout(self.shot_tab)
        self.shot_box = QComboBox(); shot_layout.addWidget(QLabel("Shot")); shot_layout.addWidget(self.shot_box)
        self.shot_task_box = QComboBox(); shot_layout.addWidget(QLabel("Task (Shot)")); shot_layout.addWidget(self.shot_task_box)
        shot_layout.addStretch()
        time_group = QGroupBox("Time spent on Task")
        time_layout = QVBoxLayout(time_group)
        h_time_lay = QHBoxLayout()
        self.time_slider = QSlider(QT_HORIZONTAL); self.time_slider.setRange(0, 48)
        self.time_spin = QDoubleSpinBox(); self.time_spin.setRange(0.0, 12.0); self.time_spin.setSingleStep(0.25); self.time_spin.setSuffix(" h")
        h_time_lay.addWidget(self.time_slider); h_time_lay.addWidget(self.time_spin)
        time_layout.addLayout(h_time_lay)
        self.time_checkbox = QCheckBox("Log time to Kitsu"); self.time_checkbox.setChecked(True); time_layout.addWidget(self.time_checkbox)
        main_layout.addWidget(time_group)
        self.status_box = QComboBox(); self.status_box.setDisabled(True)
        self.comment_box = QTextEdit(); self.comment_box.setDisabled(True)
        self.file_list = QListWidget(); self.file_list.setDisabled(True)
        self.choose_file_button = QPushButton("Choose Files — MP4 PNG JPG"); self.choose_file_button.setDisabled(True)
        self.publish_button = QPushButton("Publish Selected Files"); self.publish_button.setDisabled(True)
        main_layout.addWidget(QLabel("Status")); main_layout.addWidget(self.status_box)
        main_layout.addWidget(QLabel("Comment")); main_layout.addWidget(self.comment_box)
        main_layout.addWidget(QLabel("Files to Upload")); main_layout.addWidget(self.file_list)
        main_layout.addWidget(self.choose_file_button); main_layout.addWidget(self.publish_button)
        self.login_button.clicked.connect(self.attempt_login)
        self.filter_checkbox.stateChanged.connect(self.toggle_task_filter)
        self.project_box.currentIndexChanged.connect(self.load_context)
        self.tab_widget.currentChanged.connect(self.on_tab_changed)
        self.asset_box.currentIndexChanged.connect(self.load_asset_tasks)
        self.shot_box.currentIndexChanged.connect(self.load_shot_tasks)
        self.asset_task_box.currentIndexChanged.connect(self.on_task_selected)
        self.shot_task_box.currentIndexChanged.connect(self.on_task_selected)
        self.choose_file_button.clicked.connect(self.choose_files)
        self.publish_button.clicked.connect(self.publish_to_kitsu)
        self.time_slider.valueChanged.connect(lambda v: self.time_spin.setValue(v * 0.25))
        self.time_spin.valueChanged.connect(lambda v: self.time_slider.setValue(int(v / 0.25)))
        self.apply_stylesheet_to_window(); self.check_existing_session()

    def apply_stylesheet_to_window(self):
        self.setStyle(QStyleFactory.create("Fusion"))
        self.setStyleSheet("QWidget { background-color: #2d2d2d; color: #ffffff; font-size: 9pt; } QWidget:disabled { color: #7f7f7f; } QGroupBox { border: 1px solid #444444; border-radius: 4px; margin-top: 1ex; padding-top: 10px; } QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top center; padding: 0 5px; } QTabWidget::pane { border: 1px solid #444444; } QTabBar::tab { background-color: #353535; padding: 5px 10px; border: 1px solid #444444; border-bottom: none; } QTabBar::tab:selected { background-color: #444444; } QPushButton { background-color: #353535; border: 1px solid #555555; border-radius: 4px; padding: 5px; } QPushButton:hover { background-color: #454545; } QPushButton:pressed { background-color: #2a82da; } QPushButton:disabled { background-color: #2d2d2d; border-color: #444444; } QComboBox, QLineEdit, QTextEdit, QSpinBox { background-color: #1a1a1a; border: 1px solid #555555; border-radius: 4px; padding: 3px; } QListWidget { background-color: #1a1a1a; border: 1px solid #555555; } QListWidget::item:selected, QComboBox QAbstractItemView::item:selected { background-color: #2a82da; }")
    
    def on_task_selected(self):
        sender, task, entity, entity_type = self.sender(), None, None, ""
        if not sender: return
        current_tab_text = self.tab_widget.tabText(self.tab_widget.currentIndex())
        if sender == self.asset_task_box and current_tab_text == "Asset": task, entity, entity_type = self.asset_task_box.currentData(), self.asset_box.currentData(), "Asset"
        elif sender == self.shot_task_box and current_tab_text == "Shot": task, entity, entity_type = self.shot_task_box.currentData(), self.shot_box.currentData(), "Shot"
        else: return
        project = self.project_box.currentData()
        if task and entity and project:
            self.current_kitsu_task, self.current_kitsu_entity, self.current_entity_type = task, entity, entity_type
            self.context_project_label.setText(f"<b style='color:#aaddff;'>{project.get('name', 'N/A')}</b>")
            self.context_entity_label.setText(f"<b style='color:#aaddff;'>{entity.get('name', 'N/A')} ({entity_type})</b>")
            self.context_task_label.setText(f"<b style='color:#aaddff;'>{task.get('task_type_name', 'N/A')} / {task.get('name', 'N/A')}</b>")
        else:
            self.current_kitsu_task, self.current_kitsu_entity, self.current_entity_type = None, None, ""
            self.context_project_label.setText("None"); self.context_entity_label.setText("None"); self.context_task_label.setText("None")

    def create_playblast_tab(self):
        playblast_widget = QWidget()
        playblast_layout = QVBoxLayout(playblast_widget)
        if not self.playblast_handler:
            playblast_widget.setEnabled(False)
            disabled_label = QLabel(f"Playblast is not supported in '{self.dcc_context}'."); disabled_label.setAlignment(QT_ALIGN_CENTER)
            playblast_layout.addWidget(disabled_label); return playblast_widget
        settings_group = QGroupBox("Playblast Settings"); settings_layout = QFormLayout(settings_group)
        self.playblast_camera_combo = QComboBox()
        self.playblast_start_frame, self.playblast_end_frame = QSpinBox(), QSpinBox()
        self.playblast_start_frame.setRange(-10000, 10000); self.playblast_end_frame.setRange(-10000, 10000)
        frame_layout = QHBoxLayout(); frame_layout.addWidget(QLabel("Start:")); frame_layout.addWidget(self.playblast_start_frame)
        frame_layout.addWidget(QLabel("End:")); frame_layout.addWidget(self.playblast_end_frame)
        settings_layout.addRow("Camera:", self.playblast_camera_combo); settings_layout.addRow("Frame Range:", frame_layout)
        playblast_layout.addWidget(settings_group)
        output_group = QGroupBox("Output"); output_layout = QFormLayout(output_group)
        self.playblast_output_path, self.playblast_filename = QLineEdit(), QLineEdit()
        self.playblast_browse_btn = QPushButton("Browse"); self.playblast_browse_btn.clicked.connect(self.browse_playblast_folder)
        path_layout = QHBoxLayout(); path_layout.addWidget(self.playblast_output_path); path_layout.addWidget(self.playblast_browse_btn)
        output_layout.addRow("Output Folder:", path_layout); output_layout.addRow("File Name:", self.playblast_filename)
        playblast_layout.addWidget(output_group)
        self.generate_playblast_btn = QPushButton("Generate Playblast and Publish")
        self.generate_playblast_btn.setFixedHeight(40); self.generate_playblast_btn.clicked.connect(self.generate_playblast_and_publish)
        playblast_layout.addWidget(self.generate_playblast_btn); playblast_layout.addStretch()
        return playblast_widget

    def on_tab_changed(self, index):
        self.load_context();
        if self.tab_widget.tabText(index) == "Playblast": self.initialize_playblast_tab()

    def initialize_playblast_tab(self):
        if not self.playblast_handler or not self.is_logged_in: return
        print("KitsuPublisher: initializing Playblast tab.")
        try:
            self.playblast_camera_combo.clear(); self.playblast_camera_combo.addItems(self.playblast_handler.get_cameras())
            start, end = self.playblast_handler.get_frame_range()
            self.playblast_start_frame.setValue(int(start)); self.playblast_end_frame.setValue(int(end))
            defaults = self.playblast_handler.get_output_defaults()
            self.playblast_output_path.setText(defaults['path']); self.playblast_filename.setText(defaults['filename'])
        except Exception as e: print(f"KitsuPublisher: error initializing Playblast tab: {e}"); self.playblast_tab.setEnabled(False)
    
    def browse_playblast_folder(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Output Folder", self.playblast_output_path.text())
        if directory: self.playblast_output_path.setText(directory)

    def generate_playblast_and_publish(self):
        if not self.playblast_handler: return
        task, entity, entity_type = self.current_kitsu_task, self.current_kitsu_entity, self.current_entity_type
        if not (task and entity):
            QMessageBox.warning(self, "Incomplete Kitsu Context", "Please select a Project, Entity and Task before generating a playblast."); return
        status, comment_text = self.status_box.currentData(), self.comment_box.toPlainText().strip()
        if not status: QMessageBox.warning(self, "Missing Status", "Please select a Status before publishing."); return
        output_dir, base_filename = self.playblast_output_path.text(), self.playblast_filename.text().replace(".mp4", "")
        temp_frame_dir = os.path.join(output_dir, f"{base_filename}_temp_frames")
        if os.path.exists(temp_frame_dir): shutil.rmtree(temp_frame_dir)
        os.makedirs(temp_frame_dir, exist_ok=True)
        settings = {"camera": self.playblast_camera_combo.currentText(), "start_frame": self.playblast_start_frame.value(),
            "end_frame": self.playblast_end_frame.value(), "image_seq_pattern": os.path.join(temp_frame_dir, f"{base_filename}.$F4.jpg"),
            "ffmpeg_input_pattern": os.path.join(temp_frame_dir, f"{base_filename}.%04d.jpg").replace("\\", "/"),
            "output_mp4_filepath": os.path.join(output_dir, f"{base_filename}.mp4"), "frame_rate": 24}
        try:
            self.show_progress("Generating playblast frames...")
            self.playblast_handler.generate_frames(settings)
            self.show_progress("Converting to MP4...")
            self.playblast_handler.convert_to_mp4(settings)
            self.show_progress("Publishing to Kitsu...")
            self.run_kitsu_task(self._perform_multiple_publish, task, status, comment_text or " ", [settings['output_mp4_filepath']], entity_type, entity)
            time.sleep(3)  # brief pause before cleanup
            shutil.rmtree(temp_frame_dir)
        except Exception as e:
            self.hide_progress(); QMessageBox.critical(self, f"Playblast Error ({self.dcc_context})", str(e))
            if os.path.exists(temp_frame_dir):
                try: time.sleep(3); shutil.rmtree(temp_frame_dir)
                except Exception as e_clean: print(f"KitsuPublisher: could not clean temp folder: {e_clean}")

    def toggle_task_filter(self, state):
        """Toggle between showing all tasks or only the current user's tasks."""
        self.show_only_user_tasks = bool(state)
        print(f"User task filter: {'enabled' if self.show_only_user_tasks else 'disabled'}")
        self.load_context()

    def check_existing_session(self):
        try:
            gazu.client.get_current_user()
            print("KitsuPublisher: active Kitsu session found."); self.is_logged_in = True; self.enable_ui(False)
            self.run_kitsu_task(self._fetch_initial_data)
        except Exception as e:
            print(f"KitsuPublisher: no active session ({e}). Attempting auto-login.")
            self.is_logged_in = False; self.attempt_login(silent_fail=True)

    def attempt_login(self, silent_fail=False):
        if self.is_logged_in: self.logout(); return
        try:
            _env_user = CFG.get("env_user_var", "KITSU_USER")
            _env_pass = CFG.get("env_pass_var", "KITSU_PASS")
            email, password = os.getenv(_env_user), os.getenv(_env_pass)
            if not (email and password):
                if silent_fail: print("KitsuPublisher: KITSU env variables not set."); return
                dialog = LoginDialog(self)
                if dialog.exec() if USING_PYSIDE6 else dialog.exec_(): email, password = dialog.get_credentials()
                else: print("KitsuPublisher: login cancelled."); return
            if email and password: self.enable_ui(False); self.run_kitsu_task(self._perform_login, email, password)
            elif not silent_fail: QMessageBox.warning(self, "Invalid Input", "Email and password cannot be empty.")
        except Exception as e: QMessageBox.critical(self, "Login Error", f"An unexpected error occurred: {e}"); self.enable_ui(True)

    def _perform_login(self, email, password):
        gazu.set_host(self.kitsu_host)
        gazu.log_in(email, password)
        return self._fetch_initial_data()

    def _fetch_initial_data(self):
        if gazu.client.get_host() != self.kitsu_host:
             gazu.set_host(self.kitsu_host)
        projects = gazu.project.all_open_projects()
        statuses = gazu.task.all_task_statuses()
        user_info = gazu.client.get_current_user()
        
        # Fetch all asset types to classify tasks correctly
        all_asset_types_names = set()
        try:
            asset_types = gazu.asset.all_asset_types()
            for atype in asset_types:
                if atype["name"] and atype["name"].lower() not in ['', '_exemplo de andamento_']: # Remova explicitamente strings vazias e exemplos
                    all_asset_types_names.add(atype["name"].lower())
        except Exception as e:
            all_asset_types_names = set()

        user_tasks_details = []
        try:
            raw_user_tasks = gazu.user.all_tasks_to_do()
            for task_data in raw_user_tasks:
    
                try:
                    entity_id = task_data.get("entity_id")
                    project_id = task_data.get("project_id")
                    entity_type_id = task_data.get("entity_type_id")
                    entity_type_name = task_data.get("entity_type_name")

                    # If entity_type_name wasn't in task_data, resolve via entity_type_id
                    if not entity_type_name and entity_type_id:
                        entity_type_obj = gazu.entity.get_entity_type(entity_type_id)
                        if entity_type_obj:
                            entity_type_name = entity_type_obj["name"]
                        else:
                            continue  # cannot classify task without entity type

                    # if entity_type_name is still unknown, skip this task
                    if not entity_type_name:
                        continue

                    # Resolve the full entity object (Asset or Shot)
                    resolved_entity_obj = None
                    if entity_type_name.lower() in all_asset_types_names:
                        if entity_id:
                            try:
                                resolved_entity_obj = gazu.asset.get_asset(entity_id)
                            except Exception as e:
                                print(f"KitsuPublisher: error fetching asset {entity_id}: {e}")
                    elif entity_type_name.lower() == "shot":
                        if entity_id:
                            try:
                                resolved_entity_obj = gazu.shot.get_shot(entity_id)
                            except Exception as e:
                                print(f"KitsuPublisher: error fetching shot {entity_id}: {e}")


                    # Update task_data with resolved entity info
                    if resolved_entity_obj:
                        entity_id   = resolved_entity_obj["id"]
                        project_id  = resolved_entity_obj["project_id"]
                        task_data["entity_id"]                  = entity_id
                        task_data["project_id"]                 = project_id
                        task_data["entity_type_name_resolved"]  = entity_type_name

                    # Only keep tasks where all essential info is available
                    if entity_id and project_id and entity_type_name:
                        task_data["entity_type_name_resolved"] = entity_type_name
                        user_tasks_details.append(task_data)

                except Exception as e_task_process:
                    print(f"KitsuPublisher: error processing task {task_data.get('id')}: {e_task_process}")

        except Exception as e:
            print(f"KitsuPublisher: error fetching user tasks: {e}")
            user_tasks_details = []
        
        return "login_success", {
            "projects": projects, 
            "statuses": statuses, 
            "user": user_info,
            "user_tasks_details": user_tasks_details,
            "all_asset_types_names": list(all_asset_types_names)
        }

    def _handle_login_success(self, data):
        self.is_logged_in = True
        self.projects = data.get("projects", [])
        self.statuses = data.get("statuses", [])
        user_info = data.get("user", {})
        
        self.user_tasks_details = data.get("user_tasks_details", [])
        self.all_asset_types_names = set(data.get("all_asset_types_names", []))

        self.project_box.clear()
        if self.projects:
            self.project_box.addItem("-- Select a Project --", None)
            for project in self.projects:
                self.project_box.addItem(project["name"], project)
            self.project_box.setEnabled(True)
        else:
            self.project_box.setDisabled(True)
        self.status_box.clear()
        if self.statuses:
            self.status_box.addItem("-- Select a Status --", None)
            for status in self.statuses:
                if status["name"] in self.authorized_statuses:
                    self.status_box.addItem(status["name"], status)
            self.status_box.setEnabled(True)
        else:
            self.status_box.setDisabled(True)
        self.login_status_label.setText(f"Logged in as {gazu.client.get_current_user()['full_name']}")
        try: self.login_button.clicked.disconnect() 
        except: pass
        self.login_button.clicked.connect(self.logout)
        self.tab_widget.setEnabled(True)
        self.comment_box.setEnabled(True)
        self.choose_file_button.setEnabled(True)
        self.file_list.setEnabled(True)
        self.publish_button.setEnabled(True)
        
        self.filter_checkbox.setEnabled(True)
        
        self.enable_ui(True)
        self.load_context()

    def logout(self):
        gazu.client.host = gazu.client.auth = gazu.client.access_token = gazu.client.refresh_token = None
        self.is_logged_in = False
        self.projects, self.statuses, self.selected_files, self.user_tasks_details = [], [], [], []
        self.assets_cache, self.shots_cache, self.asset_tasks_cache, self.shot_tasks_cache = {}, {}, {}, {}
        self.all_asset_types_names = set()
        self.project_box.clear(); self.asset_box.clear(); self.shot_box.clear()
        self.asset_task_box.clear(); self.shot_task_box.clear(); self.status_box.clear()
        self.comment_box.clear(); self.file_list.clear(); self.on_task_selected()
        self.login_status_label.setText("Not connected"); self.login_button.setText("Kitsu Login")
        try: self.login_button.clicked.disconnect()
        except: pass
        self.login_button.clicked.connect(self.attempt_login)
        self.enable_ui(True)

    def run_kitsu_task(self, func, *args, **kwargs):
        if self.worker and self.worker.isRunning(): QMessageBox.warning(self, "Busy", "Another Kitsu operation is already running."); return
        self.show_progress("Processing..."); self.worker = KitsuWorker(func, *args, **kwargs)
        self.worker.finished.connect(self.on_kitsu_task_finished); self.worker.error.connect(self.on_kitsu_task_error)
        self.worker.progress.connect(self.update_progress); self.worker.start()

    def show_progress(self, message):
        if not self.progress_dialog:
            self.progress_dialog = QProgressDialog(message, "Cancel", 0, 100, self)
            self.progress_dialog.setWindowModality(QT_WINDOW_MODAL); self.progress_dialog.setAutoClose(False)
            self.progress_dialog.setAutoReset(False); self.progress_dialog.canceled.connect(self.cancel_kitsu_task)
        self.progress_dialog.setLabelText(message); self.progress_dialog.setValue(0); self.progress_dialog.show()

    def update_progress(self, current, total, message):
        if self.progress_dialog: self.progress_dialog.setValue(int((current/total)*100) if total > 0 else 0); self.progress_dialog.setLabelText(message)
    def hide_progress(self):
        if self.progress_dialog: self.progress_dialog.hide()
    def cancel_kitsu_task(self):
        if self.worker and self.worker.isRunning():
            try: self.worker.finished.disconnect(); self.worker.error.disconnect(); self.worker.progress.disconnect()
            except: pass
        self.hide_progress(); self.enable_ui(True)

    def on_kitsu_task_finished(self, result):
        self.hide_progress(); self.enable_ui(True)
        if isinstance(result, tuple) and len(result) > 1 and result[0] == "login_success": self._handle_login_success(result[1])
        elif isinstance(result, tuple) and len(result) > 1 and result[0] == "publish_success":
            QMessageBox.information(self, "Success", f"Publish complete! {result[1].get('success_count', 0)} file(s) published.")
            self.comment_box.clear(); self.file_list.clear(); self.selected_files = []
            # reset time controls after publish
            self.time_slider.setValue(0); self.time_spin.setValue(0.0)

    def on_kitsu_task_error(self, error_message):
        self.hide_progress(); self.enable_ui(True)
        QMessageBox.critical(self, "Kitsu Error", error_message)
        if "Authentication failed" in error_message or "Could not log in" in error_message: self.logout()

    def enable_ui(self, enabled):
        self.login_button.setEnabled(enabled)
        logged_in_and_enabled = self.is_logged_in and enabled
        self.project_box.setEnabled(logged_in_and_enabled and bool(self.projects))
        self.tab_widget.setEnabled(logged_in_and_enabled and self.project_box.currentData() is not None)
        self.status_box.setEnabled(logged_in_and_enabled and bool(self.statuses) and self.status_box.count() > 1)
        self.comment_box.setEnabled(logged_in_and_enabled)
        self.choose_file_button.setEnabled(logged_in_and_enabled)
        self.file_list.setEnabled(logged_in_and_enabled)
        self.filter_checkbox.setEnabled(logged_in_and_enabled)
        can_publish = (self.asset_task_box.currentData() or self.shot_task_box.currentData()) and self.status_box.currentData() and self.selected_files
        self.publish_button.setEnabled(logged_in_and_enabled and bool(can_publish))

    def load_context(self):
        if not self.is_logged_in: return
        project = self.project_box.currentData()
        self.tab_widget.setEnabled(project is not None)
        if not project:
            self.asset_box.clear()
            self.asset_task_box.clear()
            self.shot_box.clear()
            self.shot_task_box.clear()
            self.enable_ui(True)
            return
        current_tab_index = self.tab_widget.currentIndex()
        if current_tab_index == 0:
            self.load_assets(project)
        elif current_tab_index == 1:
            self.load_shots(project)
        self.enable_ui(True)

    def load_assets(self, project):
        self.asset_box.clear()
        self.asset_task_box.clear()
        project_id = project["id"]

        if not self.show_only_user_tasks and project_id in self.assets_cache:
            all_project_assets = self.assets_cache[project_id]
        else:
            try:
                all_project_assets = gazu.asset.all_assets_for_project(project)
                self.assets_cache[project_id] = all_project_assets
            except Exception as e:
                self.on_kitsu_task_error(f"Error loading Assets: {e}")
                self.enable_ui(True)
                return

        self.asset_box.addItem("-- Select an Asset --", None)

        if self.show_only_user_tasks and self.user_tasks_details:
            user_asset_ids = set()
            for td in self.user_tasks_details:
                if (td.get("project_id") == project_id
                        and td.get("entity_type_name_resolved", "").lower() in self.all_asset_types_names
                        and td.get("entity_id")):
                    user_asset_ids.add(td["entity_id"])
            filtered = [a for a in all_project_assets if a["id"] in user_asset_ids]
            for asset in filtered:
                self.asset_box.addItem(asset["name"], asset)
            print(f"KitsuPublisher: showing {len(filtered)} of {len(all_project_assets)} assets for {project['name']}")
        else:
            for asset in all_project_assets:
                self.asset_box.addItem(asset["name"], asset)
        self.enable_ui(True)

    def load_shots(self, project):
        self.shot_box.clear()
        self.shot_task_box.clear()
        project_id = project["id"]

        if not self.show_only_user_tasks and project_id in self.shots_cache:
            all_project_shots = self.shots_cache[project_id]
        else:
            try:
                sequences = gazu.shot.all_sequences_for_project(project)
                all_project_shots = []
                for seq in sequences:
                    for shot in gazu.shot.all_shots_for_sequence(seq):
                        shot["sequence_name"] = seq["name"]
                        all_project_shots.append(shot)
                self.shots_cache[project_id] = all_project_shots
            except Exception as e:
                self.on_kitsu_task_error(f"Error loading Shots: {e}")
                self.enable_ui(True)
                return

        self.shot_box.addItem("-- Select a Shot --", None)

        if self.show_only_user_tasks and self.user_tasks_details:
            user_shot_ids = set()
            for td in self.user_tasks_details:
                if (td.get("project_id") == project_id
                        and td.get("entity_type_name_resolved", "").lower() == "shot"
                        and td.get("entity_id")):
                    user_shot_ids.add(td["entity_id"])
            filtered = [s for s in all_project_shots if s["id"] in user_shot_ids]
            for shot in filtered:
                self.shot_box.addItem(f"{shot['sequence_name']} / {shot['name']}", shot)
            print(f"KitsuPublisher: showing {len(filtered)} of {len(all_project_shots)} shots for {project.get('name', '')}")
        else:
            for shot in all_project_shots:
                self.shot_box.addItem(f"{shot['sequence_name']} / {shot['name']}", shot)
        self.enable_ui(True)

    def load_asset_tasks(self):
        self.asset_task_box.clear()
        asset = self.asset_box.currentData()
        if not asset:
            self.enable_ui(True)
            return

        asset_id = asset["id"]
        if not self.show_only_user_tasks and asset_id in self.asset_tasks_cache:
            all_asset_tasks = self.asset_tasks_cache[asset_id]
        else:
            try:
                all_asset_tasks = gazu.task.all_tasks_for_asset(asset)
                self.asset_tasks_cache[asset_id] = all_asset_tasks
            except Exception as e:
                self.on_kitsu_task_error(f"Error loading Asset Tasks: {e}")
                self.enable_ui(True)
                return

        self.asset_task_box.addItem("-- Select a Task --", None)

        if self.show_only_user_tasks and self.user_tasks_details:
            user_task_ids = {td.get("id") for td in self.user_tasks_details if td.get("entity_id") == asset_id}
            filtered = [t for t in all_asset_tasks if t["id"] in user_task_ids]
            for task in filtered:
                task_type = gazu.task.get_task_type(task["task_type_id"])
                self.asset_task_box.addItem(f"{task_type['name']} ({task['name']})", task)
            print(f"KitsuPublisher: showing {len(filtered)} of {len(all_asset_tasks)} asset tasks for {asset.get('name', '')}")
        else:
            for task in all_asset_tasks:
                task_type = gazu.task.get_task_type(task["task_type_id"])
                self.asset_task_box.addItem(f"{task_type['name']} ({task['name']})", task)
        self.enable_ui(True)

    def load_shot_tasks(self):
        self.shot_task_box.clear()
        shot = self.shot_box.currentData()
        if not shot:
            self.enable_ui(True)
            return

        shot_id = shot["id"]
        if not self.show_only_user_tasks and shot_id in self.shot_tasks_cache:
            all_shot_tasks = self.shot_tasks_cache[shot_id]
        else:
            try:
                all_shot_tasks = gazu.task.all_tasks_for_shot(shot)
                self.shot_tasks_cache[shot_id] = all_shot_tasks
            except Exception as e:
                self.on_kitsu_task_error(f"Error loading Shot Tasks: {e}")
                self.enable_ui(True)
                return

        self.shot_task_box.addItem("-- Select a Task --", None)

        if self.show_only_user_tasks and self.user_tasks_details:
            user_task_ids = {td.get("id") for td in self.user_tasks_details if td.get("entity_id") == shot_id}
            filtered = [t for t in all_shot_tasks if t["id"] in user_task_ids]
            for task in filtered:
                task_type = gazu.task.get_task_type(task["task_type_id"])
                self.shot_task_box.addItem(f"{task_type['name']} ({task['name']})", task)
            print(f"KitsuPublisher: showing {len(filtered)} of {len(all_shot_tasks)} shot tasks for {shot.get('name', '')}")
        else:
            for task in all_shot_tasks:
                task_type = gazu.task.get_task_type(task["task_type_id"])
                self.shot_task_box.addItem(f"{task_type['name']} ({task['name']})", task)
        self.enable_ui(True)

    def choose_files(self):
        file_filter = "Supported Files (*.mp4 *.jpg *.jpeg *.png);;Videos (*.mp4);;Images (*.jpg *.jpeg *.png)"
        file_paths, _ = QFileDialog.getOpenFileNames(self, "Choose Files", "", file_filter)
        if file_paths:
            self.selected_files = file_paths
            self.file_list.clear()
            for file_path in file_paths:
                self.file_list.addItem(os.path.basename(file_path))
        self.enable_ui(True)


    def publish_to_kitsu(self):
        if not self.is_logged_in: return
        task, entity, entity_type = self.current_kitsu_task, self.current_kitsu_entity, self.current_entity_type
        status, comment = self.status_box.currentData(), self.comment_box.toPlainText().strip()
        if not (task and status and self.selected_files):
            QMessageBox.warning(self, "Error", "Please select a Task, Status and at least one file."); return
        # read duration only if timesheet checkbox is checked
        duration_hours = self.time_spin.value() if self.time_checkbox.isChecked() else 0.0
        self.enable_ui(False)
        self.run_kitsu_task(self._perform_multiple_publish, task, status, comment or " ", self.selected_files, entity_type, entity, duration_hours)

    def _perform_multiple_publish(self, task, status, comment_text, file_paths, entity_type, entity, duration_hours=0.0):
        results = {"success": [], "failed": []}
        comment = gazu.task.add_comment(task, status, comment_text)
        # log time before uploading previews
        if duration_hours > 0:
            try:
                duration_minutes = int(duration_hours * 60)
                gazu.task.add_time_spent(task, gazu.client.get_current_user(), date.today(), duration_minutes)
                print(f"KitsuPublisher: logged {duration_hours}h ({duration_minutes} min) for task {task.get('id')}.")
            except Exception as e:
                print(f"KitsuPublisher: failed to log time: {e}")
        for i, fpath in enumerate(file_paths):
            try:
                if hasattr(self.worker, 'progress'): self.worker.progress.emit(i, len(file_paths), f"Publicando {os.path.basename(fpath)}")
                preview = gazu.task.add_preview(task, comment, fpath)
                if i == 0: gazu.task.set_main_preview(preview)
                results["success"].append({"file_path": fpath})
            except Exception as e: results["failed"].append({"file_path": fpath, "error": str(e)})
        if results["success"]:
            project_name = gazu.project.get_project(entity["project_id"])["name"] if entity else "Unknown"
            notify_discord(task, gazu.client.get_current_user(), [item['file_path'] for item in results['success']], project_name, entity, entity_type, self.all_asset_types_names)
        return "publish_success", {"success_count": len(results["success"]), "results": results}

    def closeEvent(self, event):
        print("KitsuPublisher: closing window.")
        self.deleteLater(); event.accept()

def get_main_dcc_window():
    context = kitsu_context_detection.get_dcc_context()
    if context == 'maya':
        try:
            try: from shiboken6 import wrapInstance
            except ImportError: from shiboken2 import wrapInstance
            import maya.OpenMayaUI as omui
            main_window_ptr = omui.MQtUtil.mainWindow(); return wrapInstance(int(main_window_ptr), QWidget)
        except Exception as e: print(f"KitsuPublisher: could not get Maya main window: {e}")
    elif context == 'nuke':
        try:
            for widget in QApplication.instance().allWidgets():
                if widget.inherits('QMainWindow') and 'Nuke' in widget.windowTitle(): return widget
        except Exception as e: print(f"KitsuPublisher: could not get Nuke main window: {e}")
    elif context == 'houdini':
        try:
            import hou; return hou.qt.mainWindow()
        except Exception as e: print("KitsuPublisher: could not get Houdini main window: " + str(e))
    elif context == 'blender':
        return None  # Blender manages its own event loop; panel floats
    return None

def show_kitsu_publisher():
    main_window = get_main_dcc_window()
    if main_window:
        for child in main_window.findChildren(QWidget, "KitsuPublisher_Main_Window"):
            print(f"KitsuPublisher: closing previous instance: {child}")
            child.close(); child.deleteLater()
    app = QApplication.instance()
    if not app: app = QApplication(sys.argv)
    instance = KitsuPublisher(parent=main_window)
    instance.show()
    if kitsu_context_detection.get_dcc_context() == 'standalone':
        app.exec_() if not USING_PYSIDE6 else app.exec()
