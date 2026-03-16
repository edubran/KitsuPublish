# Author : Eduardo Brandao <eduardo@bosonpost.com.br>
# License: MIT
# Kitsu Publisher

A publish tool for artists integrated with [Kitsu](https://www.cg-wire.com/kitsu) via [gazu](https://github.com/cgwire/gazu).

Publish files, change task status and send Discord notifications directly from **Nuke**, **Maya**, **Houdini**, **Blender** and standalone Python — a single file, one config.

![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Python: 3.x](https://img.shields.io/badge/python-3.x-blue)

---

## Features

- Publish files to Kitsu tasks (Assets, Shots and Playblast)
- Change task status on publish
- Filter tasks to show only your own assignments
- Log time (timesheet) directly from the publish dialog
- Playblast generation for Maya and Houdini with automatic MP4 conversion via FFmpeg
- Optional Discord notification on every publish
- Auto-login via environment variables
- Fully configurable via a JSON file — no code changes needed

---

## Requirements

| Dependency | How to get it |
|---|---|
| [gazu](https://github.com/cgwire/gazu) | `pip install gazu` or copy the `gazu/` folder next to the scripts |
| [requests](https://pypi.org/project/requests/) | usually bundled with gazu; `pip install requests` otherwise |
| PySide2 or PySide6 | provided by your DCC; install PySide2 for standalone use |
| FFmpeg *(Playblast only)* | [ffmpeg.org](https://ffmpeg.org/download.html) — must be in PATH or `C:\ffmpeg\bin\` on Windows |

---

## Installation

### 1 — Copy the files

```
your_pipeline_folder/
├── kitsu_publisher_panel.py
├── kitsu_publisher_launch.py
├── kitsu_publisher_dcc_integrations.py
├── kitsu_publisher_config.json        ← edit this
├── kitsu_context_detection.py
├── gazu/                              ← gazu library folder (or installed via pip)
└── requests/                          ← requests library folder (or installed via pip)
```

> **Tip:** if `gazu` and `requests` are installed system-wide via `pip`, you can leave out those folders and remove them from `sys_paths` in the config.

---

### 2 — Edit `kitsu_publisher_config.json`

```json
{
    "kitsu_host":     "https://your-kitsu-server.com/api",
    "kitsu_base_url": "https://your-kitsu-server.com",

    "env_user_var": "KITSU_USER",
    "env_pass_var": "KITSU_PASS",

    "sys_paths": [
        "/path/to/your_pipeline_folder",
        "/path/to/your_pipeline_folder/gazu",
        "/path/to/your_pipeline_folder/requests"
    ],

    "authorized_statuses": [
        "Waiting For Approval",
        "Work In Progress",
        "Slap Comp",
        "Published"
    ],

    "discord_webhook_url": ""
}
```

**`authorized_statuses`** — status names shown in the publish dropdown. Must match your Kitsu server exactly (check *Settings → Task Statuses* in Kitsu).

**`discord_webhook_url`** — paste your Discord webhook URL here to enable publish notifications. Leave empty to disable. See [Discord docs](https://support.discord.com/hc/en-us/articles/228383668) to create a webhook.

---

### 3 — Set environment variables for auto-login

| Variable | Value |
|---|---|
| `KITSU_USER` | your Kitsu email |
| `KITSU_PASS` | your Kitsu password |

Set them in your OS, render farm or DCC launch script. If they are not set, the publisher shows a login dialog on startup.

---

### 4 — Add a shelf button in your DCC

The snippet below works in **Nuke, Maya, Houdini and Blender** without modification. Only the first `sys.path.insert` line needs to point to your pipeline folder.

```python
import sys
sys.path.insert(0, "/path/to/your_pipeline_folder")
import kitsu_publisher_launch, importlib
importlib.reload(kitsu_publisher_launch)
kitsu_publisher_launch.launch()
```

> **Nuke** — paste into a Python Toolbar button.  
> **Maya** — paste into a Shelf button (Python tab).  
> **Houdini** — create a Shelf tool, paste into the Script tab.  
> **Blender** — paste into the Text Editor and run, or add to `startup/`.

---

## Adding support for a new DCC

The publisher needs two small additions per DCC.

### Step 1 — Detect the DCC in `kitsu_context_detection.py`

Add a detection block in `get_dcc_context()` before the `return "standalone"` line:

```python
# Example: adding Unreal Engine
try:
    import unreal
    return "unreal"
except ImportError:
    pass
```

### Step 2 — Get the main window in `kitsu_publisher_panel.py`

Find `get_main_dcc_window()` and add a branch for your DCC:

```python
elif context == 'unreal':
    try:
        # Return the QWidget that is the main window of the DCC.
        # If the DCC does not expose one, return None — the publisher
        # will open as a standalone floating window.
        import unreal
        return unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_window()
    except Exception as e:
        print("KitsuPublisher: could not get Unreal main window: " + str(e))
```

### Step 3 — Add a playblast integration *(optional)*

If the DCC supports viewport playblast, create a new class in `kitsu_publisher_dcc_integrations.py` inheriting from `PlayblastInterface`:

```python
class UnrealPlayblast(PlayblastInterface):
    def get_cameras(self): ...
    def get_frame_range(self): ...
    def get_output_defaults(self): ...
    def generate_frames(self, settings): ...
```

Then register it in `KitsuPublisher.__init__()` inside `kitsu_publisher_panel.py`:

```python
elif self.dcc_context == "unreal":
    self.playblast_handler = kitsu_publisher_dcc_integrations.UnrealPlayblast()
```

### Common patterns for getting the main window

| DCC | Code |
|---|---|
| Houdini | `hou.qt.mainWindow()` |
| Maya | `shiboken2.wrapInstance(int(OpenMayaUI.MQtUtil.mainWindow()), QWidget)` |
| Nuke | iterate `app.topLevelWidgets()` for `Foundry::UI::DockMainWindow` |
| Blender | `None` (Blender manages its own loop; window floats) |
| Standalone | `None` |

> **Event loop:** Never call `app.exec()` inside a DCC — it already has an event loop running. The publisher only calls `exec()` when `_DCC == "standalone"`.

---

## Configuration reference

| Key | Type | Description |
|---|---|---|
| `kitsu_host` | string | Full API URL, e.g. `https://your-server.com/api` |
| `kitsu_base_url` | string | Base URL without `/api`, used for browser links and Discord messages |
| `env_user_var` | string | OS env var name for the login email (default: `KITSU_USER`) |
| `env_pass_var` | string | OS env var name for the password (default: `KITSU_PASS`) |
| `sys_paths` | list | Paths prepended to `sys.path` before importing gazu |
| `authorized_statuses` | list | Status names shown in the publish dropdown |
| `discord_webhook_url` | string | Discord webhook URL — leave empty to disable notifications |

---

## File overview

| File | Purpose |
|---|---|
| `kitsu_publisher_panel.py` | Main UI and publish logic |
| `kitsu_publisher_launch.py` | Entry point — use this in your shelf button |
| `kitsu_publisher_dcc_integrations.py` | Playblast classes for Maya and Houdini |
| `kitsu_publisher_config.json` | All studio-specific configuration |
| `kitsu_context_detection.py` | Detects active DCC — shared with Kitsu Task Panel |

---

## License

MIT — free to use, modify and distribute.
