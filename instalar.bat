@echo off
REM Instala o robo de inadimplencia (rodar UMA vez, com Python ja instalado)
cd /d "%~dp0"
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium
if not exist .env copy .env.example .env
echo.
echo Instalacao concluida. Abra o arquivo .env no Bloco de Notas e preencha usuario e senha.
pause
