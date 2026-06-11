@echo off
chcp 65001 >nul
echo ============================================================
echo Guardian爬虫定时任务设置（修复版）
echo ============================================================
echo.

REM 获取当前脚本所在目录
set "SCRIPT_DIR=%~dp0"
set "PS_SCRIPT=%SCRIPT_DIR%run_guardian_crawler.ps1"

echo 脚本目录: %SCRIPT_DIR%
echo PowerShell脚本: %PS_SCRIPT%
echo.

REM 检查PowerShell脚本是否存在
if not exist "%PS_SCRIPT%" (
    echo 错误: 未找到PowerShell脚本文件
    echo 请确保 run_guardian_crawler.ps1 文件存在
    pause
    exit /b 1
)

echo 正在设置定时任务...
echo.

REM 删除可能存在的旧任务
echo 清理旧任务...
schtasks /delete /tn "Guardian_Crawler_00" /f >nul 2>&1
schtasks /delete /tn "Guardian_Crawler_06" /f >nul 2>&1
schtasks /delete /tn "Guardian_Crawler_12" /f >nul 2>&1
schtasks /delete /tn "Guardian_Crawler_18" /f >nul 2>&1

REM 获取当前用户名
for /f "tokens=*" %%u in ('whoami') do set "CURRENT_USER=%%u"
echo 使用用户: %CURRENT_USER%
echo.

REM 创建定时任务 - 0点（改用当前用户，添加工作目录）
echo 创建定时任务: Guardian_Crawler_00 (00:00)
schtasks /create /tn "Guardian_Crawler_00" /tr "powershell.exe -ExecutionPolicy Bypass -NoProfile -File \"%PS_SCRIPT%\"" /sc daily /st 00:00 /ru "%CURRENT_USER%" /rl highest /f

REM 创建定时任务 - 6点
echo 创建定时任务: Guardian_Crawler_06 (06:00)
schtasks /create /tn "Guardian_Crawler_06" /tr "powershell.exe -ExecutionPolicy Bypass -NoProfile -File \"%PS_SCRIPT%\"" /sc daily /st 06:00 /ru "%CURRENT_USER%" /rl highest /f

REM 创建定时任务 - 12点
echo 创建定时任务: Guardian_Crawler_12 (12:00)
schtasks /create /tn "Guardian_Crawler_12" /tr "powershell.exe -ExecutionPolicy Bypass -NoProfile -File \"%PS_SCRIPT%\"" /sc daily /st 12:00 /ru "%CURRENT_USER%" /rl highest /f

REM 创建定时任务 - 18点
echo 创建定时任务: Guardian_Crawler_18 (18:00)
schtasks /create /tn "Guardian_Crawler_18" /tr "powershell.exe -ExecutionPolicy Bypass -NoProfile -File \"%PS_SCRIPT%\"" /sc daily /st 18:00 /ru "%CURRENT_USER%" /rl highest /f

echo.
echo ============================================================
echo 定时任务设置完成！
echo.
echo 任务列表:
echo - Guardian_Crawler_00 (每天 00:00)
echo - Guardian_Crawler_06 (每天 06:00)
echo - Guardian_Crawler_12 (每天 12:00)
echo - Guardian_Crawler_18 (每天 18:00)
echo.
echo 运行用户: %CURRENT_USER%
echo 日志位置: %SCRIPT_DIR%logs\
echo.
echo ============================================================
echo 立即测试运行
echo ============================================================
echo.
choice /c YN /m "是否立即测试运行6点的任务"
if errorlevel 2 goto skip_test
if errorlevel 1 goto run_test

:run_test
echo.
echo 正在运行测试...
schtasks /run /tn "Guardian_Crawler_06"
echo.
echo 等待5秒...
timeout /t 5 /nobreak >nul
echo.
echo 查看任务状态:
schtasks /query /tn "Guardian_Crawler_06" /fo list /v | findstr /C:"Last Run" /C:"Last Result"
echo.
echo 检查日志文件:
if exist "%SCRIPT_DIR%logs\" (
    echo 最新Guardian日志:
    dir /b /od "%SCRIPT_DIR%logs\guardian_crawler_*.log" 2>nul | findstr /r ".*" >nul && dir /b /od "%SCRIPT_DIR%logs\guardian_crawler_*.log" | find /n /v "" | find "[1]"
) else (
    echo logs目录尚未创建
)
echo.
goto end

:skip_test
echo 跳过测试运行
echo.

:end
echo ============================================================
echo 完成！
echo.
echo 可以通过以下命令查看任务状态:
echo schtasks /query /tn "Guardian_Crawler_06" /fo list /v
echo.
echo 可以通过以下命令手动测试:
echo schtasks /run /tn "Guardian_Crawler_06"
echo.
echo 查看日志:
echo - Guardian爬虫日志: %SCRIPT_DIR%logs\
echo.
echo ============================================================
pause

