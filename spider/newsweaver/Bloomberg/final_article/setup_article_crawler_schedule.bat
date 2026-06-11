@echo off
chcp 65001 >nul
echo ========================================
echo   Bloomberg 文章爬虫定时任务设置
echo   (隐藏窗口模式)
echo ========================================
echo.

REM 获取当前用户
set "TASK_USER=%USERNAME%"
echo 当前用户: %TASK_USER%
echo.

REM 获取脚本所在目录的绝对路径
set "SCRIPT_DIR=%~dp0"
set "PS_SCRIPT=%SCRIPT_DIR%run_ultimate_crawler.ps1"

echo PowerShell脚本路径: %PS_SCRIPT%
echo.

REM 检查PowerShell脚本是否存在
if not exist "%PS_SCRIPT%" (
    echo [错误] 找不到PowerShell脚本: %PS_SCRIPT%
    pause
    exit /b 1
)

echo ----------------------------------------
echo 开始创建定时任务...
echo ----------------------------------------
echo.

REM 删除已存在的任务（如果有）
echo 正在删除旧任务（如果存在）...
for /L %%i in (0,1,12) do (
    schtasks /delete /tn "Bloomberg_Article_Crawler_%%i" /f >nul 2>&1
)
echo.

REM 创建13个定时任务（08:10 到 20:10，每小时一次，隐藏窗口模式）
setlocal enabledelayedexpansion
set TASK_NUM=0
for /L %%H in (8,1,20) do (
    set "HOUR=%%H"
    
    REM 格式化小时为两位数
    if %%H LSS 10 set "HOUR=0%%H"
    
    echo [!TASK_NUM!] 创建任务: Bloomberg_Article_Crawler_!TASK_NUM! - 每天 !HOUR!:10 运行
    
    REM 创建隐藏窗口的定时任务
    schtasks /create /tn "Bloomberg_Article_Crawler_!TASK_NUM!" /tr "powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -File \"!PS_SCRIPT!\"" /sc daily /st !HOUR!:10 /ru "!TASK_USER!" /rl highest /f >nul
    
    if !ERRORLEVEL! EQU 0 (
        echo     成功
    ) else (
        echo     失败
    )
    
    set /a TASK_NUM+=1
)
endlocal

echo.
echo ========================================
echo   定时任务创建完成！
echo ========================================
echo.
echo 已创建 13 个定时任务（隐藏窗口模式）:
echo   - 任务名称: Bloomberg_Article_Crawler_0 到 Bloomberg_Article_Crawler_12
echo   - 运行时间: 每天 08:10, 09:10, 10:10, ..., 20:10（每小时一次）
echo   - 随机延迟: 0-10分钟
echo   - 窗口模式: 隐藏（不显示在前台）
echo.
echo 查看任务状态:
schtasks /query /fo table | findstr Bloomberg_Article_Crawler
echo.
pause

