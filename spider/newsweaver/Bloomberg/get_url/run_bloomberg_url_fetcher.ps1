# Bloomberg URL Fetcher Scheduled Task Script
# Runs hourly with 2-10 minutes random delay

# 静默运行，不显示窗口
$Host.UI.RawUI.WindowTitle = "Bloomberg URL Fetcher (Background)"

# Set UTF-8 encoding to handle international characters
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

# Random delay 2-10 minutes
$DelaySeconds = Get-Random -Minimum 120 -Maximum 600
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Bloomberg URL Fetcher Task Starting" -ForegroundColor Green
Write-Host "Random delay: $DelaySeconds seconds ($([math]::Round($DelaySeconds/60, 1)) minutes)" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Green

if ($DelaySeconds -gt 0) {
    Write-Host "Waiting..." -ForegroundColor Yellow
    Start-Sleep -Seconds $DelaySeconds
}

# Set working directory to script location
# Use PSScriptRoot which is more reliable in scheduled tasks
if ($PSScriptRoot) {
    $ScriptDir = $PSScriptRoot
} else {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}

# Fallback to hardcoded path if both fail
if (-not $ScriptDir -or -not (Test-Path $ScriptDir)) {
    $ScriptDir = "C:\Users\Administrator\Desktop\Bloomberg\get_url"
}

Set-Location $ScriptDir

# Output start message
$CurrentTime = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Bloomberg URL Fetcher Started - $CurrentTime" -ForegroundColor Green
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

# Check if bloomberg_url_fetcher.py exists
if (-not (Test-Path "bloomberg_url_fetcher.py")) {
    Write-Host "ERROR: bloomberg_url_fetcher.py not found" -ForegroundColor Red
    exit 1
}

# Check if .env file exists
if (-not (Test-Path ".env")) {
    Write-Host "WARNING: .env not found" -ForegroundColor Yellow
} else {
    Write-Host "Config file: .env" -ForegroundColor Green
}

# Run Bloomberg URL fetcher
Write-Host "Running Bloomberg URL fetcher..." -ForegroundColor Cyan
try {
    # Set UTF-8 encoding for Python output
    $env:PYTHONIOENCODING = "utf-8"
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    
    # Run Python script and capture output
    $Output = python bloomberg_url_fetcher.py 2>&1
    $ExitCode = $LASTEXITCODE
    
    # Output result
    Write-Host $Output
    
    if ($ExitCode -eq 0) {
        Write-Host "============================================================" -ForegroundColor Green
        Write-Host "Bloomberg URL Fetcher Task Completed - $CurrentTime" -ForegroundColor Green
        Write-Host "============================================================" -ForegroundColor Green
    } else {
        Write-Host "============================================================" -ForegroundColor Red
        Write-Host "Bloomberg URL Fetcher Task Failed - Exit Code: $ExitCode" -ForegroundColor Red
        Write-Host "============================================================" -ForegroundColor Red
    }
} catch {
    Write-Host "ERROR: Exception occurred while running Bloomberg URL fetcher" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}

# Keep window open for 3 seconds to view result
Start-Sleep -Seconds 3

