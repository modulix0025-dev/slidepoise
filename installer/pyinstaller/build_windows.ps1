# Build the ModuleX Magazine Studio one-folder app on Windows (ASCII-only file).
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File installer\pyinstaller\build_windows.ps1 -Version 0.2.0
#
# Steps: build venv -> pinned requirements -> PyInstaller spec -> portable Node (sha256 pinned in
# installer\downloads.json) + npm ci --omit=dev (pptxgenjs, jszip from package-lock.json) ->
# build_info.json -> smoke: mxstudio-cli.exe doctor --out (windowed exe, so JSON goes to a file).
# Output: workspace\dist\ModuleX Magazine Studio\
param(
    [string]$Version = "",
    [string]$Python = "python",
    [switch]$SkipSmoke
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Work = Join-Path $Root "workspace"
$Venv = Join-Path $Work "build-venv"
$Dist = Join-Path $Work "dist"
$AppName = "ModuleX Magazine Studio"
$App = Join-Path $Dist $AppName
$env:PYTHONUTF8 = "1"

function Step($text) { Write-Host "==> $text" }

# 0. version guard: the release version must equal mxstudio.config.APP_VERSION, or the updater would loop
$AppVersion = (& $Python -c "import sys; sys.path.insert(0, r'$Root'); from mxstudio.config import APP_VERSION; print(APP_VERSION)").Trim()
if ($Version -and ($Version -ne $AppVersion)) { throw "Version $Version does not match mxstudio.config.APP_VERSION $AppVersion" }
if (-not $Version) { $Version = $AppVersion }
Step "version $Version"

# 1. build venv with pinned requirements
if (-not (Test-Path (Join-Path $Venv "Scripts\python.exe"))) { & $Python -m venv $Venv }
$Py = Join-Path $Venv "Scripts\python.exe"
& $Py -m pip install --upgrade pip | Out-Null
& $Py -m pip install -r (Join-Path $PSScriptRoot "requirements-windows.txt")
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# 2. PyInstaller one-folder (two windowed exes)
Step "PyInstaller"
& $Py -m PyInstaller --noconfirm --clean --distpath $Dist --workpath (Join-Path $Work "pyi-build") (Join-Path $PSScriptRoot "MagazineStudio.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
foreach ($exe in @("$AppName.exe", "mxstudio-cli.exe")) {
    if (-not (Test-Path (Join-Path $App $exe))) { throw "missing $exe" }
}

# 3. portable Node runtime, pinned by sha256
Step "Node runtime"
$Downloads = Get-Content -Raw -Encoding UTF8 (Join-Path $Root "installer\downloads.json") | ConvertFrom-Json
$Node = $Downloads.entries.node_runtime
$Cache = Join-Path $Work "download-cache"
New-Item -ItemType Directory -Force -Path $Cache | Out-Null
$Zip = Join-Path $Cache $Node.file_name
if (-not (Test-Path $Zip)) { Invoke-WebRequest -Uri $Node.url -OutFile $Zip -UseBasicParsing }
$Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Zip).Hash.ToLowerInvariant()
if ($Hash -ne $Node.sha256) { Remove-Item $Zip; throw "Node zip sha256 $Hash does not match the pin $($Node.sha256)" }
$NodeTmp = Join-Path $Work "node-extract"
if (Test-Path $NodeTmp) { Remove-Item -Recurse -Force $NodeTmp }
Expand-Archive -LiteralPath $Zip -DestinationPath $NodeTmp
$NodeHome = (Get-ChildItem -Directory $NodeTmp | Select-Object -First 1).FullName
$NodeOut = Join-Path $App "node"
New-Item -ItemType Directory -Force -Path $NodeOut | Out-Null
Copy-Item (Join-Path $NodeHome "node.exe") $NodeOut
Copy-Item (Join-Path $NodeHome "LICENSE") (Join-Path $NodeOut "LICENSE.node.txt")

# 4. node_modules (pptxgenjs + jszip, exact versions from package-lock.json), no dev deps, no scripts
Step "node_modules"
$Stage = Join-Path $Work "node-stage"
if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
New-Item -ItemType Directory -Force -Path $Stage | Out-Null
Copy-Item (Join-Path $Root "package.json"), (Join-Path $Root "package-lock.json") $Stage
$env:PATH = "$NodeHome;$env:PATH"
Push-Location $Stage
& (Join-Path $NodeHome "npm.cmd") ci --omit=dev --ignore-scripts --no-audit --no-fund
$NpmExit = $LASTEXITCODE
Pop-Location
if ($NpmExit -ne 0) { throw "npm ci failed" }
Copy-Item -Recurse (Join-Path $Stage "node_modules") (Join-Path $NodeOut "node_modules")
foreach ($m in @("pptxgenjs", "jszip")) {
    if (-not (Test-Path (Join-Path $NodeOut "node_modules\$m\package.json"))) { throw "missing node module $m" }
}

# 5. build record
$Commit = ""
try { $Commit = (git -C $Root rev-parse HEAD).Trim() } catch { }
$Info = [ordered]@{ app = $AppName; version = $Version; commit = $Commit; node = $Node.version;
                    built_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ") }
$Info | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $App "build_info.json")

# 6. smoke: the windowed CLI writes its JSON to a file; Start-Process -Wait because GUI-subsystem exes do not block
if (-not $SkipSmoke) {
    Step "smoke: doctor"
    $Smoke = Join-Path $Work "smoke"
    if (Test-Path $Smoke) { Remove-Item -Recurse -Force $Smoke }
    # Arabic folder name ("masar") built from code points so this file stays ASCII
    $Ar = -join ([char[]](0x0645, 0x0633, 0x0627, 0x0631))
    $env:MXS_HOME = Join-Path $Smoke "home"
    $env:MXS_WORKSPACE = Join-Path $Smoke "$Ar workspace"
    New-Item -ItemType Directory -Force -Path $env:MXS_WORKSPACE | Out-Null
    $Report = Join-Path $Smoke "doctor.json"
    $p = Start-Process -FilePath (Join-Path $App "mxstudio-cli.exe") -ArgumentList @("doctor", "--json", "--out", "`"$Report`"") -Wait -PassThru -WindowStyle Hidden
    if (-not (Test-Path $Report)) { throw "doctor wrote no report (exit $($p.ExitCode))" }
    $Doc = Get-Content -Raw -Encoding UTF8 $Report | ConvertFrom-Json
    $Required = @("python", "node", "pypdfium2", "arabic_path", "workspace")
    $Bad = @($Doc.checks | Where-Object { ($Required -contains $_.id) -and (-not $_.ok) })
    $Doc.checks | ForEach-Object { Write-Host ("  {0,-16} {1,-5} {2}" -f $_.id, $_.level, $_.en) }
    if ($Bad.Count -gt 0) { throw "doctor smoke failed: $(($Bad | ForEach-Object { $_.id }) -join ', ')" }
    # MCP over stdio through the windowed CLI (no console): initialize + tools/list from a file
    Step "smoke: mcp"
    $McpIn = Join-Path $Smoke "mcp-in.jsonl"
    $McpOut = Join-Path $Smoke "mcp-out.jsonl"
    $Lines = @(
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke","version":"1"}}}',
        '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
    )
    [System.IO.File]::WriteAllText($McpIn, ($Lines -join "`n") + "`n", (New-Object System.Text.UTF8Encoding($false)))
    $m = Start-Process -FilePath (Join-Path $App "mxstudio-cli.exe") -ArgumentList @("mcp") -RedirectStandardInput $McpIn -RedirectStandardOutput $McpOut -Wait -PassThru -WindowStyle Hidden
    $Reply = if (Test-Path $McpOut) { Get-Content -Raw -Encoding UTF8 $McpOut } else { "" }
    if (($Reply -notmatch '"protocolVersion"') -or ($Reply -notmatch 'studio_view_preview')) { throw "mcp smoke failed (exit $($m.ExitCode)): $Reply" }
    Write-Host "  mcp ok: initialize + tools/list"
    Remove-Item Env:MXS_HOME, Env:MXS_WORKSPACE
}
Step "done: $App"
