<#
.SYNOPSIS
    Standard build procedure for CWatM_GUI.exe and CWatM_GUI_Setup.exe.

.DESCRIPTION
    The source of truth is this repository (on the network share P:), but PyInstaller
    and Inno Setup are *not* run here: they read tens of thousands of small files
    (site-packages, the collected Qt/GDAL/matplotlib trees) and write ~950 MB of
    output, which over SMB turns a few-minute build into a very long one.

    So the build runs in a LOCAL working copy - C:\work\CWatM_GUI by default:

        venv       one-time (or -ForceVenv) mirror of the repo venv to <Work>\venv,
                   so site-packages is read from the local disk as well
        sync       mirror the sources the build needs into <Work>
        build      <Work>\venv\Scripts\python.exe -m PyInstaller cwatm_gui_dir.spec
        installer  ISCC <Work>\installer\CWatM_GUI.iss
        copyback   <Work>\dist\CWatM_GUI      -> <Repo>\dist\CWatM_GUI
                   <Work>\installer\Output\*  -> <Repo>\installer\Output

    Everything the build needs resolves relative to the spec / the .iss file, so the
    local copy builds exactly what the repo would - including the version number,
    which the .iss scrapes from src\gui\__init__.py in the mirror.

.EXAMPLE
    .\build_release.ps1                       # full run: sync, build, installer, copy back
    .\build_release.ps1 -Steps sync,build     # rebuild the exe only
    .\build_release.ps1 -ForceVenv            # re-mirror the venv (after pip install/upgrade)
#>
[CmdletBinding()]
param(
    # Local working copy. Anything but a local disk defeats the purpose.
    [string]$Work = 'C:\work\CWatM_GUI',
    [ValidateSet('venv', 'sync', 'build', 'installer', 'copyback')]
    [string[]]$Steps = @('venv', 'sync', 'build', 'installer', 'copyback'),
    # Re-mirror the venv even if <Work>\venv already has a python.exe.
    [switch]$ForceVenv
)

$ErrorActionPreference = 'Stop'
$Repo = $PSScriptRoot
$script:Times = [ordered]@{}

function Write-Step([string]$Text) {
    Write-Host ""
    Write-Host "=== $Text ===" -ForegroundColor Cyan
}

function Invoke-Robocopy([string]$From, [string]$To, [string[]]$Extra) {
    # Robocopy's exit code is a bit field: < 8 means "copied / extra / mismatch",
    # >= 8 is a real failure.
    $argv = @($From, $To) + $Extra + @('/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:2', '/W:2')
    robocopy @argv | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy '$From' -> '$To' failed (exit $LASTEXITCODE)"
    }
    $global:LASTEXITCODE = 0
}

function Measure-Step([string]$Name, [scriptblock]$Body) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    & $Body
    $sw.Stop()
    $script:Times[$Name] = $sw.Elapsed
    Write-Host ("--- {0} done in {1:hh\:mm\:ss}" -f $Name, $sw.Elapsed) -ForegroundColor DarkGray
}

$venvPython = Join-Path $Work 'venv\Scripts\python.exe'

# --------------------------------------------------------------- venv (local copy)
if ($Steps -contains 'venv') {
    if ($ForceVenv -or -not (Test-Path $venvPython)) {
        Write-Step "Mirroring the venv to $Work\venv (1.3 GB, one-time)"
        Measure-Step 'venv' {
            Invoke-Robocopy (Join-Path $Repo 'venv') (Join-Path $Work 'venv') @('/MIR', '/MT:16')
        }
    }
    else {
        Write-Host "venv already present at $Work\venv (use -ForceVenv to refresh)" -ForegroundColor DarkGray
    }
}
if (-not (Test-Path $venvPython)) { throw "No build interpreter at $venvPython - run with -Steps venv first." }

# ------------------------------------------------------------------- source sync
if ($Steps -contains 'sync') {
    Write-Step "Mirroring the sources to $Work"
    Measure-Step 'sync' {
        # Directories the build reads. Nothing else is needed: the spec bundles code
        # through collect_submodules('cwatm'/'src') and only assets, metaNetcdf.xml,
        # the Help markdown + figures, the translation table and the t5 routing
        # libraries as data.
        foreach ($d in 'src', 'cwatm', 'assets', 'documentation', 'translations') {
            Invoke-Robocopy (Join-Path $Repo $d) (Join-Path $Work $d) @('/MIR', '/MT:16', '/XD', '__pycache__', '.git')
        }
        # The installer script + its wizard images; keep a previously built setup.
        Invoke-Robocopy (Join-Path $Repo 'installer') (Join-Path $Work 'installer') @('/MIR', '/MT:8', '/XD', 'Output')
        # Root files the spec entry points need.
        foreach ($f in 'cwatm_gui.py', 'cwatm_model.py', 'cwatm_gui_dir.spec', 'LICENSE') {
            $src = Join-Path $Repo $f
            if (Test-Path $src) { Copy-Item $src (Join-Path $Work $f) -Force }
        }
    }
}

# -------------------------------------------------------------------- PyInstaller
if ($Steps -contains 'build') {
    Write-Step 'PyInstaller (one-folder build)'
    Measure-Step 'build' {
        Push-Location $Work
        try {
            & $venvPython -m PyInstaller cwatm_gui_dir.spec --noconfirm
            if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }
        }
        finally { Pop-Location }
        # The model child exe must end up inside _internal\ - the GUI looks for it
        # there, and its bootloader finds its dependencies next to itself.
        foreach ($p in 'dist\CWatM_GUI\CWatM_GUI.exe', 'dist\CWatM_GUI\_internal\CWatM_model.exe') {
            if (-not (Test-Path (Join-Path $Work $p))) { throw "Build did not produce $p" }
        }
    }
}

# ------------------------------------------------------------------- Inno Setup
if ($Steps -contains 'installer') {
    Write-Step 'Inno Setup (CWatM_GUI_Setup.exe)'
    # ISCC.exe lives in a different place per machine (Inno Setup installs per-user too).
    $iscc = @(
        'C:\Apps\Inno Setup 7\ISCC.exe',
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 7\ISCC.exe'),
        'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $iscc) { throw 'ISCC.exe not found - install Inno Setup 7 or add its path here.' }
    Measure-Step 'installer' {
        & $iscc (Join-Path $Work 'installer\CWatM_GUI.iss')
        if ($LASTEXITCODE -ne 0) { throw "ISCC failed (exit $LASTEXITCODE)" }
    }
}

# --------------------------------------------------------------------- copy back
if ($Steps -contains 'copyback') {
    Write-Step "Copying the results back to $Repo"
    Measure-Step 'copyback' {
        $distSrc = Join-Path $Work 'dist\CWatM_GUI'
        if (Test-Path $distSrc) {
            Invoke-Robocopy $distSrc (Join-Path $Repo 'dist\CWatM_GUI') @('/MIR', '/MT:8')
        }
        $setup = Join-Path $Work 'installer\Output\CWatM_GUI_Setup.exe'
        if (Test-Path $setup) {
            $outDir = Join-Path $Repo 'installer\Output'
            if (-not (Test-Path $outDir)) { New-Item -ItemType Directory $outDir | Out-Null }
            Copy-Item $setup $outDir -Force
        }
    }
}

# ----------------------------------------------------------------------- summary
Write-Step 'Summary'
foreach ($k in $script:Times.Keys) { "{0,-10} {1:hh\:mm\:ss}" -f $k, $script:Times[$k] }
foreach ($p in (Join-Path $Repo 'dist\CWatM_GUI\CWatM_GUI.exe'),
               (Join-Path $Repo 'installer\Output\CWatM_GUI_Setup.exe')) {
    if (Test-Path $p) {
        $i = Get-Item $p
        "{0,-58} {1,8:N1} MB  {2}" -f $i.FullName, ($i.Length / 1MB), $i.LastWriteTime
    }
}
