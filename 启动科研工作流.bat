@echo off
cd /d "%~dp0"
if exist __pycache__ rmdir /s /q __pycache__
streamlit run ui.py
pause
