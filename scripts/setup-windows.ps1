param([switch]$Launch, [switch]$CheckOnly, [ValidateSet('web','desktop')][string]$Mode = 'web')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $projectRoot

function Invoke-Checked([string]$Executable, [string[]]$Arguments) {
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Fallo ejecutando $Executable (codigo $LASTEXITCODE)." }
}
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}
function Get-SetupHash([string]$FilePath) {
    $stream = [IO.File]::OpenRead((Join-Path $projectRoot $FilePath))
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($sha.ComputeHash($stream)) }
    finally { $stream.Dispose(); $sha.Dispose() }
}
function Find-Python {
    foreach ($candidate in @("$env:LOCALAPPDATA\Programs\Python\Python312\python.exe", 'python', 'python3')) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) {
            & $candidate -c "import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] < (3,14) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) { return $candidate }
        }
    }
    return $null
}
try {
    $python = Find-Python
    $nodeReady = $false
    if (Get-Command node -ErrorAction SilentlyContinue) {
        & node -e "process.exit(Number(process.versions.node.split('.')[0]) >= 22 ? 0 : 1)"
        $nodeReady = $LASTEXITCODE -eq 0
    }
    $venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
    $chromePaths = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe", "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe")
    $chromeReady = @($chromePaths | Where-Object { Test-Path -LiteralPath $_ }).Count -gt 0
    $stamp = Join-Path $projectRoot '.venv\utel-setup.json'
    $signature = (Get-SetupHash 'backend/requirements.txt') + (Get-SetupHash 'package-lock.json')
    $ready = $false
    $electronReady = $Mode -eq 'web' -or (Test-Path 'node_modules/electron/dist/electron.exe')
    # El registro es informativo: una instalacion existente y valida no requiere
    # reinstalar por un cambio de hash, carpeta o formato del registro.
    if ((Test-Path $venvPython) -and $nodeReady -and $chromeReady -and $electronReady) {
        & $venvPython (Join-Path $PSScriptRoot 'check-runtime.py')
        $ready = $LASTEXITCODE -eq 0
    }
    if (-not $ready) {
        Write-Host 'UTEL QA necesita preparar/verificar las dependencias de este equipo.'
        Write-Host 'Preparara Python, Node.js, librerias en .venv, Chromium y Chrome segun lo necesario.'
        if ($Mode -eq 'desktop') { Write-Host 'El modo escritorio tambien requiere Electron.' }
        Write-Host 'Se requiere internet y espacio en disco. Windows puede solicitar permisos de administrador.'
        if ($CheckOnly) { Write-Host 'Diagnostico: preparacion pendiente. No se instalo nada.'; exit 2 }
        $answer = Read-Host 'Autoriza la descarga e instalacion? Escriba SI para continuar'
        if ($answer.Trim() -ine 'SI') { Write-Host 'Instalacion cancelada.'; exit 1 }
        if (-not $python -or -not $nodeReady -or -not $chromeReady) {
            if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { throw 'Instale App Installer de Microsoft (winget), o Python 3.12, Node.js LTS y Chrome manualmente, y vuelva a abrir Iniciar.cmd.' }
            foreach ($item in @(@(-not $python, 'Python.Python.3.12'), @(-not $nodeReady, 'OpenJS.NodeJS.LTS'), @(-not $chromeReady, 'Google.Chrome'))) {
                if ($item[0]) { Invoke-Checked 'winget' @('install', '--id', $item[1], '--exact', '--source', 'winget', '--accept-source-agreements', '--accept-package-agreements', '--disable-interactivity') }
            }
            Refresh-Path
            $python = Find-Python
        }
        if (-not $python) { throw 'Python no esta disponible. Cierre y vuelva a abrir Iniciar.cmd.' }
        if (-not (Test-Path $venvPython)) { Invoke-Checked $python @('-m', 'venv', '.venv') }
        Invoke-Checked $venvPython @('-m', 'pip', 'install', '-r', 'backend/requirements.txt')
        if ($Mode -eq 'desktop') {
            Invoke-Checked 'npm.cmd' @('ci')
            if (-not (Test-Path 'node_modules/electron/dist/electron.exe')) {
                Invoke-Checked 'node' @('scripts/install-electron.js')
            }
            if (-not (Test-Path 'node_modules/electron/dist/electron.exe')) { throw 'Electron no se descargo correctamente; no se marcara la instalacion como completa.' }
        }
        Invoke-Checked $venvPython @('-m', 'playwright', 'install', 'chromium')
        Invoke-Checked $venvPython @('-m', 'pip', 'check')
        Invoke-Checked $venvPython @((Join-Path $PSScriptRoot 'check-runtime.py'))
        if (-not (Test-Path '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env'; Write-Host 'Se creo .env: configure sus credenciales de CRM/IA antes de ejecutar automatizaciones.' }
        @{ signature = $signature; computer = $env:COMPUTERNAME; root = $projectRoot } | ConvertTo-Json | Set-Content -LiteralPath $stamp -Encoding UTF8
    }
    & $venvPython (Join-Path $PSScriptRoot 'prepare-resources.py')
    $resourceStatus = $LASTEXITCODE
    if ($resourceStatus -eq 2) {
        if ($CheckOnly) { exit 2 }
        Write-Host 'Se preparara .env y se habilitara la generacion local de telefonos de QA, como en el equipo original.'
        Write-Host 'Son numeros sinteticos con formato nacional; no garantizan una linea activa y pueden coincidir con numeros asignados.'
        $resourceConsent = Read-Host 'Autoriza esta configuracion para sus pruebas? Escriba SI'
        if ($resourceConsent.Trim() -ine 'SI') { Write-Host 'Configuracion cancelada. Puede configurar UTEL_TEST_PHONES_JSON con su banco autorizado.'; exit 1 }
        Invoke-Checked $venvPython @((Join-Path $PSScriptRoot 'prepare-resources.py'), '--prepare')
    } elseif ($resourceStatus -ne 0) { throw 'Faltan recursos de la app o su configuracion es invalida. Revise el mensaje anterior.' }
    Write-Host 'Dependencias y recursos locales preparados. CRM e IA requieren credenciales propias; Ollama local es opcional.'
    if ($Launch) { Invoke-Checked 'node' @('scripts/launch-web.js') }
} catch { Write-Host "No se pudo preparar UTEL QA: $_" -ForegroundColor Red; exit 1 }
