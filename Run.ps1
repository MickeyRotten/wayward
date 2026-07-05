# Wayward Alpha - setup & launcher
# Installs everything required (Node, Python deps, npm deps), starts the
# backend (FastAPI/uvicorn) and frontend (Vite) each in their own window,
# then opens the browser at the app URL.
#
# -Remote    : also bind the frontend to every network interface (0.0.0.0) so
#              other devices on your LAN can connect at http://<this-pc-ip>:5173.
#              Launched via Run-Remote.bat.
# -Tailscale : same 0.0.0.0 binding, but reachable from anywhere on your
#              Tailscale tailnet (not just the local LAN). Prints your tailnet
#              IP + MagicDNS name to connect with. Launched via Run-Tailscale.bat.
#
# In every case the backend stays local-only; the browser reaches it through
# Vite's /api proxy, so nothing extra is exposed and CORS is never involved.
param(
    [switch]$Remote,
    [switch]$Tailscale
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Set-Location $root

$NODE_VERSION = 'v24.17.0'      # pinned portable Node LTS
$BACKEND_PORT = 8000
$FRONTEND_PORT = 5173           # must match Vite proxy + server CORS
$APP_URL = "http://localhost:$FRONTEND_PORT"

function Info($m){ Write-Host "[wayward] $m" -ForegroundColor Cyan }
function Step($m){ Write-Host "[setup]   $m" -ForegroundColor Yellow }
function Ok($m){   Write-Host "[ok]      $m" -ForegroundColor Green }

try {
    $banner = @'
 __      __                                         .___
/  \    /  \_____  ___.__.__  _  _______ _______  __| _/
\   \/\/   /\__  \<   |  |\ \/ \/ /\__  \\_  __ \/ __ |
 \        /  / __ \\___  | \     /  / __ \|  | \/ /_/ |
  \__/\  /  (____  / ____|  \/\_/  (____  /__|  \____ |
       \/        \/\/                   \/           \/

'@
    Write-Host $banner -ForegroundColor Yellow
    Write-Host "  Alpha - setup & launch" -ForegroundColor DarkGray

    # ---------------------------------------------------------------
    # 1. Node.js (portable install under %LOCALAPPDATA%\nodejs)
    # ---------------------------------------------------------------
    $nodeDir = Join-Path $env:LOCALAPPDATA 'nodejs'
    if (Test-Path (Join-Path $nodeDir 'node.exe')) {
        $env:Path = "$nodeDir;$env:Path"
    }
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        Step "Node.js not found - downloading portable $NODE_VERSION ..."
        $zip = "node-$NODE_VERSION-win-x64.zip"
        $tmp = Join-Path $env:TEMP $zip
        $pp = $ProgressPreference; $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest "https://nodejs.org/dist/$NODE_VERSION/$zip" -OutFile $tmp
        $ProgressPreference = $pp
        if (Test-Path $nodeDir) { Remove-Item $nodeDir -Recurse -Force }
        Expand-Archive $tmp $env:LOCALAPPDATA -Force
        Rename-Item (Join-Path $env:LOCALAPPDATA "node-$NODE_VERSION-win-x64") $nodeDir
        Remove-Item $tmp -Force
        $env:Path = "$nodeDir;$env:Path"
        # persist for future shells
        $userPath = [Environment]::GetEnvironmentVariable('Path','User')
        if ($userPath -notlike "*$nodeDir*") {
            [Environment]::SetEnvironmentVariable('Path', "$nodeDir;$userPath", 'User')
        }
    }
    Ok "Node $(node --version) / npm $(npm --version)"

    # ---------------------------------------------------------------
    # 2. Python interpreter
    # ---------------------------------------------------------------
    $py = $null
    foreach ($c in 'py','python') {
        if (Get-Command $c -ErrorAction SilentlyContinue) { $py = $c; break }
    }
    if (-not $py) {
        Write-Host "[error] Python 3.11+ not found on PATH." -ForegroundColor Red
        Write-Host "        Install it from https://www.python.org/downloads/ (check 'Add to PATH'), then re-run." -ForegroundColor Red
        Read-Host 'Press Enter to exit'; exit 1
    }
    Ok "Python via '$py'"

    # ---------------------------------------------------------------
    # 3. Backend venv + Python dependencies
    # ---------------------------------------------------------------
    $venv   = Join-Path $root 'server\.venv'
    $venvPy = Join-Path $venv 'Scripts\python.exe'
    if (-not (Test-Path $venvPy)) {
        Step "Creating Python virtual environment (server\.venv) ..."
        & $py -m venv $venv
    }
    Step "Installing Python dependencies ..."
    & $venvPy -m pip install --upgrade pip --quiet
    & $venvPy -m pip install -r (Join-Path $root 'server\requirements.txt') --quiet
    Ok "Backend dependencies ready"

    # ---------------------------------------------------------------
    # 4. Frontend dependencies
    # ---------------------------------------------------------------
    $clientDir = Join-Path $root 'client'
    if (-not (Test-Path (Join-Path $clientDir 'node_modules'))) {
        Step "Installing client dependencies (npm install) ..."
        Push-Location $clientDir
        npm install --no-fund --no-audit
        Pop-Location
    }
    Ok "Frontend dependencies ready"

    # ---------------------------------------------------------------
    # 5. Launch both servers in THIS window (no extra console windows).
    #    -NoNewWindow shares this console, so their logs interleave here
    #    and closing this one window stops both.
    # ---------------------------------------------------------------
    Info "Starting backend  -> http://127.0.0.1:$BACKEND_PORT"
    $backend = Start-Process -FilePath $venvPy -WorkingDirectory $root -NoNewWindow -PassThru `
        -ArgumentList '-m', 'uvicorn', 'server.main:app', '--port', "$BACKEND_PORT"

    Info "Starting frontend -> $APP_URL"
    $viteArgs = @('run', 'dev', '--', '--port', "$FRONTEND_PORT", '--strictPort')
    if ($Remote -or $Tailscale) { $viteArgs += @('--host', '0.0.0.0') }
    $frontend = Start-Process -FilePath 'npm.cmd' -WorkingDirectory $clientDir -NoNewWindow -PassThru `
        -ArgumentList $viteArgs

    # ---------------------------------------------------------------
    # 6. Wait for the frontend to respond, then open the browser
    # ---------------------------------------------------------------
    Info "Waiting for the app to come up ..."
    $up = $false
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Milliseconds 500
        try {
            Invoke-WebRequest $APP_URL -UseBasicParsing -TimeoutSec 2 | Out-Null
            Invoke-WebRequest "http://127.0.0.1:$BACKEND_PORT/health" -UseBasicParsing -TimeoutSec 2 | Out-Null
            $up = $true; break
        } catch {}
    }
    if ($up) { Ok "App is live" } else { Write-Host "[warn] Frontend slow to start; opening browser anyway." -ForegroundColor Yellow }
    Start-Process $APP_URL

    Write-Host ""
    Info "Wayward is running at $APP_URL  (backend + frontend log below)"
    if ($Tailscale) {
        # Resolve the Tailscale CLI (PATH, or the default Windows install path).
        $ts = (Get-Command tailscale -ErrorAction SilentlyContinue).Source
        if (-not $ts) {
            $tsDefault = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'
            if (Test-Path $tsDefault) { $ts = $tsDefault }
        }
        Write-Host ""
        if (-not $ts) {
            Write-Host "  Tailscale not found. Install it from https://tailscale.com/download and" -ForegroundColor Yellow
            Write-Host "  sign in, then re-run. The app is still bound to all interfaces, so any" -ForegroundColor Yellow
            Write-Host "  tailnet IP will work once Tailscale is up." -ForegroundColor Yellow
        } else {
            $tsIp   = (& $ts ip -4 2>$null | Select-Object -First 1)
            $tsName = $null
            try {
                $status = & $ts status --json 2>$null | ConvertFrom-Json
                if ($status.Self.DNSName) { $tsName = $status.Self.DNSName.TrimEnd('.') }
            } catch {}
            if ($tsIp -or $tsName) {
                Write-Host "  Tailscale access is ON. From any device on your tailnet, open:" -ForegroundColor Green
                if ($tsName) { Write-Host "      http://${tsName}:$FRONTEND_PORT" -ForegroundColor Cyan }
                if ($tsIp)   { Write-Host "      http://${tsIp}:$FRONTEND_PORT" -ForegroundColor Cyan }
                Write-Host "  Both devices must be signed in to the same tailnet." -ForegroundColor DarkGray
            } else {
                Write-Host "  Tailscale is installed but not connected. Run 'tailscale up' and sign in," -ForegroundColor Yellow
                Write-Host "  then reconnect at http://<your-tailscale-ip>:$FRONTEND_PORT." -ForegroundColor Yellow
            }
        }
        Write-Host "  If it won't connect, allow Node.js through Windows Firewall when prompted." -ForegroundColor DarkGray
    }
    elseif ($Remote) {
        # Show every non-loopback IPv4 address so the user knows what to hand out.
        $ips = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
            Select-Object -ExpandProperty IPAddress)
        Write-Host ""
        Write-Host "  Remote access is ON. On another device on the same network, open:" -ForegroundColor Green
        if ($ips.Count -gt 0) {
            foreach ($ip in $ips) { Write-Host "      http://${ip}:$FRONTEND_PORT" -ForegroundColor Cyan }
        } else {
            Write-Host "      http://<this-pc-ip>:$FRONTEND_PORT   (couldn't auto-detect your IP)" -ForegroundColor Cyan
        }
        Write-Host "  If it won't connect, allow Node.js through Windows Firewall (Private networks)" -ForegroundColor DarkGray
        Write-Host "  when prompted, and make sure the other device is on the same Wi-Fi/LAN." -ForegroundColor DarkGray
    }
    Info "Close this window to stop both servers."
    Write-Host ""

    # Keep this single window alive while the servers run; closing it stops both.
    try {
        Wait-Process -Id $backend.Id, $frontend.Id
    } finally {
        Stop-Process -Id $backend.Id, $frontend.Id -Force -ErrorAction SilentlyContinue
    }
}
catch {
    Write-Host ""
    Write-Host "[error] Setup/launch failed: $($_.Exception.Message)" -ForegroundColor Red
    Read-Host 'Press Enter to exit'
    exit 1
}
