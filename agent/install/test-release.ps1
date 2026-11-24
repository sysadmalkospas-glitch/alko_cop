param(
    [Parameter(Mandatory)] [string] $Archive,
    [Parameter(Mandatory)] [string] $Version
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$serviceName = 'AlkoCopAgent'
if (Get-Service -Name $serviceName -ErrorAction SilentlyContinue) {
    throw 'The package test requires a runner without an existing AlkoCop service.'
}

$testRoot = Join-Path $env:RUNNER_TEMP 'AlkoCop package test'
$sourceDir = Join-Path $testRoot 'extracted'
$installDir = Join-Path $testRoot 'program'
$dataDir = Join-Path $testRoot 'data'
Expand-Archive -LiteralPath $Archive -DestinationPath $sourceDir
foreach ($app in @('AlkoCopAgentService', 'AlkoCopCollector')) {
    $config = Get-Content -LiteralPath (Join-Path $sourceDir "$app.runtimeconfig.json") -Raw | ConvertFrom-Json
    if ($config.runtimeOptions.includedFrameworks.name -notcontains 'Microsoft.NETCore.App') {
        throw "$app is not a self-contained Windows build."
    }
}

$serverUrl = 'http://127.0.0.1:17819/'
$listener = [System.Net.HttpListener]::new()
$listener.Prefixes.Add($serverUrl)
$installer = Join-Path $sourceDir 'install-agent.ps1'
$uninstaller = Join-Path $sourceDir 'uninstall-agent.ps1'
$powershellFlags = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File')
$testStarted = Get-Date
try {
    $listener.Start()
    $pendingRequest = $listener.GetContextAsync()
    Write-Host 'Installing the ZIP using its default package directory.'
    & powershell.exe @powershellFlags $installer -ServerUrl $serverUrl -EnrollKey 'ci-only' -InstallDir $installDir -DataDir $dataDir
    if ((Get-Service -Name $serviceName).Status -ne 'Running') {
        throw 'The installed agent service did not start.'
    }
    if (-not $pendingRequest.Wait(60000)) {
        throw 'The installed agent did not attempt to enroll.'
    }
    $context = $pendingRequest.GetAwaiter().GetResult()
    if ($context.Request.Url.AbsolutePath -ne '/api/agent/v1/enroll') {
        throw 'Expected an enrollment request from the installed agent.'
    }
    $reader = [System.IO.StreamReader]::new($context.Request.InputStream)
    try {
        $request = $reader.ReadToEnd() | ConvertFrom-Json
    } finally {
        $reader.Dispose()
        $context.Response.StatusCode = 503
        $context.Response.Close()
    }
    $actualVersion = $request.agent_version
    if ($actualVersion -cne $Version) {
        throw "Expected agent_version '$Version', got '$actualVersion'."
    }

    & powershell.exe @powershellFlags $uninstaller
    if ((Get-Service -Name $serviceName -ErrorAction SilentlyContinue) -or (Test-Path -LiteralPath $installDir)) {
        throw 'The service and program files were expected to be removed.'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $dataDir 'state.json'))) {
        throw 'An ordinary uninstall must preserve the agent state.'
    }

    & powershell.exe @powershellFlags $uninstaller -InstallDir $installDir -DataDir $dataDir -RemoveData
    if (Test-Path -LiteralPath $dataDir) {
        throw 'The agent state directory was expected to be removed with -RemoveData.'
    }
} catch {
    Get-WinEvent -FilterHashtable @{ LogName = 'Application', 'System'; StartTime = $testStarted } -ErrorAction SilentlyContinue |
        Where-Object Message -Match 'AlkoCopAgent|AlkoCop Agent' |
        Format-List TimeCreated, ProviderName, Id, Message |
        Out-Host
    throw
} finally {
    $listener.Close()
    if ((Get-Service -Name $serviceName -ErrorAction SilentlyContinue) -or
        (Test-Path -LiteralPath (Join-Path $installDir '.alkocop-install')) -or
        (Test-Path -LiteralPath (Join-Path $dataDir '.alkocop-data'))) {
        & powershell.exe @powershellFlags $uninstaller -InstallDir $installDir -DataDir $dataDir -RemoveData
    }
}
