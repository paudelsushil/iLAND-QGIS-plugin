param(
    [string]$OutputDir = "dist",
    [string]$ZipName = "iLAND_Workbench_QGIS.zip",
    [switch]$SkipPreflight
)


$ErrorActionPreference = "Stop"

$PluginDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $PluginDir
$OutputPath = Join-Path $PluginDir $OutputDir
$StageRoot = Join-Path $OutputPath "_stage"
$StagePluginDir = Join-Path $StageRoot "iLAND_QGIS_plugin"
$ZipPath = Join-Path $OutputPath $ZipName

if (-not $SkipPreflight) {
    $requiredPaths = @(
        @{ Path = (Join-Path $RepoRoot "src"); Kind = "dir"; Why = "iLAND source root is required for module discovery." },
        @{ Path = (Join-Path $RepoRoot "src\iland"); Kind = "dir"; Why = "Desktop iLAND UI sources are required for catalog mapping." },
        @{ Path = (Join-Path $RepoRoot "src\iland\mainwindow.ui"); Kind = "file"; Why = "UI mirror source required for toolbar/dock/settings discovery." },
        @{ Path = (Join-Path $RepoRoot "src\iland\res\project_file_metadata.txt"); Kind = "file"; Why = "Settings taxonomy source required." },
        @{ Path = (Join-Path $RepoRoot "src\ilandc"); Kind = "dir"; Why = "Headless engine source folder required." },
        @{ Path = (Join-Path $RepoRoot "src\ilandc\main.cpp"); Kind = "file"; Why = "Headless iLANDc entrypoint source required." },
        @{ Path = (Join-Path $PluginDir "metadata.txt"); Kind = "file"; Why = "QGIS plugin metadata required." },
        @{ Path = (Join-Path $PluginDir "__init__.py"); Kind = "file"; Why = "QGIS classFactory entrypoint required." },
        @{ Path = (Join-Path $PluginDir "iland_qgis_plugin.py"); Kind = "file"; Why = "Plugin bootstrap required." },
        @{ Path = (Join-Path $PluginDir "iland_dock_widget.py"); Kind = "file"; Why = "Main workbench UI required." },
        @{ Path = (Join-Path $PluginDir "runtime_manager.py"); Kind = "file"; Why = "Runtime install/activation logic required." }
    )

    $missing = @()
    foreach ($req in $requiredPaths) {
        $exists = Test-Path $req.Path
        if (-not $exists) {
            $missing += ("- Missing {0}: {1}`n  Reason: {2}" -f $req.Kind, $req.Path, $req.Why)
        }
    }

    if ($missing.Count -gt 0) {
        Write-Host "Preflight failed. Required iLAND/plugin components are missing:" -ForegroundColor Red
        $missing | ForEach-Object { Write-Host $_ -ForegroundColor Red }
        throw "Packaging aborted by preflight checks."
    }

    $ilandcCandidates = @(
        (Join-Path $RepoRoot "iLANDc.exe"),
        (Join-Path $RepoRoot "build\iLANDc.exe"),
        (Join-Path $RepoRoot "bin\iLANDc.exe")
    )
    $hasLocalIlandc = $false
    foreach ($candidate in $ilandcCandidates) {
        if (Test-Path $candidate) {
            $hasLocalIlandc = $true
            break
        }
    }
    if (-not $hasLocalIlandc) {
        Write-Host "Preflight warning: no local iLANDc.exe found; plugin will rely on Runtime tab auto-install or external runtime." -ForegroundColor Yellow
    }
}

if (Test-Path $StageRoot) {
    Remove-Item -Recurse -Force $StageRoot
}
if (-not (Test-Path $OutputPath)) {
    New-Item -ItemType Directory -Path $OutputPath | Out-Null
}

New-Item -ItemType Directory -Path $StagePluginDir | Out-Null

$includePatterns = @("*.py", "metadata.txt", "README.md", "LICENSE", "QGIS_COOKBOOK_COMPLIANCE.md", "REQUIRED_REPO_COMPONENTS.md", "icon*.png", "icon*.svg")

Get-ChildItem -Path $PluginDir -File | Where-Object {
    $name = $_.Name
    foreach ($pattern in $includePatterns) {
        if ($name -like $pattern) { return $true }
    }
    return $false
} | ForEach-Object {
    Copy-Item -Path $_.FullName -Destination (Join-Path $StagePluginDir $_.Name)
}

$optionalDirs = @("i18n", "help")
foreach ($dirName in $optionalDirs) {
    $sourceDir = Join-Path $PluginDir $dirName
    if (Test-Path $sourceDir) {
        Copy-Item -Path $sourceDir -Destination (Join-Path $StagePluginDir $dirName) -Recurse -Force
    }
}

if (Test-Path $ZipPath) {
    Remove-Item -Force $ZipPath
}
Compress-Archive -Path $StagePluginDir -DestinationPath $ZipPath -CompressionLevel Optimal
Remove-Item -Recurse -Force $StageRoot

Write-Host "Plugin package created:" $ZipPath
