param(
    [string]$TaskName = "PicoCommonServer"
)

$ErrorActionPreference = "Stop"

# 이 스크립트는 현재 사용자 로그온 시 Pico 공통 서버 트레이 앱을 자동 실행하도록 등록합니다.
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$distExe = Join-Path $projectRoot "dist\PicoCommonServer.exe"
$venvPythonw = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"
$trayMain = Join-Path $projectRoot "tray_main.py"

if (Test-Path $distExe) {
    $execute = $distExe
    $arguments = ""
} elseif ((Test-Path $venvPythonw) -and (Test-Path $trayMain)) {
    $execute = $venvPythonw
    $arguments = "`"$trayMain`""
} else {
    throw "실행 대상을 찾지 못했습니다. dist\PicoCommonServer.exe 또는 .venv\Scripts\pythonw.exe + tray_main.py가 필요합니다."
}

if ([string]::IsNullOrWhiteSpace($arguments)) {
    $action = New-ScheduledTaskAction -Execute $execute -WorkingDirectory $projectRoot
} else {
    $action = New-ScheduledTaskAction -Execute $execute -Argument $arguments -WorkingDirectory $projectRoot
}
$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew

try {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "Windows 로그온 시 Pico 공통 서버를 자동 실행합니다." -Force | Out-Null
    Write-Host "작업 스케줄러 등록 완료: $TaskName -> $execute $arguments"
} catch {
    # 작업 스케줄러 등록이 권한 문제로 막히면 현재 사용자 시작프로그램 바로가기로 대체합니다.
    $startupPath = [Environment]::GetFolderPath("Startup")
    $shortcutPath = Join-Path $startupPath "$TaskName.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $execute
    $shortcut.Arguments = $arguments
    $shortcut.WorkingDirectory = $projectRoot
    $shortcut.WindowStyle = 7
    $shortcut.Description = "Windows 로그온 시 Pico 공통 서버를 자동 실행합니다."
    $shortcut.Save()
    Write-Host "시작프로그램 바로가기 등록 완료: $shortcutPath -> $execute $arguments"
}
