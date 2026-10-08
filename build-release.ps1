$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "No existe .venv. Ejecuta setup.bat antes de crear el ejecutable."
}

& $python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    throw "No se pudieron preparar las dependencias para distribuir."
}
& $python -m pip show pyinstaller *> $null
if ($LASTEXITCODE -ne 0) {
    & $python -m pip install pyinstaller
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo instalar PyInstaller."
    }
}

$license = Join-Path $PSScriptRoot ".venv\Lib\site-packages\piper_tts-1.8.0.dist-info\licenses\COPYING"
if (-not (Test-Path $license)) {
    throw "No se encontro la licencia GPL del motor Piper."
}

$releaseDirectory = Join-Path $PSScriptRoot "distros"
$workDirectory = Join-Path $PSScriptRoot "build\release"
$specDirectory = Join-Path $PSScriptRoot "build\release-spec"
$tempDirectory = Join-Path ([System.IO.Path]::GetTempPath()) `
    ("TikTok-LIVE-Reader-icon-" + [guid]::NewGuid().ToString("N"))
$iconPath = Join-Path $tempDirectory "TikTok-LIVE-Reader.ico"

New-Item -ItemType Directory -Force -Path $releaseDirectory, $tempDirectory | Out-Null
$existingExtras = @(
    Get-ChildItem -LiteralPath $releaseDirectory -Force |
        Where-Object { $_.Name -ne "TikTok-LIVE-Reader.exe" }
)
if ($existingExtras.Count -gt 0) {
    throw "distros debe estar vacío o contener solo el ejecutable anterior. Mueve estos archivos antes de compilar: $($existingExtras.Name -join ', ')"
}

Add-Type -AssemblyName System.Drawing

[System.Drawing.Bitmap]$bitmap = [System.Drawing.Bitmap]::new(
    256,
    256,
    [System.Drawing.Imaging.PixelFormat]::Format32bppArgb
)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$graphics.Clear([System.Drawing.Color]::Transparent)

foreach ($layer in @(
    @{ Color = [System.Drawing.Color]::FromArgb(0, 242, 234); X = -8; Y = 2 },
    @{ Color = [System.Drawing.Color]::FromArgb(254, 44, 85); X = 7; Y = 0 },
    @{ Color = [System.Drawing.Color]::White; X = 0; Y = 0 }
)) {
    $brush = [System.Drawing.SolidBrush]::new($layer.Color)
    $pen = [System.Drawing.Pen]::new($brush, 22)
    $pen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
    $pen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
    $x = [int]$layer.X
    $y = [int]$layer.Y
    $graphics.DrawLine($pen, 145 + $x, 54 + $y, 145 + $x, 160 + $y)
    $graphics.DrawBezier(
        $pen,
        145 + $x, 56 + $y,
        164 + $x, 77 + $y,
        184 + $x, 78 + $y,
        203 + $x, 80 + $y
    )
    $graphics.DrawLine($pen, 203 + $x, 80 + $y, 203 + $x, 105 + $y)
    $graphics.FillEllipse($brush, 87 + $x, 151 + $y, 63, 48)
    $pen.Dispose()
    $brush.Dispose()
}

$pngStream = New-Object System.IO.MemoryStream
$bitmap.Save($pngStream, [System.Drawing.Imaging.ImageFormat]::Png)
$pngBytes = $pngStream.ToArray()
$iconStream = [System.IO.File]::Create($iconPath)
$writer = New-Object System.IO.BinaryWriter($iconStream)
$writer.Write([UInt16]0)
$writer.Write([UInt16]1)
$writer.Write([UInt16]1)
$writer.Write([byte]0)
$writer.Write([byte]0)
$writer.Write([byte]0)
$writer.Write([byte]0)
$writer.Write([UInt16]1)
$writer.Write([UInt16]32)
$writer.Write([UInt32]$pngBytes.Length)
$writer.Write([UInt32]22)
$writer.Write($pngBytes)
$writer.Dispose()
$pngStream.Dispose()
$graphics.Dispose()
$bitmap.Dispose()

try {
    & $python -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --console `
        --icon $iconPath `
        --collect-data piper `
        --collect-binaries piper `
        --collect-binaries onnxruntime `
        --add-data "$license;THIRD_PARTY_LICENSES" `
        --name TikTok-LIVE-Reader `
        --distpath $releaseDirectory `
        --workpath $workDirectory `
        --specpath $specDirectory `
        main.py
    if ($LASTEXITCODE -ne 0) {
        throw "La compilacion del ejecutable para compartir fallo."
    }
}
finally {
    if (Test-Path $tempDirectory) {
        Remove-Item -LiteralPath $tempDirectory -Recurse -Force
    }
}

$executable = Join-Path $releaseDirectory "TikTok-LIVE-Reader.exe"
if (-not (Test-Path $executable)) {
    throw "PyInstaller termino sin generar el ejecutable esperado."
}

$unexpectedFiles = @(
    Get-ChildItem -LiteralPath $releaseDirectory -Force |
        Where-Object { $_.Name -ne "TikTok-LIVE-Reader.exe" }
)
foreach ($file in $unexpectedFiles) {
    throw "Se encontró contenido inesperado en distros: $($file.Name)"
}

Write-Host "Ejecutable listo para compartir: distros\TikTok-LIVE-Reader.exe"
