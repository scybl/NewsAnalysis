# Bloomberg Ultimate Crawler Scheduled Task Script
# Runs at :10 of each hour from 8:10 to 20:10 (13 times daily) with 0-10 minutes random delay

# Set UTF-8 encoding to handle international characters
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

# Random delay 0-10 minutes
$DelaySeconds = Get-Random -Minimum 0 -Maximum 600
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Bloomberg Ultimate Crawler Task Starting" -ForegroundColor Green
Write-Host "Random delay: $DelaySeconds seconds ($([math]::Round($DelaySeconds/60, 1)) minutes)" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Green

if ($DelaySeconds -gt 0) {
    Write-Host "Waiting..." -ForegroundColor Yellow
    Start-Sleep -Seconds $DelaySeconds
}

# Set working directory to script location
if ($PSScriptRoot) {
    $ScriptDir = $PSScriptRoot
} else {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}

# Fallback to hardcoded path if both fail
if (-not $ScriptDir -or -not (Test-Path $ScriptDir)) {
    $ScriptDir = "C:\Users\Administrator\Desktop\Bloomberg\final_article"
}

Set-Location $ScriptDir

# Output start message
$CurrentTime = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Bloomberg Ultimate Crawler Started - $CurrentTime" -ForegroundColor Green
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

# Check if ultimate_crawler.py exists
if (-not (Test-Path "ultimate_crawler.py")) {
    Write-Host "ERROR: ultimate_crawler.py not found" -ForegroundColor Red
    exit 1
}

# Run Bloomberg ultimate crawler
Write-Host "Running Bloomberg ultimate crawler..." -ForegroundColor Cyan
try {
    # Set UTF-8 encoding for Python output
    $env:PYTHONIOENCODING = "utf-8"
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    
    # Run Python script and capture output
    $Output = python ultimate_crawler.py 2>&1
    $ExitCode = $LASTEXITCODE
    
    # Output result
    Write-Host $Output
    
    if ($ExitCode -eq 0) {
        Write-Host "============================================================" -ForegroundColor Green
        Write-Host "Bloomberg Ultimate Crawler Task Completed - $CurrentTime" -ForegroundColor Green
        Write-Host "============================================================" -ForegroundColor Green
    } else {
        Write-Host "============================================================" -ForegroundColor Red
        Write-Host "Bloomberg Ultimate Crawler Task Failed - Exit Code: $ExitCode" -ForegroundColor Red
        Write-Host "============================================================" -ForegroundColor Red
    }
} catch {
    Write-Host "ERROR: Exception occurred while running Bloomberg ultimate crawler" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}

# Keep window open for 3 seconds to view result
Start-Sleep -Seconds 3







