param(
    [string]$TaskName = "PicoCommonServer"
)

$ErrorActionPreference = "Stop"

# 자동 실행 등록만 제거합니다. 서버 설정 파일이나 Pico 연결 설정은 건드리지 않습니다.
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "삭제 완료: $TaskName"
} else {
    Write-Host "등록된 작업 스케줄러 항목이 없습니다: $TaskName"
}

$startupPath = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupPath "$TaskName.lnk"
if (Test-Path $shortcutPath) {
    Remove-Item -LiteralPath $shortcutPath -Force
    Write-Host "시작프로그램 바로가기 삭제 완료: $shortcutPath"
}
