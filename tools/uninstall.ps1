# Removes Fathom from this PC. Asks before each part. Called by Uninstall-Fathom.cmd (as administrator).
param([string]$AppDir = '')
$ErrorActionPreference = 'Continue'
function Say([string]$m) { Write-Host $m }
function Ask([string]$q) { $a = Read-Host ($q + ' (Y/N)'); return ($a -match '^\s*(y|yes)\s*$') }
function Is-Link([string]$p) {
  if (-not (Test-Path -LiteralPath $p)) { return $false }
  return [bool]((Get-Item -LiteralPath $p -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)
}
# Removes a folder. If it is only a link, the link is removed, and the folder it points to only when Fathom created it (listed in places.txt).
# the folders Fathom made while installing (written down by the installer: link|real folder); only these are ever removed from other places
$ownedTargets = @()
$placesFile = Join-Path (Join-Path $env:LOCALAPPDATA 'Fathom') 'places.txt'
if (Test-Path -LiteralPath $placesFile) { foreach ($ln in (Get-Content -LiteralPath $placesFile -ErrorAction SilentlyContinue)) { $parts = $ln.Split('|'); if ($parts.Count -ge 2 -and $parts[1]) { $ownedTargets += $parts[1].Trim() } } }
function Remove-Place([string]$p, [string]$label, [switch]$Owned) {
  if (-not (Test-Path -LiteralPath $p)) { Say "  $label : not there."; return }
  if (Is-Link $p) {
    $t = (Get-Item -LiteralPath $p -Force).Target
    if ($t -is [array]) { $t = $t[0] }
    & cmd.exe /c rmdir "$p" | Out-Null          # removes only the link
    if ($t -and ($Owned -or ($ownedTargets -contains $t)) -and (Test-Path -LiteralPath $t)) { Remove-Item -LiteralPath $t -Recurse -Force -ErrorAction SilentlyContinue }
    elseif ($t -and (Test-Path -LiteralPath $t)) { Say "  $label : the link was removed; the folder it pointed to ($t) was left alone because Fathom did not create it." }
  }
  else { Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue }
  if (Test-Path -LiteralPath $p) { Say "  $label : could not be removed completely (something is still using it). Restart the PC and delete: $p" }
  else { Say "  $label : removed." }
}

if ($AppDir) { try { $AppDir = [IO.Path]::GetFullPath($AppDir) } catch {} }
$data = Join-Path $env:LOCALAPPDATA 'Fathom'
Say ''
Say 'This removes Fathom from this PC. Your own files are never touched.'
Say ''
$wipeData = Ask 'Delete Fathom''s data too (settings, chat history, saved results, its Python packages and downloaded models)?'
$wipeProgs = Ask 'Also remove the programs Fathom installed (LibreOffice, Calibre, 7-Zip, Ollama and its AI model)? Say N if you use them for other things.'
Say ''

# 1. stop Fathom and the programs
Say '[1/5] Closing Fathom...'
Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -and ($_.CommandLine -like '*launch.py*' -or $_.CommandLine -like '*app.main:app*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
if ($wipeProgs) { foreach ($p in 'soffice', 'soffice.bin', 'ollama', 'ollama app', 'ollama_llama_server', '7zFM', 'calibre') { Get-Process -Name $p -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue } }
Start-Sleep -Seconds 2

# 2. shortcuts
Say '[2/5] Removing the shortcuts...'
$desk = [Environment]::GetFolderPath('Desktop'); $prog = [Environment]::GetFolderPath('Programs')
foreach ($k in '*', 'Directory') { try { [Microsoft.Win32.Registry]::CurrentUser.DeleteSubKeyTree('Software\Classes\' + $k + '\shell\Fathom', $false) } catch {} }
foreach ($l in @((Join-Path $desk 'Fathom.lnk'), (Join-Path $prog 'Fathom.lnk'), (Join-Path $data 'Fathom.lnk'))) {
  if (Test-Path -LiteralPath $l) { Remove-Item -LiteralPath $l -Force -ErrorAction SilentlyContinue }
}
Say '  done.'

# 3. data
Say '[3/5] Fathom''s data...'
if ($wipeData) { Remove-Place $data 'Fathom data' -Owned } else { Say ('  kept (your settings and history stay in ' + $data + ').') }

# 4. programs
Say '[4/5] Programs Fathom installed...'
if ($wipeProgs) {
  foreach ($id in 'TheDocumentFoundation.LibreOffice', 'calibre.calibre', '7zip.7zip', 'Ollama.Ollama') {
    if (Get-Command winget -ErrorAction SilentlyContinue) { & winget uninstall -e --id $id --silent --accept-source-agreements 2>&1 | Out-Null }
  }
  $pf = $env:ProgramFiles
  Remove-Place (Join-Path $pf 'LibreOffice') 'LibreOffice'
  Remove-Place (Join-Path $pf 'Calibre2') 'Calibre'
  Remove-Place (Join-Path $pf '7-Zip') '7-Zip'
  try { Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'Ollama (Fathom)' -ErrorAction SilentlyContinue } catch {}
  Remove-Place (Join-Path $env:LOCALAPPDATA 'Programs\Ollama') 'Ollama'
  Remove-Place (Join-Path $env:USERPROFILE '.ollama') 'Ollama AI model'
  $om = [Environment]::GetEnvironmentVariable('OLLAMA_MODELS', 'User')
  if ($om -and (($om -like '*\Ollama Models\models') -or ($ownedTargets -contains (Split-Path -Parent $om)))) {
    Remove-Place (Split-Path -Parent $om) 'Ollama AI model (in the folder you chose)'
    [Environment]::SetEnvironmentVariable('OLLAMA_MODELS', $null, 'User')
    Say '  OLLAMA_MODELS setting removed.'
  }
  # Python is left alone: other programs may use it. Only the empty link Fathom made for it is removed.
  $py = Join-Path $pf 'Python312'
  if ((Is-Link $py) -and -not (Test-Path -LiteralPath (Join-Path $py 'python.exe'))) { & cmd.exe /c rmdir "$py" | Out-Null; Say '  empty Python link removed.' }
  else { Say '  Python 3.12 was left in place (remove it in Settings > Apps if nothing else needs it).' }
}
else { Say '  kept.' }

# 5. the app folder
Say '[5/5] The Fathom app folder...'
$log = Join-Path $env:TEMP 'Fathom-move.log'
if (Test-Path -LiteralPath $log) { Remove-Item -LiteralPath $log -Force -ErrorAction SilentlyContinue }
$ok = $AppDir -and (Test-Path -LiteralPath (Join-Path $AppDir 'launch.py')) -and (Test-Path -LiteralPath (Join-Path $AppDir 'app\main.py'))
if ($ok) {
  $cmd = Join-Path $env:TEMP 'fathom_uninstall_cleanup.cmd'
  Set-Content -LiteralPath $cmd -Encoding ASCII -Value @('@echo off', 'ping -n 6 127.0.0.1 >nul', ('rmdir /s /q "' + $AppDir + '"'), 'del /f /q "%~f0"')
  Start-Process -FilePath 'cmd.exe' -ArgumentList ('/c "' + $cmd + '"') -WindowStyle Hidden
  Say ('  ' + $AppDir + ' will be deleted a few seconds after you close this window.')
}
else { Say '  (could not recognise the app folder; delete it yourself.)' }
Say ''
Say 'Fathom is removed. Your own files were not touched.'
