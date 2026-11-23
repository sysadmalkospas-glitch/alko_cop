#Requires -RunAsAdministrator
<#
.SYNOPSIS
  Устанавливает агент AlkoCop на компьютер сотрудника (запускать от администратора).

.EXAMPLE
  .\install-agent.ps1 -ServerUrl https://alkocop.internal/ -EnrollKey <ключ> -SourceDir .\publish
#>
param(
    [Parameter(Mandatory)] [string] $ServerUrl,
    [Parameter(Mandatory)] [string] $EnrollKey,
    [string] $SourceDir = $PSScriptRoot,
    [string] $InstallDir = "$env:ProgramFiles\AlkoCop",
    [string] $DataDir = "$env:ProgramData\AlkoCop"
)

$ErrorActionPreference = 'Stop'
$serviceName = 'AlkoCopAgent'

foreach ($name in @('AlkoCopAgentService.exe', 'AlkoCopCollector.exe')) {
    if (-not (Test-Path -LiteralPath (Join-Path $SourceDir $name) -PathType Leaf)) {
        throw "Missing $name in $SourceDir. Extract the complete agent package before installing."
    }
}

$existing = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
if ($existing) {
    Stop-Service -Name $serviceName -Force
    Get-Process -Name AlkoCopCollector -ErrorAction SilentlyContinue | Stop-Process -Force
}

New-Item -ItemType Directory -Force -Path $InstallDir, $DataDir | Out-Null
Copy-Item -Path (Join-Path $SourceDir '*') -Destination $InstallDir -Recurse -Force -Exclude 'install-agent.ps1', 'uninstall-agent.ps1'

$settings = @{
    Agent = @{ ServerUrl = $ServerUrl; EnrollKey = $EnrollKey; DataDirectory = $DataDir }
    Logging = @{ LogLevel = @{ Default = 'Information' }; EventLog = @{ LogLevel = @{ Default = 'Warning' } } }
}

# Доступ к файлам агента и его данным: только SYSTEM и администраторы.
# Обычный пользователь не может прочитать ключ и токен, изменить или удалить агент.
foreach ($path in @($InstallDir, $DataDir)) {
    icacls $path /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Cannot set the AlkoCop directory permissions: $path" }
}
# Сборщик должен запускаться от пользователя. Файл с ключом регистрации
# исключаем из прав, наследуемых от каталога программы.
$settingsPath = Join-Path $InstallDir 'appsettings.json'
if (-not (Test-Path -LiteralPath $settingsPath)) {
    New-Item -ItemType File -Path $settingsPath | Out-Null
}
icacls $settingsPath /inheritance:r /grant:r '*S-1-5-18:F' '*S-1-5-32-544:F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Cannot protect the agent settings file.' }
$settings | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 -LiteralPath $settingsPath
icacls $InstallDir /grant:r '*S-1-5-11:(OI)(CI)RX' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Cannot grant access to the collector binaries.' }

New-Item -ItemType File -Force -Path (Join-Path $InstallDir '.alkocop-install'), (Join-Path $DataDir '.alkocop-data') | Out-Null

$binary = Join-Path $InstallDir 'AlkoCopAgentService.exe'
if (-not $existing) {
    New-Service -Name $serviceName -BinaryPathName "`"$binary`"" -DisplayName 'AlkoCop Agent' -StartupType Automatic | Out-Null
}
# Перезапуск при сбое: через 5 с, 5 с и далее каждые 30 с.
sc.exe failure $serviceName reset= 86400 actions= restart/5000/restart/5000/restart/30000 | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Cannot configure service recovery.' }
# Остановить службу может только администратор (SYSTEM и администраторы — полный доступ, пользователи — только чтение статуса).
sc.exe sdset $serviceName 'D:(A;;CCLCSWRPWPDTLOCRRC;;;SY)(A;;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;BA)(A;;CCLCSWLOCRRC;;;IU)(A;;CCLCSWLOCRRC;;;SU)' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Cannot configure service permissions.' }

Start-Service -Name $serviceName
Write-Host "AlkoCop agent installed and started."
