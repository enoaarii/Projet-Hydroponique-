@echo off
cd /d "%~dp0"
pip install flask pillow
python server.py
