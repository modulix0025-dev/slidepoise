# ModuleX Magazine Studio - clean-machine proof inside Windows Sandbox (ASCII-only file).
# Started hidden by sandbox_logon.cmd. Writes everything to Desktop\mxs-results and opens summary.txt.
#   1. SHA256 of every installer against SHA256SUMS (the integrity check users do by hand)
#   2. online flavour: silent per-user install -> files present -> Doctor -> uninstall (/S):
#      program folder gone, data and workspace kept
#   3. Full flavour (if present): same, and the Doctor "office" line must be green (LibreOffice extracted)
#   4. standard-user proof (if a LibreOffice MSI is present): standard_user_proof.ps1
# The same script is the installed-app smoke test of mag-release.yml:
#   pwsh -File sandbox_proof.ps1 -In <installers dir> -Out <results dir> -Ci   (exit 1 on any FAIL)
param(
    [string]$In = "",
    [string]$Out = "",
    [switch]$Ci,
    [switch]$SkipStandardUser
)
$ErrorActionPreference = "Continue"
if (-not $In) { $In = Join-Path $env:USERPROFILE "Desktop\mxs" }
if (-not $Out) { $Out = Join-Path $env:USERPROFILE "Desktop\mxs-results" }
$Here = $PSScriptRoot
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$Log = Join-Path $Out "summary.txt"
$AppDir = Join-Path $env:LOCALAPPDATA "Programs\ModuleX Magazine Studio"
$DataDir = Join-Path $env:LOCALAPPDATA "ModuleX\MagazineStudio"
# Workspace on an Arabic path, built from code points so this file stays ASCII ("C:\<almashrou3>")
$Mashrou = -join ([char[]](0x0627, 0x0644, 0x0645, 0x0634, 0x0631, 0x0648, 0x0639))
$Workspace = "C:\$Mashrou\ModuleX_MagazineStudio_Data"
$Results = [ordered]@{}

function Say($text) { Add-Content -Path $Log -Value $text -Encoding UTF8 }
function Wait-Gone($path, $seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Test-Path $path) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 2 }
    return -not (Test-Path $path)
}

Say "ModuleX Magazine Studio - Sandbox proof $(Get-Date -Format s)"
Say "user: $(whoami)"

# 1. SHA256
$Sums = Join-Path $In "SHA256SUMS"
if (Test-Path $Sums) {
    foreach ($line in Get-Content $Sums) {
        $parts = $line -split "\s+\*?", 2
        if ($parts.Count -lt 2) { continue }
        $file = Join-Path $In $parts[1].Trim()
        if (-not (Test-Path $file)) { continue }
        $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $file).Hash.ToLowerInvariant()
        $ok = $actual -eq $parts[0].ToLowerInvariant()
        $Results["sha256 $($parts[1].Trim())"] = $ok
        Say "sha256 $($parts[1].Trim()): $ok"
    }
} else { Say "SHA256SUMS not found - skipped" }

function Prove-Flavour($label, $setup, [bool]$expectOffice) {
    Say "--- $label : $([IO.Path]::GetFileName($setup))"
    $p = Start-Process -FilePath $setup -ArgumentList "/S" -Wait -PassThru
    $installed = Test-Path (Join-Path $AppDir "mxstudio-cli.exe")
    Say "install exit=$($p.ExitCode) cli_present=$installed"
    $Results["$label install"] = ($p.ExitCode -eq 0) -and $installed
    if ($installed) {
        $env:MXS_WORKSPACE = $Workspace
        New-Item -ItemType Directory -Force -Path $Workspace | Out-Null
        Set-Content -Path (Join-Path $Workspace "keep-me.txt") -Value "workspace survives uninstall" -Encoding UTF8
        New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
        Set-Content -Path (Join-Path $DataDir "keep-me.txt") -Value "app data survives uninstall (default No)" -Encoding UTF8
        $report = Join-Path $Out "doctor-$label.json"
        Start-Process -FilePath (Join-Path $AppDir "mxstudio-cli.exe") -ArgumentList @("doctor", "--json", "--out", "`"$report`"") -Wait -WindowStyle Hidden | Out-Null
        if (Test-Path $report) {
            $doc = Get-Content -Raw -Encoding UTF8 $report | ConvertFrom-Json
            foreach ($c in $doc.checks) { Say ("  doctor {0,-16} {1,-5} {2}" -f $c.id, $c.level, $c.en) }
            $need = @("python", "node", "pypdfium2", "arabic_path", "workspace", "webview2")
            if ($expectOffice) { $need += "office" }
            $bad = @($doc.checks | Where-Object { ($need -contains $_.id) -and (-not $_.ok) })
            $Results["$label doctor"] = ($bad.Count -eq 0)
        } else { $Results["$label doctor"] = $false; Say "  doctor wrote no report" }
        Remove-Item Env:MXS_WORKSPACE
    }
    $u = Join-Path $AppDir "uninstall.exe"
    if (Test-Path $u) {
        Start-Process -FilePath $u -ArgumentList "/S" -Wait | Out-Null
        $gone = Wait-Gone $AppDir 180
        $kept = (Test-Path (Join-Path $Workspace "keep-me.txt")) -and (Test-Path (Join-Path $DataDir "keep-me.txt"))
        Say "uninstall program_gone=$gone workspace_and_data_kept=$kept"
        $Results["$label uninstall"] = $gone -and $kept
    }
}

# 2/3. flavours
$Online = Get-ChildItem -Path $In -Filter "ModuleX-MagazineStudio-Setup-*.exe" | Where-Object { $_.Name -notlike "*-Full.exe" } | Select-Object -First 1
$Full = Get-ChildItem -Path $In -Filter "ModuleX-MagazineStudio-Setup-*-Full.exe" | Select-Object -First 1
if ($Online) { Prove-Flavour "online" $Online.FullName $false } else { Say "online installer not found" }
if ($Full) { Prove-Flavour "full" $Full.FullName $true } else { Say "Full installer not found - skipped" }

# 4. standard user
$Msi = Get-ChildItem -Path $In -Filter "*.msi" | Select-Object -First 1
if (($Msi -or $Online) -and -not $SkipStandardUser) {
    $proofArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$Here\standard_user_proof.ps1`"", "-OutDir", "`"$Out\standard-user`"")
    if ($Msi) { $proofArgs += @("-Msi", "`"$($Msi.FullName)`"") }
    if ($Online) { $proofArgs += @("-Setup", "`"$($Online.FullName)`"") }
    $s = Start-Process powershell.exe -ArgumentList $proofArgs -Wait -PassThru -WindowStyle Hidden
    $Results["standard user"] = ($s.ExitCode -eq 0)
    Say "standard-user proof exit=$($s.ExitCode) (see standard-user\standard_user_proof.json)"
}

Say ""
Say "RESULT"
foreach ($k in $Results.Keys) { Say ("  {0,-40} {1}" -f $k, $(if ($Results[$k]) { "PASS" } else { "FAIL" })) }
$Results | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $Out "results.json")
$Failed = @($Results.Keys | Where-Object { -not $Results[$_] })
if ($Ci) {
    Get-Content $Log | ForEach-Object { Write-Host $_ }
    if ($Failed.Count -gt 0 -or $Results.Count -eq 0) { exit 1 } else { exit 0 }
}
Start-Process notepad.exe -ArgumentList "`"$Log`""
