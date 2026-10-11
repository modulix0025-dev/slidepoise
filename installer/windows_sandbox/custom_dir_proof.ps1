# Proof: the program installs where the operator chooses, updates stay there, and a folder that
# already holds other files is never emptied by the uninstaller. ASCII-only file (Arabic built
# from code points). Used by the release workflow on windows-latest; runnable in Windows Sandbox.
#   powershell -ExecutionPolicy Bypass -File custom_dir_proof.ps1 -In <installers dir> -Out <results dir>
param([string]$In, [string]$Out)
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$Setup = (Get-ChildItem $In -Filter "ModuleX-MagazineStudio-Setup-*.exe" | Where-Object { $_.Name -notlike "*-Full.exe" } | Select-Object -First 1).FullName
$App = "ModuleX Magazine Studio"
$Exe = "$App.exe"
$Key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{7F41B915-3B66-4225-836B-E52016D9E01E}"
$Ar = -join ([char[]](0x0628, 0x0631, 0x0627, 0x0645, 0x062C))   # "programs" in Arabic
$Base = Join-Path $env:TEMP "mxs custom $Ar"
$Custom = Join-Path $Base $App
$Default = Join-Path $env:LOCALAPPDATA "Programs\$App"
$R = [ordered]@{}

function Install($arguments) { (Start-Process -FilePath $Setup -ArgumentList $arguments -Wait -PassThru).ExitCode }
function Uninstall($dir) {
    Start-Process -FilePath (Join-Path $dir "uninstall.exe") -ArgumentList "/S" -Wait | Out-Null
    $deadline = (Get-Date).AddSeconds(90)
    while ((Test-Path (Join-Path $dir $Exe)) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 2 }
}
function Shortcut() { (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path ([Environment]::GetFolderPath("Desktop")) "$App.lnk")) }

# 1. silent install into the chosen folder (NSIS: /D= is last and unquoted)
$code = Install "/S /D=$Custom"
$R.custom_install = ($code -eq 0) -and (Test-Path (Join-Path $Custom $Exe)) -and -not (Test-Path (Join-Path $Default $Exe))
$R.registry_location = ((Get-ItemProperty $Key).InstallLocation -eq $Custom)
$lnk = Shortcut
# compare the file itself: Windows may store the long form of a short (8.3) TEMP path, or the reverse
$target = $lnk.TargetPath
$R.shortcut_target = (Test-Path $target) -and ($target.EndsWith("$App\$Exe")) -and
    ((Get-FileHash $target).Hash -eq (Get-FileHash (Join-Path $Custom $Exe)).Hash) -and ($lnk.IconLocation -like "*$Exe,0")
$R.shortcut_detail = "target=$target icon=$($lnk.IconLocation)"

# 2. an update (silent, no /D) goes back to the same folder
$code = Install "/S"
$R.update_stays = ($code -eq 0) -and (Test-Path (Join-Path $Custom $Exe)) -and -not (Test-Path (Join-Path $Default $Exe))

# 3. uninstall removes the program folder and the registration
Uninstall $Custom
$R.uninstall_removed = -not (Test-Path (Join-Path $Custom $Exe)) -and -not (Test-Path $Key)

# 4. a folder that already holds the operator's files: the program goes into its own subfolder,
#    and uninstalling never touches the operator's file
$Shared = Join-Path $env:TEMP "mxs shared $Ar"
New-Item -ItemType Directory -Force -Path $Shared | Out-Null
Set-Content -Path (Join-Path $Shared "keep.txt") -Value "operator file" -Encoding UTF8
$code = Install "/S /D=$Shared"
$Sub = Join-Path $Shared $App
$R.shared_goes_to_subfolder = ($code -eq 0) -and (Test-Path (Join-Path $Sub $Exe)) -and -not (Test-Path (Join-Path $Shared $Exe))
Uninstall $Sub
$R.shared_file_kept = (Test-Path (Join-Path $Shared "keep.txt")) -and -not (Test-Path (Join-Path $Sub $Exe))

$R | ConvertTo-Json | Set-Content -Path (Join-Path $Out "custom_dir_proof.json") -Encoding UTF8
$R.GetEnumerator() | ForEach-Object {
    if ($_.Value -is [bool]) { Write-Host ("  {0,-26} {1}" -f $_.Key, $(if ($_.Value) { "PASS" } else { "FAIL" })) }
    else { Write-Host ("  {0,-26} {1}" -f $_.Key, $_.Value) }
}
if (@($R.Values | Where-Object { $_ -is [bool] -and -not $_ }).Count -gt 0) { exit 1 }
