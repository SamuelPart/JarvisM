@echo off
setlocal
cd /d "%~dp0"
py -3 -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11 o superior es obligatorio'" || exit /b 1
py -3 -m venv venv || exit /b 1
venv\Scripts\python.exe -m pip install --upgrade pip || exit /b 1
venv\Scripts\python.exe -m pip install -r requirements.txt || exit /b 1
echo Creando icono de JARVIS en el escritorio...
powershell.exe -NoProfile -Command "$desktop=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desktop 'JARVIS.lnk')); $s.TargetPath='%CD%\venv\Scripts\pythonw.exe'; $s.Arguments='gui.py'; $s.WorkingDirectory='%CD%'; $s.Description='JARVIS - Asistente IA'; $s.Save()" && echo Icono creado: JARVIS en el escritorio. Si no aparece, marca el acceso como confiable. || echo No se pudo crear el icono; puedes abrir JARVIS con: venv\Scripts\pythonw.exe gui.py
echo.
echo Instalacion terminada. Abre JARVIS con el icono del escritorio (no necesitas la terminal).
echo En la primera apertura: Ajustes -^> Proveedor de IA (NVIDIA) - pega tu clave nvapi- y Guardar.
endlocal
