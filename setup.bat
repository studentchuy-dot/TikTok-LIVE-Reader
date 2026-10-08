@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
    echo No se encontro el lanzador py de Python. Instala Python 3.11.
    pause
    exit /b 1
)
py -3.11 -m venv .venv
if errorlevel 1 (
    echo No se pudo crear el entorno virtual de Python.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo No se pudieron instalar las dependencias. Revisa la conexion y vuelve a intentarlo.
    pause
    exit /b 1
)
echo.
echo Instalacion lista. Ejecuta run.bat para abrir el programa.
echo La primera vez que uses Piper, el programa descargara solo las voces que elijas.
pause
