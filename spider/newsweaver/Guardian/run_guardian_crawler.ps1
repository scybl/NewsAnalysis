# Guardian Crawler Scheduled Task Script
# Runs at 00:00, 06:00, 12:00, 18:00 daily

# Set UTF-8 encoding to handle international characters
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

# Set working directory to script location
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# Output start message
$CurrentTime = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Guardian Crawler Task Started - $CurrentTime" -ForegroundColor Green
Write-Host "Working Directory: $ScriptDir" -ForegroundColor Green
Write-Host "Current Location: $(Get-Location)" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green

# Check if Python is available
try {
    $PythonVersion = python --version 2>&1
    Write-Host "Python Version: $PythonVersion" -ForegroundColor Yellow
} catch {
    Write-Host "ERROR: Python not found" -ForegroundColor Red
    exit 1
}

# Check if Guardian.py exists
if (-not (Test-Path "Guardian.py")) {
    Write-Host "ERROR: Guardian.py not found" -ForegroundColor Red
    exit 1
}

# Check if config file exists
if (-not (Test-Path "guardian_config.env")) {
    Write-Host "WARNING: guardian_config.env not found" -ForegroundColor Yellow
} else {
    Write-Host "Config file: guardian_config.env" -ForegroundColor Green
}

# Run Guardian crawler
Write-Host "Running Guardian crawler..." -ForegroundColor Cyan
try {
    # Set UTF-8 encoding for Python output
    $env:PYTHONIOENCODING = "utf-8"
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    
    # Run Python script and capture output
    $Output = python Guardian.py 2>&1
    $ExitCode = $LASTEXITCODE
    
    # Output result
    Write-Host $Output
    
    if ($ExitCode -eq 0) {
        Write-Host "============================================================" -ForegroundColor Green
        Write-Host "Guardian Crawler Task Completed - $CurrentTime" -ForegroundColor Green
        Write-Host "============================================================" -ForegroundColor Green
    } else {
        Write-Host "============================================================" -ForegroundColor Red
        Write-Host "Guardian Crawler Task Failed - Exit Code: $ExitCode" -ForegroundColor Red
        Write-Host "============================================================" -ForegroundColor Red
    }
} catch {
    Write-Host "ERROR: Exception occurred while running Guardian crawler" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}

# Keep window open for 5 seconds to view result
Start-Sleep -Seconds 5
