@echo off
setlocal
title Remove Python completely
net session >nul 2>&1
if errorlevel 1 (
  echo This needs administrator permission. Click Yes on the next window.
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
echo.
echo  This removes EVERY Python 3 from this PC, including the leftover records that cause the
echo  "already installed" error, and Fathom's Python environment (the venv).
echo  Your own files, your Fathom data and the Fathom folder on GitHub are NOT touched.
echo.
choice /m "Remove Python now"
if errorlevel 2 exit /b
powershell -NoProfile -ExecutionPolicy Bypass -Command "$t = Get-Content -Raw -LiteralPath '%~f0'; $i = $t.IndexOf('#PSSTART'); Invoke-Expression $t.Substring($i)"
echo.
pause
exit /b
#PSSTART
$ErrorActionPreference = 'SilentlyContinue'
function Say($m) { Write-Host ('  ' + $m) }

Say 'Closing Python and Fathom...'
Get-Process | Where-Object { $_.ProcessName -match '^(python|pythonw|py|pyw)$' } | Stop-Process -Force
Start-Sleep 2

# 1. Remove a folder or a junction safely. A junction is unlinked first, then what it pointed to is deleted.
function Kill-Dir([string]$p) {
  if (-not (Test-Path -LiteralPath $p)) { return }
  $it = Get-Item -LiteralPath $p -Force
  $target = $null
  if ($it.Attributes -band [IO.FileAttributes]::ReparsePoint) {
    $target = $it.Target; if ($target -is [array]) { $target = $target[0] }
    [IO.Directory]::Delete($p)                      # removes only the link
    if ($target -and ($target -match 'Python') -and (Test-Path -LiteralPath $target)) { Remove-Item -LiteralPath $target -Recurse -Force }
  } else { Remove-Item -LiteralPath $p -Recurse -Force }
  Say ('Removed ' + $p)
}

# 2. Run the real uninstallers first
Say 'Running the Python uninstallers...'
$roots = @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall', 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall', 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall')
$found = @()
foreach ($r in $roots) {
  Get-ChildItem $r | ForEach-Object {
    $p = Get-ItemProperty $_.PSPath
    if ($p.DisplayName -match '^Python\s*3' -or $p.DisplayName -match '^Python Launcher') { $found += [pscustomobject]@{ Key = $_.PSPath; Name = $p.DisplayName; Cmd = $p.UninstallString; Quiet = $p.QuietUninstallString } }
  }
}
foreach ($f in $found) {
  Say ('Uninstalling: ' + $f.Name)
  try {
    if ($f.Cmd -match '\{[0-9A-Fa-f-]{36}\}') { $g = $Matches[0]; Start-Process msiexec.exe -ArgumentList ('/x ' + $g + ' /qn /norestart') -Wait -WindowStyle Hidden }
    elseif ($f.Cmd -match '^"?([^"]+\.exe)"?') { $exe = $Matches[1]; if (Test-Path -LiteralPath $exe) { Start-Process -FilePath $exe -ArgumentList '/uninstall /quiet' -Wait -WindowStyle Hidden } }
  } catch {}
}

# 3. Folders
Say 'Deleting Python folders...'
foreach ($d in (Get-ChildItem 'C:\Program Files' -Directory -Force | Where-Object { $_.Name -match '^Python3' })) { Kill-Dir $d.FullName }
foreach ($d in (Get-ChildItem 'C:\Program Files (x86)' -Directory -Force | Where-Object { $_.Name -match '^Python3' })) { Kill-Dir $d.FullName }
Kill-Dir (Join-Path $env:LOCALAPPDATA 'Programs\Python')
Kill-Dir 'C:\Program Files\Python Launcher'
foreach ($d in (Get-ChildItem 'C:\' -Directory -Force | Where-Object { $_.Name -match '^Python3' })) { Kill-Dir $d.FullName }
Remove-Item 'C:\Windows\py.exe', 'C:\Windows\pyw.exe', 'C:\Windows\pyshellext.amd64.dll' -Force
Kill-Dir (Join-Path $env:LOCALAPPDATA 'Fathom\venv')
Kill-Dir (Join-Path $env:LOCALAPPDATA 'Python')
Kill-Dir (Join-Path $env:LOCALAPPDATA 'pip')
Kill-Dir (Join-Path $env:APPDATA 'Python')

# 4. Leftover records (these cause "already installed" when the files are gone)
Say 'Clearing leftover install records...'
foreach ($f in $found) { Remove-Item -LiteralPath $f.Key -Recurse -Force }
foreach ($k in 'HKLM:\SOFTWARE\Python', 'HKLM:\SOFTWARE\WOW6432Node\Python', 'HKCU:\SOFTWARE\Python') { Remove-Item -LiteralPath $k -Recurse -Force }
foreach ($k in 'Python.File', 'Python.CompiledFile', 'Python.NoConFile', 'Python.Extension') { Remove-Item -LiteralPath ('HKLM:\SOFTWARE\Classes\' + $k) -Recurse -Force; Remove-Item -LiteralPath ('HKCU:\SOFTWARE\Classes\' + $k) -Recurse -Force }
# Windows Installer product and dependency records for Python
Get-ChildItem 'HKLM:\SOFTWARE\Classes\Installer\Products' | ForEach-Object { $n = (Get-ItemProperty $_.PSPath).ProductName; if ($n -match '^Python\s*3|^Python Launcher') { Remove-Item -LiteralPath $_.PSPath -Recurse -Force } }
Get-ChildItem 'HKLM:\SOFTWARE\Classes\Installer\Features' | ForEach-Object { }
Get-ChildItem 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Installer\UserData' -Recurse -Depth 3 | ForEach-Object { $n = (Get-ItemProperty $_.PSPath).DisplayName; if ($n -match '^Python\s*3|^Python Launcher') { Remove-Item -LiteralPath $_.PSPath -Recurse -Force } }
Get-ChildItem 'HKLM:\SOFTWARE\Classes\Installer\Dependencies' | ForEach-Object { $n = (Get-ItemProperty $_.PSPath).DisplayName; if ($n -match 'Python') { Remove-Item -LiteralPath $_.PSPath -Recurse -Force } }
Get-ChildItem 'HKCU:\SOFTWARE\Classes\Installer\Dependencies' | ForEach-Object { $n = (Get-ItemProperty $_.PSPath).DisplayName; if ($n -match 'Python') { Remove-Item -LiteralPath $_.PSPath -Recurse -Force } }
# the installer's cached copy (this is what makes it think Python is still there)
if (Test-Path 'C:\ProgramData\Package Cache') {
  Get-ChildItem 'C:\ProgramData\Package Cache' -Directory | ForEach-Object { if (Get-ChildItem -LiteralPath $_.FullName -Filter 'python-3*.exe' -File) { Remove-Item -LiteralPath $_.FullName -Recurse -Force; Say ('Removed cache ' + $_.Name) } }
}
$pc = Join-Path $env:LOCALAPPDATA 'Package Cache'
if (Test-Path $pc) { Get-ChildItem $pc -Directory | ForEach-Object { if (Get-ChildItem -LiteralPath $_.FullName -Filter 'python-3*.exe' -File) { Remove-Item -LiteralPath $_.FullName -Recurse -Force } } }

# 5. PATH: take out every Python entry
Say 'Cleaning PATH...'
foreach ($scope in 'User', 'Machine') {
  $old = [Environment]::GetEnvironmentVariable('Path', $scope)
  if ($old) {
    $new = ($old -split ';' | Where-Object { $_ -and ($_ -notmatch '\\Python3\d*(\\Scripts)?\\?$') -and ($_ -notmatch 'Python\\Launcher') }) -join ';'
    if ($new -ne $old) { [Environment]::SetEnvironmentVariable('Path', $new, $scope) }
  }
}

# 6. Temp copies of the installer
Get-ChildItem $env:TEMP -Filter 'python-3*.exe' -File | Remove-Item -Force
Get-ChildItem $env:TEMP -Directory | Where-Object { $_.Name -match '^Python 3' } | Remove-Item -Recurse -Force

Write-Host ''
Write-Host '  Done. Python is removed. Restart the PC, then run Fathom-Setup.exe again.' -ForegroundColor Green
