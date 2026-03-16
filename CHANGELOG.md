# Changelog

All notable changes to this project will be documented here.

---

## [1.0.0] — 2025

### First public release

- Publish files (MP4, JPG, PNG) to Kitsu tasks from Nuke, Maya, Houdini and Blender
- Asset, Shot and Playblast tabs
- Task status change on publish with optional comment
- Timesheet — log time spent directly from the publish dialog
- Filter tasks to show only the current user's assignments
- Auto-login via `KITSU_USER` / `KITSU_PASS` environment variables, with manual login fallback
- Optional Discord webhook notification on every publish
- Playblast generation for Maya and Houdini with automatic MP4 conversion via FFmpeg
- All studio-specific settings moved to `kitsu_publisher_config.json` — no hardcoded values in source
- Compatible with PySide2 and PySide6 (Nuke, Maya, Houdini, standalone)
- Shared `kitsu_context_detection.py` compatible with Kitsu Task Panel
