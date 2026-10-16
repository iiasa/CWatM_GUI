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
        msix       the Microsoft Store package: dist\CWatM_GUI + installer\msix
                   (manifest, logos) -> <Work>\installer\Output\CWatM_GUI_<ver>_x64.msix
        copyback   <Work>\dist\CWatM_GUI      -> <Repo>\dist\CWatM_GUI
                   <Work>\installer\Output\*  -> <Repo>\installer\Output

    Everything the build needs resolves relative to the spec / the .iss file, so the
    local copy builds exactly what the repo would - including the version number,
    which the .iss (and the msix step) read from src\gui\__init__.py in the mirror.

.EXAMPLE
    .\build_release.ps1                       # full run: sync, build, installer, msix, copy back
    .\build_release.ps1 -Steps sync,build     # rebuild the exe only
    .\build_release.ps1 -ForceVenv            # re-mirror the venv (after pip install/upgrade)
    .\build_release.ps1 -Steps msix -MsixTestIdentity   # a packaged layout to try locally
#>
[CmdletBinding()]
param(
    # Local working copy. Anything but a local disk defeats the purpose.
    [string]$Work = 'C:\work\CWatM_GUI',
    [ValidateSet('venv', 'sync', 'build', 'installer', 'msix', 'copyback')]
    [string[]]$Steps = @('venv', 'sync', 'build', 'installer', 'msix', 'copyback'),
    # Re-mirror the venv even if <Work>\venv already has a python.exe.
    [switch]$ForceVenv,
    # Authenticode signing (security.md #3): the SHA-1 thumbprint of a code-signing
    # certificate in the current user's store (Cert:\CurrentUser\My). Default: the
    # environment variable CWATM_SIGN_THUMBPRINT. Empty = build unsigned (a warning).
    [string]$SignThumbprint = $env:CWATM_SIGN_THUMBPRINT,
    [string]$TimestampUrl = 'http://timestamp.digicert.com',
    # MSIX (Microsoft Store): the third field of the package version X.YZ.<MsixBuild>.0.
    # Every Store upload needs a higher version than the last one, so raise this to
    # resubmit the same __version__ (e.g. after a packaging-only fix); back to 0 when
    # __version__ moves on.
    [ValidateRange(0, 65535)]
    [int]$MsixBuild = 0,
    # MSIX with a placeholder identity, before Partner Center's values are in
    # installer\msix\store_identity.json: builds only the layout folder, to register
    # and try locally (Developer Mode). Never uploaded, so no .msix is written.
    [switch]$MsixTestIdentity
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

function Find-SdkTool([string]$Name) {
    # A Windows SDK tool (signtool, makeappx, makepri), newest SDK version first.
    $tool = Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin\*\x64\$Name" -ErrorAction SilentlyContinue |
        Sort-Object { try { [version]$_.Directory.Parent.Name } catch { [version]'0.0' } } -Descending |
        Select-Object -First 1
    if (-not $tool) { throw "$Name not found - install the Windows SDK (it ships signtool, makeappx and makepri)." }
    return $tool.FullName
}

function Invoke-Sign([string[]]$Files) {
    # Signs with signtool (Windows SDK) when a certificate is configured; otherwise
    # says the build is unsigned. A signed exe/setup lets Windows and users verify
    # that it comes from IIASA and was not changed afterwards.
    if (-not $SignThumbprint) {
        Write-Host "NOT signed (no -SignThumbprint / CWATM_SIGN_THUMBPRINT): $($Files -join ', ')" -ForegroundColor Yellow
        return
    }
    $signtool = Find-SdkTool 'signtool.exe'
    & $signtool sign /sha1 $SignThumbprint /fd SHA256 /tr $TimestampUrl /td SHA256 @Files
    if ($LASTEXITCODE -ne 0) { throw "signtool failed (exit $LASTEXITCODE)" }
}

function Get-MsixVersion([string]$Root, [int]$Build) {
    # __version__ = "X.YZ" (src\gui\__init__.py, the line the .iss reads too) as the
    # four-part package version X.YZ.<Build>.0. The Store requires the last field 0.
    $file = Join-Path $Root 'src\gui\__init__.py'
    $version = $null
    foreach ($line in Get-Content -LiteralPath $file) {
        # the ASSIGNMENT only - the comment above it mentions __version__ as well
        if ($line -match '^__version__\s*=\s*"([^"]+)"') { $version = $Matches[1] }
    }
    if (-not $version) { throw "Could not read __version__ from $file" }
    $parts = $version.Split('.')
    if ($parts.Count -ne 2 -or ($parts | Where-Object { $_ -notmatch '^\d{1,5}$' -or [int]$_ -gt 65535 })) {
        throw "__version__ '$version' is not X.YZ - the MSIX version needs two numbers here."
    }
    return '{0}.{1}.{2}.0' -f [int]$parts[0], [int]$parts[1], $Build
}

function Get-MsixIdentity([string]$File) {
    # Partner Center > Product identity, copied into installer\msix\store_identity.json.
    # Returns $null while any of the three values is still empty.
    $id = Get-Content -LiteralPath $File -Raw | ConvertFrom-Json
    foreach ($key in 'IdentityName', 'Publisher', 'PublisherDisplayName') {
        if (-not ("$($id.$key)".Trim())) { return $null }
    }
    return $id
}

function Write-MsixManifest([string]$Template, [string]$Target, [hashtable]$Values) {
    # Fill the {{TOKEN}}s of installer\msix\AppxManifest.xml (values XML-escaped),
    # refuse a leftover token, and check that the result parses as XML.
    $xml = Get-Content -LiteralPath $Template -Raw
    foreach ($key in $Values.Keys) {
        $xml = $xml.Replace("{{$key}}", [System.Security.SecurityElement]::Escape([string]$Values[$key]))
    }
    if ($xml -match '\{\{[A-Z_]+\}\}') { throw "AppxManifest.xml: unfilled token $($Matches[0])" }
    [void][xml]$xml
    [IO.File]::WriteAllText($Target, $xml, [Text.UTF8Encoding]::new($false))
}

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
        # the Help markdown + figures, the translation table and the t6 routing
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
        # sign both exes BEFORE the installer packs them
        Invoke-Sign @((Join-Path $Work 'dist\CWatM_GUI\CWatM_GUI.exe'),
                      (Join-Path $Work 'dist\CWatM_GUI\_internal\CWatM_model.exe'))
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
        Invoke-Sign @((Join-Path $Work 'installer\Output\CWatM_GUI_Setup.exe'))
    }
}

# --------------------------------------------------------- MSIX (Microsoft Store)
# The same one-folder build, wrapped as an MSIX package for the Microsoft Store
# (CWatM_GUI_Build.md, "Microsoft Store (MSIX)"). Left unsigned: the Store signs the
# package after certification, and Store installs pass Smart App Control.
if ($Steps -contains 'msix') {
    Write-Step 'MSIX package (Microsoft Store)'
    $msixSrc = Join-Path $Work 'installer\msix'
    if ($MsixTestIdentity) {
        # Distinct from the Store identity, so a local try-out never collides with
        # an installed Store copy.
        $identity = [pscustomobject]@{
            IdentityName         = 'IIASA.CWatMGUI.LocalTest'
            Publisher            = 'CN=CWatM GUI local test'
            PublisherDisplayName = 'IIASA (local test)'
        }
    }
    else {
        $identity = Get-MsixIdentity (Join-Path $msixSrc 'store_identity.json')
    }
    if (-not $identity) {
        Write-Host ("MSIX skipped: fill in installer\msix\store_identity.json from Partner Center > " +
                    "Product identity. (-MsixTestIdentity builds a local test layout without it.)") -ForegroundColor Yellow
    }
    else {
        $dist = Join-Path $Work 'dist\CWatM_GUI'
        if (-not (Test-Path (Join-Path $dist '_internal\CWatM_model.exe'))) {
            throw "No complete build in $dist - run the build step first."
        }
        $version = Get-MsixVersion $Work $MsixBuild
        $msixRoot = Join-Path $Work 'msix'
        $layout = Join-Path $msixRoot 'layout'   # the package contents
        $res = Join-Path $msixRoot 'res'         # manifest + Images only, for makepri
        Write-Host "Identity $($identity.IdentityName), version $version"
        Measure-Step 'msix' {
            # 1. The layout: dist\CWatM_GUI verbatim (_internal\ keeps its exact
            #    layout), plus the logos and the filled-in manifest.
            Invoke-Robocopy $dist $layout @('/MIR', '/MT:16')
            foreach ($dir in $layout, $res) {
                Invoke-Robocopy (Join-Path $msixSrc 'Images') (Join-Path $dir 'Images') @('/MIR')
                Write-MsixManifest (Join-Path $msixSrc 'AppxManifest.xml') (Join-Path $dir 'AppxManifest.xml') @{
                    IDENTITY_NAME          = $identity.IdentityName
                    PUBLISHER              = $identity.Publisher
                    PUBLISHER_DISPLAY_NAME = $identity.PublisherDisplayName
                    VERSION                = $version
                }
            }

            # 2. resources.pri: indexes the qualified logo files (scale-*, targetsize-*,
            #    altform-unplated) so Windows picks the right size for the taskbar,
            #    Start and Settings. Indexed from the small res\ folder: the layout's
            #    thousands of build files are no resources. The <packaging> section is
            #    removed so everything lands in the one resources.pri (it would split
            #    the scale variants into resource packs, which only a bundle carries).
            $makepri = Find-SdkTool 'makepri.exe'
            $priconfig = Join-Path $msixRoot 'priconfig.xml'
            & $makepri createconfig /cf $priconfig /dq en-US /pv 10.0.0 /o
            if ($LASTEXITCODE -ne 0) { throw "makepri createconfig failed (exit $LASTEXITCODE)" }
            [xml]$cfg = Get-Content -LiteralPath $priconfig -Raw
            foreach ($node in @($cfg.SelectNodes('//packaging'))) { [void]$node.ParentNode.RemoveChild($node) }
            $cfg.Save($priconfig)
            $pri = Join-Path $layout 'resources.pri'
            & $makepri new /pr $res /cf $priconfig /mn (Join-Path $res 'AppxManifest.xml') /of $pri /o
            if ($LASTEXITCODE -ne 0) { throw "makepri new failed (exit $LASTEXITCODE)" }
            if (-not (Test-Path $pri)) { throw "makepri did not write $pri" }

            if ($MsixTestIdentity) {
                Write-Host "Local test layout (placeholder identity, no .msix): $layout" -ForegroundColor Green
                Write-Host "  try it (Developer Mode on): Add-AppxPackage -Register '$layout\AppxManifest.xml'" -ForegroundColor Green
                Write-Host "  remove it:                 Get-AppxPackage IIASA.CWatMGUI.LocalTest | Remove-AppxPackage" -ForegroundColor Green
            }
            else {
                # 3. Pack. One package per version in Output; older ones are removed.
                $outDir = Join-Path $Work 'installer\Output'
                if (-not (Test-Path $outDir)) { New-Item -ItemType Directory $outDir | Out-Null }
                Get-ChildItem -LiteralPath $outDir -Filter 'CWatM_GUI_*_x64.msix' | Remove-Item -Force
                $msix = Join-Path $outDir ('CWatM_GUI_{0}_x64.msix' -f $version)
                $makeappx = Find-SdkTool 'makeappx.exe'
                & $makeappx pack /d $layout /p $msix /o
                if ($LASTEXITCODE -ne 0) { throw "makeappx failed (exit $LASTEXITCODE)" }
            }
        }
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
        $outDir = Join-Path $Repo 'installer\Output'
        $setup = Join-Path $Work 'installer\Output\CWatM_GUI_Setup.exe'
        $msixFiles = @(Get-ChildItem -LiteralPath (Join-Path $Work 'installer\Output') -Filter 'CWatM_GUI_*_x64.msix' -ErrorAction SilentlyContinue)
        if ((Test-Path $setup) -or $msixFiles) {
            if (-not (Test-Path $outDir)) { New-Item -ItemType Directory $outDir | Out-Null }
        }
        if (Test-Path $setup) {
            Copy-Item $setup $outDir -Force
        }
        if ($msixFiles) {
            # keep only the current package in the repo's Output as well
            Get-ChildItem -LiteralPath $outDir -Filter 'CWatM_GUI_*_x64.msix' | Remove-Item -Force
            $msixFiles | Copy-Item -Destination $outDir -Force
        }
    }
}

# ----------------------------------------------------------------------- summary
Write-Step 'Summary'
foreach ($k in $script:Times.Keys) { "{0,-10} {1:hh\:mm\:ss}" -f $k, $script:Times[$k] }
$msixOut = @(Get-ChildItem -LiteralPath (Join-Path $Repo 'installer\Output') -Filter 'CWatM_GUI_*_x64.msix' -ErrorAction SilentlyContinue |
    ForEach-Object FullName)
foreach ($p in @((Join-Path $Repo 'dist\CWatM_GUI\CWatM_GUI.exe'),
                 (Join-Path $Repo 'installer\Output\CWatM_GUI_Setup.exe')) + $msixOut) {
    if (Test-Path $p) {
        $i = Get-Item $p
        "{0,-58} {1,8:N1} MB  {2}" -f $i.FullName, ($i.Length / 1MB), $i.LastWriteTime
    }
}
