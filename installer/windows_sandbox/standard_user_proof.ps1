# Proof that ModuleX Magazine Studio needs NO admin rights (ASCII-only file).
# Used by the CI job "standard-user-proof" (mag-release.yml) and by sandbox_proof.ps1.
#
# Must be started from an elevated PowerShell (it creates a throw-away STANDARD local user),
# then everything under test runs AS THAT STANDARD USER through a scheduled task:
#   -Msi   LibreOffice MSI : msiexec /a <msi> /qn TARGETDIR=<dir>  (administrative extraction)
#   -Setup Studio setup exe: Setup.exe /S  (per-user install), then mxstudio-cli.exe doctor
# Result: <OutDir>\standard_user_proof.json  (exit 0 only when every requested part passed)
param(
    [string]$Msi = "",
    [string]$Setup = "",
    [Parameter(Mandatory = $true)][string]$OutDir,
    [int]$TimeoutMinutes = 40
)
$ErrorActionPreference = "Stop"
$User = "mxsstd"
$Proof = "C:\mxs-proof"
New-Item -ItemType Directory -Force -Path $OutDir, $Proof | Out-Null

function Grant-BatchLogon([string]$Account) {
    # scheduled tasks "run whether logged on or not" need SeBatchLogonRight; Users do not have it on Server
    $sid = (New-Object System.Security.Principal.NTAccount($Account)).Translate([System.Security.Principal.SecurityIdentifier]).Value
    $tmp = Join-Path $env:TEMP "mxs-secpol"
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    secedit /export /cfg "$tmp\cur.inf" /areas USER_RIGHTS | Out-Null
    $line = Get-Content "$tmp\cur.inf" | Where-Object { $_ -like "SeBatchLogonRight*" } | Select-Object -First 1
    if ($line) { $new = "$line,*$sid" } else { $new = "SeBatchLogonRight = *$sid" }
    $inf = @("[Unicode]", "Unicode=yes", "[Version]", 'signature="$CHICAGO$"', "Revision=1", "[Privilege Rights]", $new)
    Set-Content -Path "$tmp\new.inf" -Value $inf -Encoding Unicode
    secedit /configure /db "$tmp\new.sdb" /cfg "$tmp\new.inf" /areas USER_RIGHTS | Out-Null
}

# 1. throw-away standard user (member of Users only)
$Plain = "Mx!" + [guid]::NewGuid().ToString("N").Substring(0, 16) + "a9"
$Secure = ConvertTo-SecureString $Plain -AsPlainText -Force
if (Get-LocalUser -Name $User -ErrorAction SilentlyContinue) { Remove-LocalUser -Name $User }
New-LocalUser -Name $User -Password $Secure -PasswordNeverExpires -AccountNeverExpires -Description "ModuleX standard-user proof" | Out-Null
Add-LocalGroupMember -Group "Users" -Member $User -ErrorAction SilentlyContinue
Grant-BatchLogon $User
icacls $Proof /grant "${User}:(OI)(CI)M" | Out-Null

# 2. inputs copied where the standard user can read them
$Parts = @()
if ($Msi) { Copy-Item -LiteralPath $Msi "$Proof\LibreOffice.msi" -Force; $Parts += "msi" }
if ($Setup) { Copy-Item -LiteralPath $Setup "$Proof\Setup.exe" -Force; $Parts += "setup" }
if ($Parts.Count -eq 0) { throw "nothing to prove: pass -Msi and/or -Setup" }

# 3. the script that runs AS the standard user
$Inner = @'
$ErrorActionPreference = "Continue"
$P = "C:\mxs-proof"
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$admin = ([Security.Principal.WindowsPrincipal]$id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$r = [ordered]@{ user = $id.Name; is_admin = $admin }
if (Test-Path "$P\LibreOffice.msi") {
    $a = Start-Process msiexec.exe -ArgumentList @("/a", "`"$P\LibreOffice.msi`"", "/qn", "TARGETDIR=`"$P\lo`"", "/L*v", "`"$P\msi.log`"") -Wait -PassThru
    $soffice = Get-ChildItem -Path "$P\lo" -Recurse -Filter soffice.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    $r.msi_exit = $a.ExitCode
    $r.soffice = if ($soffice) { $soffice.FullName } else { "" }
    $r.soffice_version = if ($soffice) { $soffice.VersionInfo.ProductVersion } else { "" }
}
if (Test-Path "$P\Setup.exe") {
    $s = Start-Process "$P\Setup.exe" -ArgumentList "/S" -Wait -PassThru
    $app = Join-Path $env:LOCALAPPDATA "Programs\ModuleX Magazine Studio"
    $r.setup_exit = $s.ExitCode
    $r.app_dir = $app
    $r.cli_present = Test-Path (Join-Path $app "mxstudio-cli.exe")
    if ($r.cli_present) {
        $d = Start-Process (Join-Path $app "mxstudio-cli.exe") -ArgumentList @("doctor", "--json", "--out", "`"$P\doctor.json`"") -Wait -PassThru -WindowStyle Hidden
        $r.doctor_exit = $d.ExitCode
        $r.doctor_report = Test-Path "$P\doctor.json"
    }
}
$r | ConvertTo-Json | Set-Content -Encoding UTF8 "$P\inner.json"
'@
Set-Content -Path "$Proof\inner.ps1" -Value $Inner -Encoding ASCII
Remove-Item "$Proof\inner.json" -ErrorAction SilentlyContinue

# 4. run it as the standard user (RunLevel Limited = never elevated)
# A scheduled task is a BATCH logon (no INTERACTIVE SID). Windows Installer refuses a standard user's
# msiexec there with 1601 even when its service runs (CI evidence, 2026-10-11); on a real desktop the
# operator is interactive. 1601 is therefore recorded as "not provable on a batch logon", never as a pass.
$Task = "mxs-standard-user-proof"
Unregister-ScheduledTask -TaskName $Task -Confirm:$false -ErrorAction SilentlyContinue
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Proof\inner.ps1`""
Register-ScheduledTask -TaskName $Task -Action $Action -User "$env:COMPUTERNAME\$User" -Password $Plain -RunLevel Limited | Out-Null
Start-ScheduledTask -TaskName $Task
$Deadline = (Get-Date).AddMinutes($TimeoutMinutes)
do {
    Start-Sleep -Seconds 10
    $State = (Get-ScheduledTask -TaskName $Task).State
} while (($State -eq "Running" -or -not (Test-Path "$Proof\inner.json")) -and (Get-Date) -lt $Deadline)
$Info = Get-ScheduledTaskInfo -TaskName $Task

# 5. verdict (facts only)
$Result = [ordered]@{ parts = $Parts; task_last_result = $Info.LastTaskResult; finished = (Test-Path "$Proof\inner.json") }
if ($Result.finished) {
    $InnerResult = Get-Content -Raw -Encoding UTF8 "$Proof\inner.json" | ConvertFrom-Json
    $Result.inner = $InnerResult
    $ok = (-not $InnerResult.is_admin)
    if ($Parts -contains "msi") {
        if ($InnerResult.msi_exit -eq 1601) {
            $Result.msi = "not_provable_batch_logon"  # see the note above step 4; the setup part still decides
        } else {
            $Result.msi = if (($InnerResult.msi_exit -eq 0) -and [bool]$InnerResult.soffice) { "ok" } else { "failed" }
            $ok = $ok -and ($Result.msi -eq "ok")
        }
    }
    if ($Parts -contains "setup") { $ok = $ok -and ($InnerResult.setup_exit -eq 0) -and $InnerResult.cli_present -and $InnerResult.doctor_report }
    $Result.ok = $ok
} else {
    $Result.ok = $false
}
if (Test-Path "$Proof\msi.log") { Copy-Item "$Proof\msi.log" $OutDir -Force }
if (Test-Path "$Proof\doctor.json") { Copy-Item "$Proof\doctor.json" (Join-Path $OutDir "doctor-standard-user.json") -Force }
$Result | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 (Join-Path $OutDir "standard_user_proof.json")
Get-Content (Join-Path $OutDir "standard_user_proof.json")

# 6. cleanup: task and user go away; files stay for the record
Unregister-ScheduledTask -TaskName $Task -Confirm:$false -ErrorAction SilentlyContinue
Remove-LocalUser -Name $User -ErrorAction SilentlyContinue
if ($Result.ok) { exit 0 } else { exit 1 }
