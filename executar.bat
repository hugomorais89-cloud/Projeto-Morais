@echo off
REM Executa o robo de inadimplencia (usado tambem pelo Agendador de Tarefas)
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python -m robo %*
