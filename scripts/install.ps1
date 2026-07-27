[CmdletBinding()]
param(
    [Parameter()]
    [string] $RepositoryPath = (Split-Path -Parent $PSScriptRoot),

    [Parameter()]
    [switch] $Editable
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $RepositoryPath -PathType Container)) {
    throw "INSTALL_SOURCE_INVALID: repository directory not found: '$RepositoryPath'."
}

$repository = (Resolve-Path -LiteralPath $RepositoryPath).Path
$projectFile = Join-Path $repository 'pyproject.toml'

if (-not (Test-Path -LiteralPath $projectFile -PathType Leaf)) {
    throw "INSTALL_SOURCE_INVALID: pyproject.toml not found in '$repository'."
}

$uv = Get-Command 'uv' -ErrorAction SilentlyContinue
if ($null -eq $uv) {
    throw 'UV_NOT_FOUND: install uv first, then rerun this script.'
}

$installArguments = @('tool', 'install', '--force')
if ($Editable) {
    $installArguments += '--editable'
}
$installArguments += $repository

Write-Host "Installing sdd-frl from: $repository"
& $uv.Source @installArguments
if ($LASTEXITCODE -ne 0) {
    throw "INSTALL_FAILED: uv tool install exited with code $LASTEXITCODE."
}

$toolBin = (& $uv.Source 'tool' 'dir' '--bin').Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($toolBin)) {
    throw 'TOOL_BIN_UNAVAILABLE: uv did not return its executable directory.'
}

$executableName = if ([System.IO.Path]::DirectorySeparatorChar -eq '\') {
    'sdd-frl.exe'
}
else {
    'sdd-frl'
}
$executable = Join-Path $toolBin $executableName
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw "EXECUTABLE_NOT_FOUND: expected '$executable' after installation."
}

$version = (& $executable '--version' 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {
    throw 'VERSION_CHECK_FAILED: sdd-frl --version returned a non-zero exit code.'
}

$help = (& $executable '--help' 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0) {
    throw 'HELP_CHECK_FAILED: sdd-frl --help returned a non-zero exit code.'
}

$requiredCommands = @('prepare', 'finalize')
$missingCommands = @(
    $requiredCommands | Where-Object { $help -notmatch "\b$([regex]::Escape($_))\b" }
)
if ($missingCommands.Count -gt 0) {
    throw "COMMAND_CHECK_FAILED: missing command(s): $($missingCommands -join ', ')."
}

[pscustomobject]@{
    status       = 'INSTALLED'
    source       = $repository
    executable   = $executable
    version      = $version
    editable     = [bool] $Editable
    commands     = $requiredCommands
} | ConvertTo-Json -Depth 3
