"""
UI 子模块包 — Streamlit 界面各功能区域拆分

使用方式（在 ui.py 中）：
    from ui import (inject_styles, render_sidebar_history,
                    render_settings_panel, process_uploaded_files,
                    dispatch_question, render_progress_panel,
                    render_results, render_export_button,
                    backfill_history, load_history, save_history)
"""
from ui.ui_styles import inject_styles
from ui.ui_history import load_history, save_history, render_sidebar_history
from ui.ui_files import process_uploaded_files
from ui.ui_settings import render_settings_panel
from ui.ui_runner import dispatch_question, render_progress_panel
from ui.ui_results import render_results, render_export_button, backfill_history
