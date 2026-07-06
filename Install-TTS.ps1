# Wayward - one-time voice / text-to-speech installer.
#
# Installs the optional TTS stack (chatterbox-tts + torch/torchaudio, a multi-GB
# download) into the SAME backend venv Run.bat uses (server\.venv), auto-detects
# an NVIDIA GPU to pick the CUDA vs CPU torch build, and pre-downloads the voice
# model so the first line spoken in-app isn't a multi-minute wait.
#
# Double-click Install-TTS.bat to run this. Safe to re-run - it skips the heavy
# install when the stack is already present. The base app (Run.bat) never needs
# this; it's purely for enabling voice.

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Set-Location $root

# PyTorch CUDA wheel index. The wheels bundle their own CUDA runtime, so the
# host only needs a recent NVIDIA driver (no CUDA toolkit install). cu124 suits
# modern torch (2.4+); if chatterbox pins an older torch this can be adjusted.
$CUDA_INDEX = 'https://download.pytorch.org/whl/cu124'

function Info($m){ Write-Host "[wayward] $m" -ForegroundColor Cyan }
function Step($m){ Write-Host "[setup]   $m" -ForegroundColor Yellow }
function Ok($m){   Write-Host "[ok]      $m" -ForegroundColor Green }

try {
    Write-Host ""
    Write-Host "  Wayward - Voice / Text-to-Speech installer" -ForegroundColor Yellow
    Write-Host "  This is a large (multi-GB) one-time download." -ForegroundColor DarkGray
    Write-Host ""

    # ---------------------------------------------------------------
    # 1. Python interpreter (same probe as Run.ps1)
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
    # 2. Backend venv (reuse Run.bat's server\.venv so the server sees the deps)
    # ---------------------------------------------------------------
    $venv   = Join-Path $root 'server\.venv'
    $venvPy = Join-Path $venv 'Scripts\python.exe'
    if (-not (Test-Path $venvPy)) {
        Step "Creating Python virtual environment (server\.venv) ..."
        & $py -m venv $venv
    }
    & $venvPy -m pip install --upgrade pip --quiet
    Ok "Backend venv ready"

    # ---------------------------------------------------------------
    # 3. Install the TTS stack (skip if already present)
    # ---------------------------------------------------------------
    & $venvPy -c "import chatterbox" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Ok "Voice support already installed - skipping download"
    } else {
        Step "Installing voice support (chatterbox-tts + torch) - this can take a while ..."
        & $venvPy -m pip install -r (Join-Path $root 'server\requirements-tts.txt')
        if ($LASTEXITCODE -ne 0) { throw "pip install of chatterbox-tts failed" }
        Ok "Voice packages installed"

        # -----------------------------------------------------------
        # 4. NVIDIA GPU? Swap the CPU torch build for the matched CUDA build.
        # -----------------------------------------------------------
        $hasNvidia = $false
        if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
            $hasNvidia = $true
        } else {
            try {
                $gpu = Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue |
                    Where-Object { $_.Name -match 'NVIDIA' }
                if ($gpu) { $hasNvidia = $true }
            } catch {}
        }

        if ($hasNvidia) {
            $tv = (& $venvPy -c "import torch;print(torch.__version__.split('+')[0])").Trim()
            Step "NVIDIA GPU detected - installing CUDA torch $tv (GPU acceleration) ..."
            & $venvPy -m pip install --upgrade "torch==$tv" "torchaudio==$tv" --index-url $CUDA_INDEX
            if ($LASTEXITCODE -ne 0) {
                Write-Host "[warn] CUDA torch install failed; keeping the CPU build (voice still works, just slower)." -ForegroundColor Yellow
            } else {
                Ok "CUDA torch installed"
            }
        } else {
            Info "No NVIDIA GPU detected - using the CPU build (voice works, but synthesis is slow)."
        }
    }

    # ---------------------------------------------------------------
    # 5. Pre-warm the model (forces the Hugging Face download into cache now)
    # ---------------------------------------------------------------
    Step "Downloading / loading the voice model (first run only) ..."
    $statusJson = & $venvPy -c "import json; from server.ai import tts; print(json.dumps(tts.preload()))"
    $device = 'cpu'; $err = $null
    try {
        $st = $statusJson | ConvertFrom-Json
        if ($st.device) { $device = $st.device }
        if ($st.error)  { $err = $st.error }
    } catch {}

    Write-Host ""
    if ($err) {
        Write-Host "[warn] The model could not be loaded: $err" -ForegroundColor Yellow
        Write-Host "       The packages are installed; the app will retry loading when you enable voice." -ForegroundColor Yellow
    } else {
        Ok "Voice model ready (running on: $device)"
    }

    Write-Host ""
    Info "Voice support is installed. Next:"
    Write-Host "    1. Start the app with Run.bat" -ForegroundColor Cyan
    Write-Host "    2. Open Config -> Voice & Audio -> tick 'Enable text-to-speech'" -ForegroundColor Cyan
    Write-Host "    3. (Optional) Upload ~10s voice samples on character sheets to clone voices" -ForegroundColor Cyan
    Write-Host ""
    Read-Host 'Press Enter to close'
}
catch {
    Write-Host ""
    Write-Host "[error] Voice install failed: $($_.Exception.Message)" -ForegroundColor Red
    Read-Host 'Press Enter to exit'
    exit 1
}
