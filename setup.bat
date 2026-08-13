@echo off
cd /d %~dp0
py -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
echo.
echo Fertig. Starte KickTrack danach mit start.bat
pause
