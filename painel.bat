@echo off
REM Abre o painel web de inadimplencia (deixe esta janela aberta)
cd /d "%~dp0"
call .venv\Scripts\activate.bat
start "" http://localhost:8050
python -m painel
