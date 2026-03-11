<#
.SYNOPSIS
    Avvia la Currency Strength Dashboard.
    Installa automaticamente Python, crea il virtual environment e le dipendenze
    se non sono già presenti.

.USAGE
    Fare doppio clic su  avvia.bat  oppure da PowerShell:
        .\setup_and_run.ps1
#>

$ErrorActionPreference = "Continue"
$ProjectDir = $PSScriptRoot
if (-not $ProjectDir) { $ProjectDir = (Get-Location).Path }

try {

Set-Location $ProjectDir

Write-Host ""
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host "   Currency Strength Indicator  -  Setup & Launch    " -ForegroundColor Cyan
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host ""

# ─────────────────────────────────────────────────────────────
# 1.  VERIFICA / INSTALLA PYTHON
# ─────────────────────────────────────────────────────────────

function Find-Python {
    # Cerca un vero python (non l'alias WindowsApps)
    $candidates = @(
        "$ProjectDir\.venv\Scripts\python.exe"
        (Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue)
        (Get-Command python3 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue)
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"
        "C:\Python312\python.exe"
        "C:\Python311\python.exe"
        "C:\Python313\python.exe"
    )

    foreach ($p in $candidates) {
        if ($p -and (Test-Path $p) -and ($p -notmatch "WindowsApps")) {
            # Verifica che funzioni davvero
            try {
                $ver = & $p --version 2>&1
                if ($ver -match "Python 3") {
                    return $p
                }
            } catch {}
        }
    }
    return $null
}

$PythonExe = Find-Python

if (-not $PythonExe) {
    Write-Host "[1/5] Python non trovato. Installazione via winget..." -ForegroundColor Yellow
    Write-Host "      (potrebbe richiedere conferma amministratore)" -ForegroundColor DarkGray
    Write-Host ""

    winget install Python.Python.3.12 --accept-package-agreements --accept-source-agreements

    # Aggiorna PATH nella sessione corrente
    $newPaths = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312",
        "$env:LOCALAPPDATA\Programs\Python\Python312\Scripts"
    )
    foreach ($np in $newPaths) {
        if ($env:Path -notmatch [regex]::Escape($np)) {
            $env:Path = "$np;$env:Path"
        }
    }

    $PythonExe = Find-Python
    if (-not $PythonExe) {
        Write-Host ""
        Write-Host "ERRORE: Installazione Python completata ma non trovato nel PATH." -ForegroundColor Red
        Write-Host "Chiudi e riapri PowerShell, poi rilancia questo script." -ForegroundColor Red
        Read-Host "Premi INVIO per chiudere"
        exit 1
    }

    Write-Host "[OK] Python installato: $PythonExe" -ForegroundColor Green
} else {
    $pyVer = & $PythonExe --version 2>&1
    Write-Host "[1/5] Python trovato: $pyVer ($PythonExe)" -ForegroundColor Green
}

# ─────────────────────────────────────────────────────────────
# 2.  CREA VIRTUAL ENVIRONMENT
# ─────────────────────────────────────────────────────────────

$VenvDir = Join-Path $ProjectDir ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvPip = Join-Path $VenvDir "Scripts\pip.exe"
$VenvStreamlit = Join-Path $VenvDir "Scripts\streamlit.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "[2/5] Creazione virtual environment (.venv)..." -ForegroundColor Yellow
    & $PythonExe -m venv $VenvDir
    if (-not (Test-Path $VenvPython)) {
        Write-Host "ERRORE: Impossibile creare il virtual environment." -ForegroundColor Red
        Read-Host "Premi INVIO per chiudere"
        exit 1
    }
    Write-Host "[OK] Virtual environment creato in .venv\" -ForegroundColor Green
} else {
    Write-Host "[2/5] Virtual environment gia' esistente." -ForegroundColor Green
}

# ─────────────────────────────────────────────────────────────
# 3.  INSTALLA / AGGIORNA DIPENDENZE
# ─────────────────────────────────────────────────────────────

$ReqFile = Join-Path $ProjectDir "requirements.txt"
$MarkerFile = Join-Path $VenvDir ".deps_installed"

# Rinstalla se il file requirements.txt e' piu' recente del marker
$needInstall = (-not (Test-Path $MarkerFile))
if ((Test-Path $MarkerFile) -and (Test-Path $ReqFile)) {
    $reqDate = (Get-Item $ReqFile).LastWriteTime
    $markDate = (Get-Item $MarkerFile).LastWriteTime
    if ($reqDate -gt $markDate) { $needInstall = $true }
}

if ($needInstall) {
    Write-Host "[3/5] Installazione dipendenze (prima volta, puo' richiedere qualche minuto)..." -ForegroundColor Yellow
    & $VenvPython -m pip install --upgrade pip 2>&1 | Out-Null
    & $VenvPython -m pip install -r $ReqFile
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERRORE: Installazione dipendenze fallita." -ForegroundColor Red
        Read-Host "Premi INVIO per chiudere"
        exit 1
    }
    New-Item -Path $MarkerFile -ItemType File -Force | Out-Null
    Write-Host "[OK] Dipendenze installate." -ForegroundColor Green
} else {
    Write-Host "[3/5] Dipendenze gia' installate (skip)." -ForegroundColor Green
}

# ─────────────────────────────────────────────────────────────
# 4.  CREA CARTELLA CACHE
# ─────────────────────────────────────────────────────────────

$CacheDir = Join-Path $ProjectDir "cache"
if (-not (Test-Path $CacheDir)) {
    New-Item -ItemType Directory -Path $CacheDir -Force | Out-Null
}
Write-Host "[4/5] Cartella cache pronta." -ForegroundColor Green

# ─────────────────────────────────────────────────────────────
# 5.  AVVIO DASHBOARD
# ─────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "[5/5] Avvio Currency Strength Dashboard..." -ForegroundColor Cyan
Write-Host ""
Write-Host "  La dashboard si aprira' nel browser." -ForegroundColor White
Write-Host "  Per fermarla: premi Ctrl+C in questa finestra." -ForegroundColor DarkGray
Write-Host "  URL: http://localhost:8501" -ForegroundColor White
Write-Host ""
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host ""

# Avvia lo scheduler in background (alert orari anche senza browser)
$SchedulerScript = Join-Path $ProjectDir "scheduler.py"
if (Test-Path $SchedulerScript) {
    Write-Host "  [BG] Avvio scheduler orario in background..." -ForegroundColor DarkCyan
    $global:SchedulerJob = Start-Process -FilePath $VenvPython -ArgumentList $SchedulerScript `
        -WindowStyle Hidden -PassThru -WorkingDirectory $ProjectDir
    Write-Host "  [OK] Scheduler PID: $($global:SchedulerJob.Id)" -ForegroundColor Green
    Write-Host ""
}

try {
    & $VenvStreamlit run (Join-Path $ProjectDir "app.py") --server.headless true --browser.gatherUsageStats false
} finally {
    # Ferma lo scheduler quando la dashboard viene chiusa
    if ($global:SchedulerJob -and -not $global:SchedulerJob.HasExited) {
        Write-Host "" 
        Write-Host "  Arresto scheduler..." -ForegroundColor Yellow
        Stop-Process -Id $global:SchedulerJob.Id -Force -ErrorAction SilentlyContinue
        Write-Host "  [OK] Scheduler fermato." -ForegroundColor Green
    }
}

} catch {
    Write-Host ""
    Write-Host "===== ERRORE ====="  -ForegroundColor Red
    Write-Host $_.Exception.Message    -ForegroundColor Red
    Write-Host $_.ScriptStackTrace      -ForegroundColor DarkGray
    Write-Host ""
    Read-Host "Premi INVIO per chiudere"
    exit 1
}
