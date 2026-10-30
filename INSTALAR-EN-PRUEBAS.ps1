$ErrorActionPreference = 'Stop'
$relayRoot = $PSScriptRoot
$workspaceRoot = Split-Path -Parent $relayRoot
$gameTarget = Join-Path $workspaceRoot 'Pokemon-Z-Pruebas'
if (-not (Test-Path -LiteralPath (Join-Path $gameTarget 'Mods\010_Coop_Net.rb'))) {
    throw 'No se encuentra la copia Pokemon-Z-Pruebas junto a esta carpeta.'
}
$backupFolder = Join-Path $relayRoot ('data\backups\' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Path $backupFolder -Force | Out-Null
foreach ($filename in @('015_Coop_Relay.rb', '045_Coop_Relay_Menu.rb')) {
    $targetFile = Join-Path $gameTarget ('Mods\' + $filename)
    if (Test-Path -LiteralPath $targetFile) {
        Copy-Item -LiteralPath $targetFile -Destination (Join-Path $backupFolder $filename)
    }
    Copy-Item -LiteralPath (Join-Path $relayRoot ('client\' + $filename)) -Destination $targetFile
}
$profile = Join-Path $relayRoot 'data\profiles\PRUEBA01\player\Mods\torneo_relay.cfg'
if (Test-Path -LiteralPath $profile) {
    $profileTarget = Join-Path $gameTarget 'Mods\torneo_relay.cfg'
    if (Test-Path -LiteralPath $profileTarget) {
        Copy-Item -LiteralPath $profileTarget -Destination (Join-Path $backupFolder 'torneo_relay.cfg')
    }
    Copy-Item -LiteralPath $profile -Destination $profileTarget
}
Write-Host 'Instalado en Pokemon-Z-Pruebas. Multijugador > Servidor del torneo.'
Write-Host 'Para el segundo cliente, usa el perfil coach de data\profiles\PRUEBA01.'
