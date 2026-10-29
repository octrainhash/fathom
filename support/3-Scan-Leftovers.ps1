# Lists every copy of Fathom, its data, its links and old leftovers on this PC (read-only: it only looks). Writes Fathom-scan.txt in Downloads.
. (Join-Path $PSScriptRoot '_common.ps1')
Start-Report 'Fathom-scan'
function Info([string]$p) {
  $i = Get-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue
  if (-not $i) { L ('  ' + $p + '  : missing'); return }
  if ($i.LinkType) { L ('  ' + $p + '  LINK -> ' + ($i.Target | Select-Object -First 1)); return }
  if ($i.PSIsContainer) {
    $n = (Get-ChildItem -LiteralPath $p -Recurse -Force -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum)
    L ('  {0}  folder, {1:N2} GB' -f $p, ($n.Sum / 1GB))
  } else { L ('  {0}  file, {1:N1} MB' -f $p, ($i.Length / 1MB)) }
}
L '== This script lives in'; L ('  ' + $AppDir)
L '== Fathom data'; Info $DataDir
if (Test-Path -LiteralPath (Join-Path $DataDir 'places.txt')) { L '  places Fathom made:'; Get-Content -LiteralPath (Join-Path $DataDir 'places.txt') | ForEach-Object { L ('    ' + $_) } }
L '== Ollama'; Info (Join-Path $env:USERPROFILE '.ollama'); Info (Join-Path $env:USERPROFILE '.ollama.junction-old'); Info (Join-Path $env:LOCALAPPDATA 'Programs\Ollama')
L ('  OLLAMA_MODELS = ' + [Environment]::GetEnvironmentVariable('OLLAMA_MODELS', 'User'))
L '== Windows folders Fathom may have linked'
foreach ($n in 'Python312', 'LibreOffice', 'Calibre2', '7-Zip') { Info (Join-Path $env:ProgramFiles $n); Info ((Join-Path $env:ProgramFiles $n) + '.moved') }
L '== Copies of Fathom.bat (where Fathom is installed or unpacked), up to 4 folders deep'
foreach ($d in [IO.DriveInfo]::GetDrives()) {
  if ($d.DriveType -eq 'Fixed' -and $d.IsReady) {
    Get-ChildItem -LiteralPath $d.Name -Recurse -Depth 4 -Force -Filter 'Fathom.bat' -ErrorAction SilentlyContinue | ForEach-Object { L ('  ' + $_.FullName + '   ' + $_.LastWriteTime.ToString('yyyy-MM-dd HH:mm')) }
  }
}
L '== Fathom files in Downloads'
Get-ChildItem -LiteralPath $Downloads -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -match 'fathom' } | ForEach-Object { L ('  ' + $_.Name + '   ' + $_.LastWriteTime.ToString('yyyy-MM-dd HH:mm')) }
L '== Shortcuts'
foreach ($p in @((Join-Path ([Environment]::GetFolderPath('Desktop')) 'Fathom.lnk'), (Join-Path ([Environment]::GetFolderPath('Programs')) 'Fathom.lnk'), (Join-Path $DataDir 'Fathom.lnk'))) {
  if (Test-Path -LiteralPath $p) {
    try { $sc = (New-Object -ComObject WScript.Shell).CreateShortcut($p); L ('  ' + $p + '  -> ' + $sc.TargetPath + ' ' + $sc.Arguments) } catch { L ('  ' + $p) }
  } else { L ('  ' + $p + '  : none') }
}
L ''
L 'Nothing was changed. To remove Fathom completely, use Fathom-Setup.vbs > Problems and Fixes > Remove Fathom.'
Finish-Report
