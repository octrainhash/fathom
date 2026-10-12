# Updates THIS Fathom from a newer Fathom zip. Writes Fathom-update.txt in Downloads. Nothing is deleted.
# Looks in Downloads for fathom-final.zip, then fathom.zip. Copies the new program files over the ones in this Fathom folder (your settings,
# chat history, data and the install choices are not touched), then starts Fathom.bat, which finishes the update by itself.
. (Join-Path $PSScriptRoot '_common.ps1')
Start-Report 'Fathom-update'
$zip = $null
foreach ($n in 'fathom-final.zip', 'fathom.zip') { $c = Join-Path $Downloads $n; if (Test-Path -LiteralPath $c) { $zip = $c; break } }
if (-not $zip) { L 'No fathom-final.zip or fathom.zip is in your Downloads folder. Download the new zip there and run this again.'; Finish-Report; exit }
L ('New zip: ' + $zip)
L ('This Fathom: ' + $AppDir + '   version ' + (Get-AppVersion))
$work = Join-Path $env:TEMP ('fathom-update-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $work -Force | Out-Null
Add-Type -AssemblyName System.IO.Compression.FileSystem
try { [IO.Compression.ZipFile]::ExtractToDirectory($zip, $work) } catch { L ('Could not open the zip: ' + $_.Exception.Message); Finish-Report; exit }
$new = $null
foreach ($d in @($work) + @(Get-ChildItem -LiteralPath $work -Directory -Recurse -Depth 2 -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })) {
  if ((Test-Path -LiteralPath (Join-Path $d 'Fathom.bat')) -and (Test-Path -LiteralPath (Join-Path $d 'app\paths.py'))) { $new = $d; break }
}
if (-not $new) { L 'That zip does not contain a Fathom folder.'; Finish-Report; exit }
$nv = (Select-String -LiteralPath (Join-Path $new 'app\paths.py') -Pattern '^VERSION\s*=\s*"([^"]+)"' | Select-Object -First 1).Matches[0].Groups[1].Value
L ('Version in the zip: ' + $nv)
if ($new -ieq $AppDir) { L 'The zip is already this folder.'; Finish-Report; exit }
# close Fathom so no file is locked
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -and ($_.CommandLine -like '*launch.py*' -or $_.CommandLine -like '*app.main:app*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2
L 'Copying the new files over this Fathom (settings and data are not touched) ...'
& robocopy.exe $new $AppDir /E /XF install-choice.txt LITE /XD __pycache__ /R:2 /W:2 /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { L ('The copy did not finish (robocopy code ' + $LASTEXITCODE + '). Nothing else was changed.'); Finish-Report; exit }
L ('Done. This Fathom is now version ' + (Get-AppVersion) + '. Starting Fathom.bat to finish the update (Windows will ask for permission) ...')
Start-Process -FilePath (Join-Path $AppDir 'Fathom.bat') -WorkingDirectory $AppDir
L ('You can delete the temporary folder later: ' + $work)
Finish-Report
