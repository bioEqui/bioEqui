@echo off
rem Actualizacion completa de BioEqui. Pensado para el Programador de tareas
rem de Windows: usa el entorno virtual del proyecto sin necesidad de activarlo.
cd /d "%~dp0"
"%~dp0..\venv\Scripts\python.exe" actualizar.py %*
