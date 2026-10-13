<#
.SYNOPSIS
    JarvisM · instalador para Windows 10/11.

.DESCRIPTION
    Crea un entorno virtual en .venv, instala JarvisM y ejecuta el diagnóstico.
    Es idempotente: se puede volver a ejecutar sin romper nada.

.PARAMETER Voice
    Instala los extras de voz (STT/TTS locales).

.PARAMETER Ui
    Instala los extras de UI (FastAPI para el HUD de la Fase 6).

.PARAMETER Dev
    Instala las herramientas de desarrollo (pytest, ruff, mypy).

.PARAMETER All
    Instala todos los extras.

.PARAMETER NoSystem
    No intenta instalar dependencias con winget.

.EXAMPLE
    .\scripts\install-windows.ps1 -All
#>
[CmdletBinding()]
param(
    [switch]$Voice,
    [switch]$Ui,
    [switch]$Dev,
    [switch]$All,
    [switch]$NoSystem
)

$ErrorActionPreference = 'Stop'

function Write-Step { param([string]$Message) Write-Host "==> $Message" -ForegroundColor Green }
function Write-Note { param([string]$Message) Write-Host "    $Message" -ForegroundColor DarkGray }
function Write-Warn { param([string]$Message) Write-Host "[aviso] $Message" -ForegroundColor Yellow }
function Fail { param([string]$Message) Write-Error $Message; exit 1 }

if ($All) { $Voice = $true; $Ui = $true; $Dev = $true }

$RepoDir = Split-Path -Parent $PSScriptRoot
$VenvDir = Join-Path $RepoDir '.venv'

# --------------------------------------------------------------------------- #
Write-Step 'Comprobando el entorno'

if ($env:OS -ne 'Windows_NT') { Fail 'Este script es para Windows.' }

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Warn 'Estás ejecutando PowerShell como Administrador.'
    Write-Warn 'JarvisM no debe correr con privilegios elevados (docs/03 §1). Abre una consola normal.'
}

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command py -ErrorAction SilentlyContinue }
if (-not $python) {
    Fail 'No encuentro Python. Instálalo con: winget install Python.Python.3.12'
}

$pyVersion = & $python.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Note "Python $pyVersion detectado"

$major, $minor = $pyVersion.Split('.')
if ([int]$major -lt 3 -or ([int]$major -eq 3 -and [int]$minor -lt 10)) {
    Fail "Se necesita Python 3.10+; tienes $pyVersion"
}

# --------------------------------------------------------------------------- #
if (-not $NoSystem) {
    Write-Step 'Comprobando dependencias del sistema'
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Note 'winget disponible. Si falta algo, se instalará manualmente.'
        # Nota: no instalamos nada silenciosamente. Solo comprobamos y avisamos.
        if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
            Write-Warn 'git no está instalado. Recomendado: winget install Git.Git'
        }
    } else {
        Write-Warn 'winget no disponible (Windows 10 antiguo). Instala git a mano si lo necesitas.'
    }
    Write-Note 'Para control de volumen: winget install nircmd  (o pip install pycaw)'
    Write-Note 'Para control de ventanas: pip install pywin32'
} else {
    Write-Step 'Omitiendo comprobaciones del sistema (-NoSystem)'
}

# --------------------------------------------------------------------------- #
Set-Location $RepoDir

Write-Step "Creando el entorno virtual en $VenvDir"
if (-not (Test-Path $VenvDir)) {
    & $python.Source -m venv $VenvDir
}

$venvPython = Join-Path $VenvDir 'Scripts\python.exe'
if (-not (Test-Path $venvPython)) { Fail "No se creó $venvPython" }

& $venvPython -m pip install --quiet --upgrade pip wheel

# --------------------------------------------------------------------------- #
Write-Step 'Instalando JarvisM'
$extras = @()
if ($Voice) { $extras += 'voice' }
if ($Ui)    { $extras += 'ui' }
if ($Dev)   { $extras += 'dev' }

if ($extras.Count -gt 0) {
    $target = ".[$($extras -join ',')]"
    Write-Note "extras: $($extras -join ', ')"
    & $venvPython -m pip install --quiet -e $target
} else {
    & $venvPython -m pip install --quiet -e .
}

# --------------------------------------------------------------------------- #
Write-Step 'Preparando la configuración'
$envFile = Join-Path $RepoDir '.env'
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $RepoDir '.env.example') $envFile
    Write-Note 'Creado .env. Edítalo con tu clave de API.'
    try {
        # Restringe el acceso al usuario actual (equivalente Windows de chmod 600).
        $acl = Get-Acl $envFile
        $acl.SetAccessRuleProtection($true, $false)
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            $identity.Name, 'FullControl', 'Allow')
        $acl.SetAccessRule($rule)
        Set-Acl -Path $envFile -AclObject $acl
        Write-Note 'Permisos de .env restringidos a tu usuario.'
    } catch {
        Write-Warn "No pude restringir los permisos de .env: $_"
    }
} else {
    Write-Note '.env ya existía; no lo he tocado.'
}

$workspace = Join-Path $env:USERPROFILE 'JarvisWorkspace'
if (-not (Test-Path $workspace)) { New-Item -ItemType Directory -Path $workspace | Out-Null }

# --------------------------------------------------------------------------- #
Write-Step 'Ejecutando el diagnóstico'
$jarvis = Join-Path $VenvDir 'Scripts\jarvis.exe'
& $jarvis doctor
$status = $LASTEXITCODE

Write-Host ''
Write-Host 'Instalación terminada' -ForegroundColor Green
Write-Host @"

  1. Activa el entorno:      $VenvDir\Scripts\Activate.ps1
  2. Edita la clave:         notepad $envFile
  3. Comprueba proveedores:  jarvis doctor --providers
  4. Prueba sin gastar:      jarvis chat --provider echo
  5. Habla con él:           jarvis chat

Si PowerShell bloquea la activación del script:
  Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned

Guía completa: docs/04-guia-kali-linux.md (los pasos de prueba valen igual en Windows)
Fase 2 pendiente en Windows: control de ventanas (pip install pywin32) y volumen (nircmd o pycaw).
"@

exit $status
