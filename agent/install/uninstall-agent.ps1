#Requires -RunAsAdministrator
[CmdletBinding(SupportsShouldProcess)]
param(
    [string] $InstallDir,
    [string] $DataDir,
    [switch] $RemoveData
)

$ErrorActionPreference = 'Stop'
$serviceName = 'AlkoCopAgent'
$defaultDataDir = Join-Path $env:ProgramData 'AlkoCop'
$service = Get-CimInstance -ClassName Win32_Service -Filter "Name = '$serviceName'"
if ($service -and -not $InstallDir) {
    $InstallDir = Split-Path -Path $service.PathName.Trim('"') -Parent
}
if (-not $InstallDir) {
    $InstallDir = Join-Path $env:ProgramFiles 'AlkoCop'
}
$InstallDir = [IO.Path]::GetFullPath($InstallDir)
$binary = Join-Path $InstallDir 'AlkoCopAgentService.exe'
$collector = Join-Path $InstallDir 'AlkoCopCollector.exe'
if ($service -and ($binary -ne $service.PathName.Trim('"'))) {
    throw 'The requested install directory does not match the registered AlkoCop service.'
}

if (-not $DataDir) {
    $settingsPath = Join-Path $InstallDir 'appsettings.json'
    if (Test-Path -LiteralPath $settingsPath -PathType Leaf) {
        $DataDir = (Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json).Agent.DataDirectory
    }
    if (-not $DataDir) {
        $DataDir = $defaultDataDir
    }
}
$DataDir = [IO.Path]::GetFullPath($DataDir)

function Test-SameOrChildPath {
    param([string] $Parent, [string] $Path)

    $parentPath = $Parent.TrimEnd('\')
    $childPath = $Path.TrimEnd('\')
    return $childPath -eq $parentPath -or $childPath.StartsWith("$parentPath\", [StringComparison]::OrdinalIgnoreCase)
}

if (-not $RemoveData -and (Test-SameOrChildPath -Parent $InstallDir -Path $DataDir)) {
    throw 'Move the agent data outside the installation directory before removing the program files.'
}
if ($RemoveData -and (Test-SameOrChildPath -Parent $DataDir -Path $InstallDir)) {
    throw 'The data directory must not contain the installation directory.'
}

function Assert-RemovalDirectory {
    param([string] $Path)

    $directory = Get-Item -LiteralPath $Path -Force
    if (-not $directory.PSIsContainer -or ($directory.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Not a regular AlkoCop directory: $Path"
    }
    $reserved = @([IO.Path]::GetPathRoot($Path), $env:SystemRoot, $env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:ProgramData)
    foreach ($reservedPath in $reserved) {
        if ($reservedPath -and (Test-SameOrChildPath -Parent $Path -Path $reservedPath)) {
            throw "Cannot remove a drive or system directory: $Path"
        }
    }
    if (Test-SameOrChildPath -Parent $env:SystemRoot -Path $Path) {
        throw "Cannot remove a Windows system directory: $Path"
    }
}

if (Test-Path -LiteralPath $InstallDir) {
    Assert-RemovalDirectory -Path $InstallDir
    $markedInstall = Test-Path -LiteralPath (Join-Path $InstallDir '.alkocop-install') -PathType Leaf
    $legacyInstall = (Test-Path -LiteralPath $binary -PathType Leaf) -and (Test-Path -LiteralPath $collector -PathType Leaf)
    if (-not ($service -or $markedInstall -or $legacyInstall)) {
        throw "AlkoCop program files were not found in $InstallDir."
    }
}
if ($RemoveData -and (Test-Path -LiteralPath $DataDir)) {
    Assert-RemovalDirectory -Path $DataDir
    $markedData = Test-Path -LiteralPath (Join-Path $DataDir '.alkocop-data') -PathType Leaf
    $hasQueue = Test-Path -LiteralPath (Join-Path $DataDir 'outbox.db') -PathType Leaf
    if (-not $markedData -and -not ($hasQueue -and $DataDir.TrimEnd('\') -eq $defaultDataDir)) {
        $statePath = Join-Path $DataDir 'state.json'
        if (-not ($hasQueue -and (Test-Path -LiteralPath $statePath -PathType Leaf))) {
            throw "AlkoCop data files were not found in $DataDir."
        }
        $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        if ($state.machine_id -notmatch '\A[0-9a-f]{32}\z') {
            throw "The state file in $DataDir is not from AlkoCop."
        }
    }
}
if (-not $PSCmdlet.ShouldProcess($InstallDir, 'Uninstall AlkoCop Agent')) {
    return
}

if ($service) {
    Stop-Service -Name $serviceName
}
Get-Process -Name AlkoCopCollector -ErrorAction SilentlyContinue |
    Where-Object Path -eq $collector |
    ForEach-Object {
        Stop-Process -InputObject $_ -Force
        if (-not $_.WaitForExit(10000)) {
            throw "The AlkoCop collector process $($_.Id) did not stop."
        }
    }

if (Test-Path -LiteralPath $InstallDir) {
    Remove-Item -LiteralPath $InstallDir -Recurse -Force
}
if ($service) {
    sc.exe delete $serviceName | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot remove the AlkoCop service registration.' }
}
if ($RemoveData -and (Test-Path -LiteralPath $DataDir)) {
    Remove-Item -LiteralPath $DataDir -Recurse -Force
}
Write-Host 'AlkoCop agent uninstalled.'
