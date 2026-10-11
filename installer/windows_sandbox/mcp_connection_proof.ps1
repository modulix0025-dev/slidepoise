# Proof: Claude Desktop always finds the Studio (docs/mag/phase-16). ASCII-only file.
# Run by mag-release.yml on a clean windows-latest after the installers are built; runnable in Windows Sandbox.
#   pwsh -File mcp_connection_proof.ps1 -In <installers dir> -Out <results dir>
# A fake Claude Desktop config (with another MCP server that must survive) stands in for Claude Desktop; the
# handshake is run exactly as Claude Desktop runs it: the command/args from that config, JSON-RPC over pipes.
param([string]$In, [string]$Out)
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$Setup = (Get-ChildItem $In -Filter "ModuleX-MagazineStudio-Setup-*.exe" | Where-Object { $_.Name -notlike "*-Full.exe" } | Select-Object -First 1).FullName
$App = "ModuleX Magazine Studio"
$Exe = "$App.exe"
$Default = Join-Path $env:LOCALAPPDATA "Programs\$App"
$Data = Join-Path $env:LOCALAPPDATA "ModuleX\MagazineStudio"
$Launcher = Join-Path $Data "bin\mxstudio-mcp.exe"
$RegKey = "HKCU:\Software\ModuleX\MagazineStudio"
$ClaudeDir = Join-Path $env:APPDATA "Claude"
$Config = Join-Path $ClaudeDir "claude_desktop_config.json"
$Mashrou = -join ([char[]](0x0627, 0x0644, 0x0645, 0x0634, 0x0631, 0x0648, 0x0639))
$env:MXS_WORKSPACE = "C:\$Mashrou\ModuleX_MagazineStudio_Data"
New-Item -ItemType Directory -Force -Path $env:MXS_WORKSPACE | Out-Null
$R = [ordered]@{}
$Timings = @()
# Results are also published as check-run annotations (readable through the GitHub API without downloading logs).
function Publish() {
    $flat = ($R.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join "; "
    Write-Host "::notice title=mcp_connection_proof::$flat"
    $failed = @($R.GetEnumerator() | Where-Object { $_.Value -is [bool] -and -not $_.Value } | ForEach-Object { $_.Key })
    if ($failed.Count -gt 0) { Write-Host ("::error title=mcp_connection_proof FAIL::" + ($failed -join ", ")) }
}
trap {
    $R.exception = "$($_.Exception.Message) @ line $($_.InvocationInfo.ScriptLineNumber): $($_.InvocationInfo.Line.Trim())"
    Publish
    $R | ConvertTo-Json | Set-Content -Path (Join-Path $Out "mcp_connection_proof.json") -Encoding UTF8
    exit 1
}

function Install($arguments) { (Start-Process -FilePath $Setup -ArgumentList $arguments -Wait -PassThru).ExitCode }
function Uninstall($dir) {
    Start-Process -FilePath (Join-Path $dir "uninstall.exe") -ArgumentList "/S" -Wait | Out-Null
    $deadline = (Get-Date).AddSeconds(120)
    while ((Test-Path (Join-Path $dir $Exe)) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 2 }
}
function ReadConfig() { Get-Content -Raw -Encoding UTF8 $Config | ConvertFrom-Json }
function Entry() { $c = ReadConfig; if ($c.mcpServers.PSObject.Properties.Name -contains "modulex-studio") { $c.mcpServers."modulex-studio" } else { $null } }
function RegDir() { (Get-ItemProperty -Path $RegKey -Name InstallDir -ErrorAction SilentlyContinue).InstallDir }

# Starts the command from Claude Desktop's config with pipes, sends initialize + tools/list, reads two replies.
function Handshake([string]$command, [string[]]$arguments) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $command
    $psi.Arguments = ($arguments | ForEach-Object { '"' + $_ + '"' }) -join " "
    $psi.UseShellExecute = $false
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $p = [System.Diagnostics.Process]::Start($psi)
    $errTask = $p.StandardError.ReadToEndAsync()
    $p.StandardInput.WriteLine('{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"proof","version":"1"}}}')
    $p.StandardInput.WriteLine('{"jsonrpc":"2.0","method":"notifications/initialized"}')
    $p.StandardInput.WriteLine('{"jsonrpc":"2.0","id":2,"method":"tools/list"}')
    $p.StandardInput.Flush()
    $lines = @()
    $junk = @()
    $tools = 0
    $readTask = $p.StandardOutput.ReadLineAsync()
    while ($lines.Count -lt 2) {
        if (-not $readTask.Wait(60000)) { break }
        $line = $readTask.Result
        if ($null -eq $line) { break }
        try { $msg = $line | ConvertFrom-Json; $lines += $msg; if ($msg.id -eq 2) { $tools = @($msg.result.tools).Count } }
        catch { $junk += $line }
        if ($lines.Count -lt 2) { $readTask = $p.StandardOutput.ReadLineAsync() }
    }
    $seconds = [math]::Round($watch.Elapsed.TotalSeconds, 2)
    $p.StandardInput.Close()
    if (-not $p.WaitForExit(30000)) { $p.Kill() }
    $err = ""
    if ($errTask.Wait(5000)) { $err = $errTask.Result }
    [pscustomobject]@{ ok = ($lines.Count -eq 2 -and $tools -gt 40 -and $junk.Count -eq 0); seconds = $seconds; tools = $tools; junk = $junk.Count; stderr = ($err | Out-String).Trim() }
}

# 0. Claude Desktop "installed": its folder and a config holding another server that must never be lost
New-Item -ItemType Directory -Force -Path $ClaudeDir | Out-Null
Set-Content -Path $Config -Encoding UTF8 -Value '{"mcpServers":{"filesystem":{"command":"npx","args":["-y","@modelcontextprotocol/server-filesystem","C:\\"]}},"globalShortcut":"Ctrl+Space"}'

# 1. default install: registry, launcher in the app home, entry on the launcher, other server kept, backup made
$code = Install "/S"
$R.install_default = ($code -eq 0) -and (Test-Path (Join-Path $Default $Exe))
$R.registry_installdir = ((RegDir) -eq $Default)
$R.launcher_in_app_home = Test-Path $Launcher
$e = Entry
$R.entry_is_fixed_launcher = ($null -ne $e) -and ($e.command -eq $Launcher) -and (@($e.args).Count -eq 0)
$cfg = ReadConfig
$R.other_server_kept = ($cfg.mcpServers.filesystem.command -eq "npx") -and ($cfg.globalShortcut -eq "Ctrl+Space")
$R.backup_written = @(Get-ChildItem $ClaudeDir -Filter "claude_desktop_config.json.bak-*").Count -ge 1
$connect = Join-Path $Data "logs\mcp-connect.json"
if (Test-Path $connect) {
    Copy-Item $connect (Join-Path $Out "mcp-connect.json")
    $cj = Get-Content -Raw -Encoding UTF8 $connect | ConvertFrom-Json
    $R.install_connect_self_test = "ok=$($cj.self_test.ok) tools=$($cj.self_test.tools) s=$($cj.self_test.seconds) cache=$($cj.tools_cache.tools)"
} else { $R.install_connect_self_test = "no mcp-connect.json" }

# 2. 20 handshakes in a row exactly as Claude Desktop starts the server (the window open), then 5 in parallel
$window = Start-Process -FilePath (Join-Path $Default $Exe) -PassThru
Start-Sleep -Seconds 20
$allOk = $true
$allFast = $true
for ($i = 1; $i -le 20; $i++) {
    $h = Handshake $e.command @($e.args)
    $Timings += [pscustomobject]@{ run = $i; mode = "serial"; seconds = $h.seconds; tools = $h.tools; ok = $h.ok; junk = $h.junk }
    if (-not $h.ok) {
        $allOk = $false; Add-Content (Join-Path $Out "handshake-stderr.txt") $h.stderr
        if (-not $R.Contains("first_failed_handshake")) {
            $R.first_failed_handshake = "run $i tools=$($h.tools) junk=$($h.junk) s=$($h.seconds) stderr=" + ($h.stderr -replace "[\r\n]+", " | ").Substring(0, [math]::Min(400, $h.stderr.Length))
        }
    }
    if ($h.seconds -ge 2) { $allFast = $false }
}
$parallel = @()
foreach ($n in 1..5) {
    $parallel += Start-Job -ScriptBlock {
        param($cmd)
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $cmd; $psi.UseShellExecute = $false; $psi.RedirectStandardInput = $true
        $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true; $psi.CreateNoWindow = $true
        $p = [System.Diagnostics.Process]::Start($psi)
        $p.StandardInput.WriteLine('{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"p","version":"1"}}}')
        $p.StandardInput.WriteLine('{"jsonrpc":"2.0","id":2,"method":"tools/list"}')
        $p.StandardInput.Flush()
        $a = $p.StandardOutput.ReadLine(); $b = $p.StandardOutput.ReadLine()
        $s = [math]::Round($sw.Elapsed.TotalSeconds, 2)
        $p.StandardInput.Close(); [void]$p.WaitForExit(30000)
        $ok = $false
        try { $ok = (($a | ConvertFrom-Json).id -eq 1) -and (@(($b | ConvertFrom-Json).result.tools).Count -gt 40) } catch { $ok = $false }
        [pscustomobject]@{ ok = $ok; seconds = $s }
    } -ArgumentList $e.command
}
$parallelResults = $parallel | Wait-Job -Timeout 240 | Receive-Job
$parallel | Remove-Job -Force -ErrorAction SilentlyContinue
foreach ($p in $parallelResults) {
    $Timings += [pscustomobject]@{ run = 0; mode = "parallel"; seconds = $p.seconds; tools = 0; ok = $p.ok; junk = 0 }
    if (-not $p.ok) { $allOk = $false }
}
$R.handshake_20x_and_parallel_ok = $allOk -and (@($parallelResults).Count -eq 5)
$R.handshake_all_under_2s = $allFast
$Timings | ConvertTo-Json | Set-Content -Path (Join-Path $Out "mcp_handshake_timings.json") -Encoding UTF8
$R.handshake_max_seconds = ($Timings | Measure-Object -Property seconds -Maximum).Maximum

# 3. single instance: two more starts while the window is open -> still one window process
Start-Process -FilePath (Join-Path $Default $Exe) | Out-Null
Start-Process -FilePath (Join-Path $Default $Exe) | Out-Null
# the second start must exit by itself; poll instead of a fixed sleep and record how long it took
$t0 = Get-Date
Start-Sleep -Seconds 5
do {
    $R.single_instance_count = @(Get-Process -Name $App -ErrorAction SilentlyContinue).Count
    if ($R.single_instance_count -eq 1) { break }
    Start-Sleep -Seconds 2
} while (((Get-Date) - $t0).TotalSeconds -lt 45)
$R.single_instance_seconds = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
$R.single_instance = ($R.single_instance_count -eq 1)

# 4. self-heal on open: delete our entry by hand, open the Studio again -> the entry is back, other server kept
Get-Process -Name $App -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Process -FilePath (Join-Path $Default "mxstudio-cli.exe") -ArgumentList "shutdown" -Wait -WindowStyle Hidden | Out-Null
Start-Sleep -Seconds 3
$cfg = ReadConfig
$cfg.mcpServers.PSObject.Properties.Remove("modulex-studio")
$cfg | ConvertTo-Json -Depth 10 | Set-Content -Path $Config -Encoding UTF8
Start-Process -FilePath (Join-Path $Default $Exe) | Out-Null
$deadline = (Get-Date).AddSeconds(120)
while (-not (Entry) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 3 }
$e2 = Entry
$R.self_heal_entry_back = ($null -ne $e2) -and ($e2.command -eq $Launcher)
$R.self_heal_other_server_kept = ((ReadConfig).mcpServers.filesystem.command -eq "npx")
$state = Join-Path $Data "mcp_state.json"
$deadline = (Get-Date).AddSeconds(120)
while ((Get-Date) -lt $deadline) {
    if ((Test-Path $state) -and ((Get-Content -Raw -Encoding UTF8 $state | ConvertFrom-Json).last_heal.self_test)) { break }
    Start-Sleep -Seconds 3
}
if (Test-Path $state) {
    Copy-Item $state (Join-Path $Out "mcp_state.json")
    $R.self_test_on_open = [bool]((Get-Content -Raw -Encoding UTF8 $state | ConvertFrom-Json).last_heal.self_test.ok)
} else { $R.self_test_on_open = $false }
Get-Process -Name $App -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Process -FilePath (Join-Path $Default "mxstudio-cli.exe") -ArgumentList "shutdown" -Wait -WindowStyle Hidden | Out-Null
Start-Sleep -Seconds 3

# 5. uninstall: only our entry leaves; reinstall elsewhere: the SAME entry works with no edit to the config
$before = $e2.command
Uninstall $Default
$R.uninstall_removed_only_ours = ($null -eq (Entry)) -and ((ReadConfig).mcpServers.filesystem.command -eq "npx")
$R.uninstall_cleared_installdir = -not (RegDir)
$Other = "C:\mxs other place\$App"
$code = Install "/S /D=$Other"
$R.reinstall_other_folder = ($code -eq 0) -and (Test-Path (Join-Path $Other $Exe))
$R.registry_follows_move = ((RegDir) -eq $Other)
$e3 = Entry
$R.entry_unchanged_after_move = ($null -ne $e3) -and ($e3.command -eq $before)
$h = Handshake $e3.command @($e3.args)
$R.handshake_after_move = $h.ok
$R.handshake_after_move_seconds = $h.seconds
Uninstall $Other

# 6. a silent install aimed at OneDrive\Desktop is moved to the default folder
$fake = Join-Path $env:USERPROFILE "OneDrive"
New-Item -ItemType Directory -Force -Path (Join-Path $fake "Desktop") | Out-Null
[Environment]::SetEnvironmentVariable("OneDrive", $fake, "Process")
$target = Join-Path $fake "Desktop\$App"
$code = Install "/S /D=$target"
$R.onedrive_refused_moved_to_default = ($code -eq 0) -and (Test-Path (Join-Path $Default $Exe)) -and -not (Test-Path (Join-Path $target $Exe))
$R.onedrive_registry_default = ((RegDir) -eq $Default)
Uninstall $Default

$R | ConvertTo-Json | Set-Content -Path (Join-Path $Out "mcp_connection_proof.json") -Encoding UTF8
Publish
$R.GetEnumerator() | ForEach-Object {
    if ($_.Value -is [bool]) { Write-Host ("  {0,-36} {1}" -f $_.Key, $(if ($_.Value) { "PASS" } else { "FAIL" })) }
    else { Write-Host ("  {0,-36} {1}" -f $_.Key, $_.Value) }
}
if (@($R.Values | Where-Object { $_ -is [bool] -and -not $_ }).Count -gt 0) { exit 1 }
