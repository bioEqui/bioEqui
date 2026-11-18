@echo off
rem Levanta BioEqui completo (Docker, base, API y pagina) y abre el navegador.
rem Doble clic para usarlo. Para detener: Ctrl+C o cerrar la ventana.
cd /d "%~dp0"
"%~dp0..\venv\Scripts\python.exe" levantar.py %*
pause
