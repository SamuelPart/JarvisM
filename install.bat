@echo off
setlocal
cd /d "%~dp0"
py -3 -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11 o superior es obligatorio'" || exit /b 1
py -3 -m venv venv || exit /b 1
venv\Scripts\python.exe -m pip install --upgrade pip || exit /b 1
venv\Scripts\python.exe -m pip install -r requirements.txt || exit /b 1
echo Instalacion terminada. Abra JARVIS y pegue su NVIDIA_API_KEY en Ajustes > Proveedor de IA.
echo Para ejecutarlo: venv\Scripts\python.exe gui.py
endlocal
