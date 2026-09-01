$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $PSScriptRoot '.venv'
$Python = Join-Path $Venv 'Scripts\python.exe'

Write-Host 'Quant Scanner - Windows Companion Installer'
Write-Host ''

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw 'Python launcher (py) was not found. Install Python 3.11+ from python.org, then run this installer again.'
}

if (-not (Test-Path $Python)) {
    py -3 -m venv $Venv
}

& $Python -m pip install --upgrade pip
& $Python -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')

$Launcher = Join-Path $PSScriptRoot 'run_desktop_agent.cmd'
$Startup = [Environment]::GetFolderPath('Startup')
$ShortcutPath = Join-Path $Startup 'Quant Scanner.lnk'
$Target = $Launcher
$Wsh = New-Object -ComObject WScript.Shell
$Shortcut = $Wsh.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $Target
$Shortcut.WorkingDirectory = $PSScriptRoot
$Shortcut.WindowStyle = 7
$Shortcut.Description = 'Quant Scanner Windows desktop alert companion'
$Shortcut.Save()

Write-Host ''
Write-Host 'Installed.' -ForegroundColor Green
Write-Host "Startup shortcut: $ShortcutPath"
Write-Host 'The companion will run quietly after the next Windows login.'
Write-Host 'To start it now, run desktop\run_desktop_agent.cmd.'
