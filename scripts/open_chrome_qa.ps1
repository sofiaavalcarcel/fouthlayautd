# Abre un perfil aislado de Chrome para iniciar sesión una sola vez antes de automatizar.
# Este perfil no es el perfil personal de Chrome y sus cookies quedan dentro de storage.

$projectRoot = Split-Path -Parent $PSScriptRoot
$profileDirectory = Join-Path $projectRoot "storage\browser_profiles\chrome-qa"
$chromeCandidates = @(
  (Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe"),
  (Join-Path ${env:ProgramFiles(x86)} "Google\Chrome\Application\chrome.exe"),
  (Join-Path $env:LOCALAPPDATA "Google\Chrome\Application\chrome.exe")
)
$chromePath = $chromeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

if (-not $chromePath) {
  throw "No se encontró Google Chrome en las rutas habituales."
}

New-Item -ItemType Directory -Force -Path $profileDirectory | Out-Null
Start-Process -FilePath $chromePath -ArgumentList @(
  "--user-data-dir=$profileDirectory",
  "--profile-directory=Default",
  "https://utel.edu.mx/",
  "https://lead-balancer.scalahed.com/leads/"
)

Write-Host "Chrome QA abierto. Inicia sesión en UTEL y Balanceador, completa Cloudflare si aparece y cierra esa ventana cuando termines."
