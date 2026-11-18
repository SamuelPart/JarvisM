@echo off
setlocal
cd /d "%~dp0"
py -3 -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11 o superior es obligatorio'" || exit /b 1
py -3 -m venv venv || exit /b 1
venv\Scripts\python.exe -m pip install --upgrade pip || exit /b 1
venv\Scripts\python.exe -m pip install -r requirements.txt || exit /b 1
if not exist .env (
  powershell.exe -NoProfile -Command "$s=Read-Host 'Introduzca NVIDIA_API_KEY' -AsSecureString; $b=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s); try { $k=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($b); if ($k -notmatch '^[A-Za-z0-9_-]+$') { throw 'Clave invalida' }; [IO.File]::WriteAllText((Join-Path (Get-Location) '.env'), 'NVIDIA_API_KEY='+$k+[Environment]::NewLine, [Text.UTF8Encoding]::new($false)) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b) }" || exit /b 1
)
echo Instalacion terminada. Ejecute: venv\Scripts\python.exe gui.py
endlocal
