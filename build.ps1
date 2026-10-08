$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Preparando el entorno aislado del proyecto..."
    & py -3.11 -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo crear .venv. Instala Python 3.11."
    }
}

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    throw "No se pudo instalar el conector de TikTok."
}
& $python -m pip show pyinstaller *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Instalando PyInstaller solo para compilar el ejecutable..."
    & $python -m pip install pyinstaller
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo instalar PyInstaller."
    }
}
$portableDirectory = Join-Path $PSScriptRoot "dist\TikTok-LIVE-Reader"
$portableData = Join-Path $portableDirectory "data"
$dataBackupRoot = $null
if (Test-Path $portableData) {
    $dataBackupRoot = Join-Path ([System.IO.Path]::GetTempPath()) `
        ("TikTok-LIVE-Reader-data-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $dataBackupRoot | Out-Null
    Copy-Item -LiteralPath $portableData `
        -Destination (Join-Path $dataBackupRoot "data") -Recurse
}

try {
    & $python -m PyInstaller --noconfirm --clean --onedir --console --collect-data piper --collect-binaries piper --collect-binaries onnxruntime --name TikTok-LIVE-Reader main.py
    if ($LASTEXITCODE -ne 0) {
        throw "La compilacion de la CLI fallo."
    }
}
finally {
    $backupData = if ($dataBackupRoot) {
        Join-Path $dataBackupRoot "data"
    }
    if ($backupData -and (Test-Path $backupData)) {
        New-Item -ItemType Directory -Force -Path $portableData | Out-Null
        Get-ChildItem -LiteralPath $backupData -Force | ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $portableData `
                -Recurse -Force
        }
        Remove-Item -LiteralPath $dataBackupRoot -Recurse -Force
    }
}
$license = Join-Path $PSScriptRoot ".venv\Lib\site-packages\piper_tts-1.8.0.dist-info\licenses\COPYING"
if (-not (Test-Path $license)) {
    throw "No se encontro la licencia GPL del motor Piper."
}
$licenseDirectory = Join-Path $PSScriptRoot "dist\TikTok-LIVE-Reader\THIRD_PARTY_LICENSES"
New-Item -ItemType Directory -Force -Path $licenseDirectory | Out-Null
Copy-Item $license (Join-Path $licenseDirectory "Piper-GPL-3.0.txt") -Force
Write-Host "Aplicacion de consola creada: dist\TikTok-LIVE-Reader\TikTok-LIVE-Reader.exe"
