@echo off
REM Doble clic para iniciar el bot (Windows). Deja esta ventana abierta.
cd /d "%~dp0\.."
python -m monitor_redes bot
pause
