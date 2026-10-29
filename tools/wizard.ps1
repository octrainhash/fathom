# Fathom setup wizard: a window with pages (Welcome, Where, Programs, Shortcuts, Summary, Installing, Finished).
# You choose what to install and exactly where every part goes. Nothing is decided for you except the suggested folders.
# Started by Fathom-Setup.vbs (double-click, it only runs this file) or by "Fathom.bat setup". Needs only Windows PowerShell (built into Windows 10 and 11, including Tiny11).
# $AppDir may be set by the starter before this runs; otherwise it is the folder above this file.
if (-not $AppDir) { $AppDir = Split-Path -Parent $PSScriptRoot }
$AppDir = [IO.Path]::GetFullPath($AppDir)
$Version = '1.0.0'
try {
  $vm = Select-String -LiteralPath (Join-Path $AppDir 'app\paths.py') -Pattern '^VERSION\s*=\s*"([^"]+)"' | Select-Object -First 1
  if ($vm) { $Version = $vm.Matches[0].Groups[1].Value }
} catch {}
$DataHome = Join-Path $env:LOCALAPPDATA 'Fathom'
# stand somewhere harmless, so the old folder can be tidied away after the move
try { Set-Location -LiteralPath $env:TEMP; [Environment]::CurrentDirectory = $env:TEMP } catch {}

# ----------------------------------------------------------------------------------------------- helpers
function Get-FreeGB([string]$path) {
  try {
    $root = [IO.Path]::GetPathRoot([IO.Path]::GetFullPath($path))
    $d = New-Object IO.DriveInfo($root)
    if (-not $d.IsReady) { return -1 }
    return [math]::Round($d.AvailableFreeSpace / 1GB, 1)
  } catch { return -1 }
}
function Get-DriveKey([string]$path) {
  try { return ([IO.Path]::GetPathRoot([IO.Path]::GetFullPath($path))).Substring(0, 2).ToUpper() } catch { return '' }
}
function Get-BestDrive {
  $best = $null; $bestFree = -1
  foreach ($d in [IO.DriveInfo]::GetDrives()) {
    if ($d.DriveType -eq 'Fixed' -and $d.IsReady -and $d.AvailableFreeSpace -gt $bestFree) { $best = $d.Name; $bestFree = $d.AvailableFreeSpace }
  }
  if (-not $best) { $best = $env:SystemDrive + '\' }
  return $best
}
function Clean-Path([string]$p) {
  $p = $p.Trim().Trim('"').Trim()
  if ($p.Length -gt 3) { $p = $p.TrimEnd('\') }
  return $p
}
function Test-Folder([string]$p, [string]$what) {
  # returns '' when fine, otherwise the problem in plain words
  if (-not $p) { return "Please choose a folder for $what." }
  if (-not [IO.Path]::IsPathRooted($p) -or $p.StartsWith('\\')) { return "Please type a full folder path for $what, such as E:\Fathom, or choose one with Browse." }
  if ($p.Length -le 3) { return "Please choose a folder inside the drive for $what, not the whole drive (for example $($p.Substring(0,2))\Fathom)." }
  if ((Get-FreeGB $p) -lt 0) { return "The drive for $what does not exist or is not ready. Please choose another folder." }
  if ($p.IndexOfAny([IO.Path]::GetInvalidPathChars()) -ge 0 -or $p.IndexOf('|') -ge 0 -or $p.IndexOf('%') -ge 0 -or $p.IndexOf('^') -ge 0 -or $p.IndexOf('&') -ge 0 -or $p.IndexOf('!') -ge 0) { return "The folder for $what has a character that cannot be used here (one of  | % ^ & !). Please choose another folder." }
  return ''
}

# the parts Fathom can use. GB = about how much room each needs once installed.
$Parts = @(
  @{ Key = 'python';      Title = 'Python 3.12';      Desc = 'Runs Fathom (always installed).';                                                Folder = 'Python312';      GB = 0.2;  Required = $true },
  @{ Key = 'libreoffice'; Title = 'LibreOffice';      Desc = 'Open and convert Word, Excel, PowerPoint and old Office files, and open them as pages in the Visual editor (download about 350 MB).'; Folder = 'LibreOffice'; GB = 1.6 },
  @{ Key = 'calibre';     Title = 'Calibre';          Desc = 'Convert e-books such as EPUB, MOBI and AZW (download about 200 MB).';             Folder = 'Calibre2';       GB = 1.0 },
  @{ Key = '7zip';        Title = '7-Zip';            Desc = 'Open RAR, 7z and other archives (small).';                                       Folder = '7-Zip';          GB = 0.05 },
  @{ Key = 'ollama';      Title = 'Ollama';           Desc = 'The program that runs the free AI assistant on your own PC. No key, no account.'; Folder = 'Ollama';        GB = 1.2 },
  @{ Key = 'models';      Title = 'AI assistant model'; Desc = 'The assistant''s brain, a free vision model, plus the small model for Search by meaning (download about 3.6 GB, once).';     Folder = 'Ollama Models';  GB = 3.6 }
)


# ----------------------------------------------------------------------------------------------- fixes and tools
# Each entry becomes a small .bat file the user can run. They find the installed Fathom by themselves (app-dir.txt), so they work from anywhere.
function Q([string]$name) { return ('call :need "support\' + $name + '"' + "`r`n" + 'call "%APP%\support\' + $name + '"') }
$Fixes = @(
  @{ Id = 'repair'; Title = 'Fathom will not start, or something is missing (repair everything)'; Kw = 'repair start open crash blank missing broken error fix not working wont'; Desc = 'Runs the Fathom setup again: reinstalls whatever is missing or damaged (Python packages, models, programs). Your settings and files are kept.'; Body = 'call :need "Fathom.bat"' + "`r`n" + 'call "%APP%\Fathom.bat" repair' },
  @{ Id = 'update'; Title = 'Update Fathom to the newest version (and install anything missing)'; Kw = 'update upgrade newest latest version old'; Desc = 'Downloads the newest Fathom, copies it over yours (data untouched) and installs anything missing.'; Body = 'call :need "tools\Install-or-Update-Fathom.bat"' + "`r`n" + 'call "%APP%\tools\Install-or-Update-Fathom.bat" "%APP%"' },
  @{ Id = 'everything'; Title = 'Download every model now (so nothing downloads later)'; Kw = 'download model speech whisper wait downloading preinstall offline slow handwriting faces object'; Desc = 'Downloads all speech models, object search, faces and the handwriting reader now.'; Body = 'call :need "support\15-Get-Everything-Now.bat"' + "`r`n" + 'call "%APP%\support\15-Get-Everything-Now.bat"' },
  @{ Id = 'check'; Title = 'Check everything and write a report'; Kw = 'check test status diagnose report health'; Desc = 'Reads the state of Fathom and Ollama and saves a report in Downloads.'; Body = (Q '1-Check-Everything.cmd') },
  @{ Id = 'ollama'; Title = 'The assistant says "model not found" / Ollama problems'; Kw = 'ollama assistant model not found chat ai llm'; Desc = 'Repairs the free AI assistant: points Ollama at the right models folder and tests it.'; Body = (Q '2-Fix-Ollama.cmd') },
  @{ Id = 'diagollama'; Title = 'Diagnose Ollama in detail'; Kw = 'ollama diagnose detail why'; Desc = 'Shows exactly what is wrong with Ollama.'; Body = (Q '7-Diagnose-Ollama.cmd') },
  @{ Id = 'fastmodel'; Title = 'Assistant is slow: download the small fast model'; Kw = 'slow fast assistant small model speed lag'; Desc = 'Downloads a smaller, quicker assistant model.'; Body = (Q '5-Download-Fast-Model.cmd') },
  @{ Id = 'speed'; Title = 'Speed test for the assistant'; Kw = 'speed slow test benchmark performance'; Desc = 'Measures how fast the assistant answers on this PC.'; Body = (Q '6-Speed-Test.cmd') },
  @{ Id = 'voice'; Title = 'Microphone / voice (Talk button) does not work'; Kw = 'voice microphone mic talk speak audio hear'; Desc = 'Tests the microphone and the speech model.'; Body = (Q '10-Test-Voice.cmd') },
  @{ Id = 'leftovers'; Title = 'Scan for leftover Fathom files'; Kw = 'leftover scan old files clean junk'; Desc = 'Lists leftover Fathom folders from older installs. Deletes nothing.'; Body = (Q '3-Scan-Leftovers.cmd') },
  @{ Id = 'zipupdate'; Title = 'Update from a newer Fathom zip in Downloads'; Kw = 'zip update downloads offline'; Desc = 'Updates this Fathom from a zip you downloaded.'; Body = (Q '4-Update-From-Zip.cmd') },
  @{ Id = 'logs'; Title = 'Open the logs and data folder'; Kw = 'log logs folder data open send'; Desc = 'Opens the folder with Fathom''s logs, so you can send them to someone.'; Body = 'start "" explorer.exe "%LOCALAPPDATA%\Fathom"' },
  @{ Id = 'move'; Title = 'Move all of Fathom to another folder or drive'; Kw = 'move drive disk space full c d folder relocate'; Desc = 'Moves the app, its data and the programs into the folder you type. Checks the copy before deleting anything.'; Body = 'call :need "tools\Move-Fathom.cmd"' + "`r`n" + 'call "%APP%\tools\Move-Fathom.cmd"' },
  @{ Id = 'uninstall'; Title = 'Remove Fathom from this PC (uninstall)'; Kw = 'uninstall remove delete erase'; Desc = 'Asks before each part: data and models, then the programs (LibreOffice, Calibre, 7-Zip, Ollama). Your own files are never touched.'; Body = 'call :need "tools\Uninstall-Fathom.cmd"' + "`r`n" + 'call "%APP%\tools\Uninstall-Fathom.cmd"' },
  @{ Id = 'zip'; Title = 'Install 7-Zip (RAR / 7z archives)'; Kw = '7zip 7-zip rar archive missing install'; Desc = 'Installs 7-Zip with winget.'; Body = 'winget install -e --id 7zip.7zip --accept-source-agreements --accept-package-agreements' },
  @{ Id = 'lo'; Title = 'Install LibreOffice (Word / Excel / PowerPoint)'; Kw = 'libreoffice office word excel powerpoint docx missing install'; Desc = 'Installs LibreOffice with winget.'; Body = 'winget install -e --id TheDocumentFoundation.LibreOffice --accept-source-agreements --accept-package-agreements' },
  @{ Id = 'calibre'; Title = 'Install Calibre (e-books)'; Kw = 'calibre ebook epub mobi azw missing install'; Desc = 'Installs Calibre with winget.'; Body = 'winget install -e --id calibre.calibre --accept-source-agreements --accept-package-agreements' },
  @{ Id = 'ollamainst'; Title = 'Install Ollama (the free assistant)'; Kw = 'ollama install missing assistant'; Desc = 'Installs Ollama with winget.'; Body = 'winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements' },
  @{ Id = 'ffmpeg'; Title = 'Use the graphics card for video (full FFmpeg)'; Kw = 'ffmpeg gpu nvidia graphics card encode video nvenc'; Desc = 'Installs a full FFmpeg so the NVIDIA option in Convert works.'; Body = 'call :need "tools\Get-FFmpeg-GPU.bat"' + "`r`n" + 'call "%APP%\tools\Get-FFmpeg-GPU.bat"' },
  @{ Id = 'serve'; Title = 'Start Fathom in server mode (use it from a phone, tablet or another PC)'; Kw = 'server mode phone tablet remote browser network serve link token'; Desc = 'Starts Fathom as a private web server and shows a link. Open the link on any device on your network. Keep the window open.'; Body = 'call :need "Fathom.bat"' + "`r`n" + 'call "%APP%\Fathom.bat" serve' },
  @{ Id = 'serveoff'; Title = 'Stop starting the server with Windows'; Kw = 'server startup windows remove auto start boot'; Desc = 'Removes the Fathom Server entry from Windows startup.'; Body = 'del /f /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Fathom Server.lnk"' },
  @{ Id = 'sendto'; Title = 'Add "Send to > Fathom" to the right-click menu'; Kw = 'send to right click menu context'; Desc = 'Right-click any file, Send to, Fathom.'; Body = (Q '11-Add-Send-To.cmd') },
  @{ Id = 'sendtooff'; Title = 'Remove "Send to > Fathom"'; Kw = 'send to remove right click menu'; Desc = 'Takes Fathom out of the Send to menu.'; Body = (Q '12-Remove-Send-To.cmd') },
  @{ Id = 'portable'; Title = 'Portable mode ON (settings travel with the folder)'; Kw = 'portable usb stick travel'; Desc = 'Keeps settings and history next to the app.'; Body = (Q '13-Portable-Mode-On.cmd') },
  @{ Id = 'portableoff'; Title = 'Portable mode OFF'; Kw = 'portable usb off'; Desc = 'Goes back to the normal data place.'; Body = (Q '14-Portable-Mode-Off.cmd') }
)

# ----------------------------------------------------------------------------------------------- look: dark and light
function Get-ThemeName {
  try {
    $f1 = Join-Path $env:APPDATA 'FathomSetup\theme.txt'
    if (Test-Path -LiteralPath $f1) { $v = (Get-Content -LiteralPath $f1 -ErrorAction Stop | Select-Object -First 1).Trim(); if ($v -eq 'dark' -or $v -eq 'light') { return $v } }
  } catch {}
  try { $r = Get-ItemPropertyValue -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize' -Name AppsUseLightTheme -ErrorAction Stop; if ($r -eq 0) { return 'dark' } } catch {}
  return 'light'
}
function Save-ThemeName([string]$n) {
  try { $d1 = Join-Path $env:APPDATA 'FathomSetup'; if (-not (Test-Path -LiteralPath $d1)) { New-Item -ItemType Directory -Path $d1 -Force | Out-Null }; Set-Content -LiteralPath (Join-Path $d1 'theme.txt') -Value $n -Encoding ASCII } catch {}
}
function Get-Theme([string]$name) {
  function C($h) { return [System.Drawing.ColorTranslator]::FromHtml($h) }
  if ($name -eq 'dark') {
    return @{ Name = 'dark'; Bg = (C '#1B1E24'); Head = (C '#14171C'); Input = (C '#2A2F39'); Btn = (C '#2F3541'); Border = (C '#3A404C'); Text = (C '#E8EAED'); Muted = (C '#9AA3AF'); Accent = (C '#FFC83D'); AccentText = (C '#1B1E24'); Ok = (C '#7FE0A0'); Bad = (C '#FF8A80') }
  }
  return @{ Name = 'light'; Bg = (C '#F4F5F7'); Head = (C '#FFFFFF'); Input = (C '#FFFFFF'); Btn = (C '#E9ECF1'); Border = (C '#D3D8E0'); Text = (C '#1F2328'); Muted = (C '#5F6670'); Accent = (C '#FFC83D'); AccentText = (C '#1B1E24'); Ok = (C '#0F7B3F'); Bad = (C '#B3261E') }
}
function Apply-Theme($ctl, $t, $pbg) {
  $bgHere = $pbg
  if (-not $bgHere) { $bgHere = $t.Bg }
  if ($ctl.Name -eq 'head') { $bgHere = $t.Head }
  if ($ctl -is [System.Windows.Forms.Form]) { $ctl.BackColor = $t.Bg; $ctl.ForeColor = $t.Text }
  elseif ($ctl -is [System.Windows.Forms.TextBox]) { $ctl.BackColor = $t.Input; $ctl.ForeColor = $t.Text; $ctl.BorderStyle = 'FixedSingle' }
  elseif ($ctl -is [System.Windows.Forms.ListBox]) { $ctl.BackColor = $t.Input; $ctl.ForeColor = $t.Text; $ctl.BorderStyle = 'FixedSingle' }
  elseif ($ctl -is [System.Windows.Forms.Button]) {
    $ctl.FlatStyle = 'Flat'; $ctl.FlatAppearance.BorderSize = 1; $ctl.Cursor = [System.Windows.Forms.Cursors]::Hand
    if ($ctl.Tag -eq 'primary') { $ctl.BackColor = $t.Accent; $ctl.ForeColor = $t.AccentText; $ctl.FlatAppearance.BorderColor = $t.Accent; $ctl.Font = New-Object System.Drawing.Font('Segoe UI Semibold', 9) }
    else { $ctl.BackColor = $t.Btn; $ctl.ForeColor = $t.Text; $ctl.FlatAppearance.BorderColor = $t.Border }
  }
  elseif ($ctl -is [System.Windows.Forms.Label]) {
    if ($ctl.BorderStyle -eq 'Fixed3D') { $ctl.BorderStyle = 'None'; $ctl.BackColor = $t.Border; $ctl.Height = 1 }
    else {
      if ($ctl.Tag -ne 'muted' -and $ctl.ForeColor.R -eq 96 -and $ctl.ForeColor.G -eq 96 -and $ctl.ForeColor.B -eq 96) { $ctl.Tag = 'muted' }
      if ($ctl.Tag -eq 'muted') { $ctl.ForeColor = $t.Muted } else { $ctl.ForeColor = $t.Text }
      $ctl.BackColor = $bgHere
    }
  }
  elseif ($ctl -is [System.Windows.Forms.CheckBox] -or $ctl -is [System.Windows.Forms.RadioButton]) { $ctl.BackColor = $bgHere; $ctl.ForeColor = $t.Text }
  elseif ($ctl -is [System.Windows.Forms.Panel]) { $ctl.BackColor = $bgHere }
  elseif ($ctl -is [System.Windows.Forms.PictureBox]) { $ctl.BackColor = $bgHere }
  foreach ($k in $ctl.Controls) { Apply-Theme $k $t $bgHere }
}
function Set-DarkTitleBar($form, [bool]$dark) {
  try {
    if (-not ('Fathom.FathomDwm' -as [type])) { Add-Type -Namespace Fathom -Name FathomDwm -MemberDefinition '[System.Runtime.InteropServices.DllImport("dwmapi.dll")] public static extern int DwmSetWindowAttribute(System.IntPtr h, int a, ref int v, int s);' -ErrorAction Stop }
    $v = 0; if ($dark) { $v = 1 }
    [void][Fathom.FathomDwm]::DwmSetWindowAttribute($form.Handle, 20, [ref]$v, 4)
  } catch {}
}

function New-FixBat([string]$title, [string]$body, [string]$problem) {
  $L = @()
  $L += '@echo off'
  $L += 'setlocal EnableExtensions'
  $L += ('title ' + ($title -replace '[&%^|<>"]', ''))
  $L += 'rem Made by the Fathom setup window. Open it in Notepad to read exactly what it does. It never deletes your own files.'
  if ($problem) { foreach ($ln in ($problem -split "`r?`n")) { $L += ('rem YOUR DESCRIPTION: ' + ($ln -replace '[\r\n]', ' ')) } }
  $L += 'set "APP="'
  $L += 'if exist "%LOCALAPPDATA%\Fathom\app-dir.txt" set /p APP=<"%LOCALAPPDATA%\Fathom\app-dir.txt"'
  $L += 'if defined APP set "APP=%APP:"=%"'
  $L += ('if not defined APP set "APP=' + $AppDir + '"')
  $L += 'if not exist "%APP%\Fathom.bat" set "APP=%~dp0"'
  $L += 'if not exist "%APP%\Fathom.bat" ('
  $L += '  echo Cannot find the Fathom folder. Put this file inside the Fathom folder and run it again.'
  $L += '  pause'
  $L += '  exit /b 1'
  $L += ')'
  $L += 'goto :go'
  $L += ':need'
  $L += 'if exist "%APP%\%~1" exit /b 0'
  $L += 'echo "%~1" was not found in "%APP%". Run the Fathom update (Install-or-Update-Fathom.bat) first.'
  $L += 'pause'
  $L += 'exit /b 1'
  $L += ':go'
  $L += 'echo.'
  $L += ('echo ' + ($title -replace '[&%^|<>"]', ''))
  $L += 'echo.'
  foreach ($ln in ($body -split "`r?`n")) { $L += $ln }
  $L += 'echo.'
  $L += 'echo Finished.'
  $L += 'pause'
  return ($L -join "`r`n")
}

# the "describe your problem" bat: fixes by keyword, or (when nothing matches) repairs, checks and bundles a report to send
function New-ProblemBat([string]$text) {
  $words = @($text.ToLower() -split '[^a-z0-9\-]+' | Where-Object { $_.Length -ge 3 })
  $scored = @()
  foreach ($fx in $Fixes) {
    $hay = ($fx.Title + ' ' + $fx.Kw).ToLower()
    $sc = 0; foreach ($w in $words) { if ($hay.Contains($w)) { $sc++ } }
    if ($sc -gt 0) { $scored += [pscustomobject]@{ Fix = $fx; Score = $sc } }
  }
  $top = @($scored | Sort-Object Score -Descending | Select-Object -First 3)
  $title = 'Fix for your problem'
  $body = @()
  if ($top.Count -gt 0) {
    $title = 'Fix: ' + $top[0].Fix.Title
    $body += 'echo This file tries the closest fixes for what you described, one after the other.'
    foreach ($t in $top) { $body += ('echo --- ' + ($t.Fix.Title -replace '[&%^|<>"]', '')); $body += $t.Fix.Body }
  }
  else {
    $body += 'echo Nothing in the list matched your description exactly, so this file repairs everything, checks it and saves a report.'
    $body += 'call "%APP%\Fathom.bat" repair'
    $body += 'if exist "%APP%\support\1-Check-Everything.cmd" call "%APP%\support\1-Check-Everything.cmd"'
  }
  $body += 'set "RPT=%USERPROFILE%\Downloads\Fathom-problem-report.txt"'
  $body += 'echo Problem described by the user:> "%RPT%"'
  foreach ($ln in ($text -split "`r?`n")) { $body += ('echo ' + ($ln -replace '[&%^|<>"()]', ' ') + '>> "%RPT%"') }
  $body += 'echo.>> "%RPT%"'
  $body += 'for %%F in (setup.log bat.log install-update.log) do if exist "%LOCALAPPDATA%\Fathom\%%F" (echo ===== %%F =====>> "%RPT%" & type "%LOCALAPPDATA%\Fathom\%%F" >> "%RPT%")'
  $body += 'echo A report with your description and the logs was saved in "%RPT%". If this did not fix it, send that file to whoever helps you.'
  return (New-FixBat $title ($body -join "`r`n") $text)
}

function Show-Fixes {
  Add-Type -AssemblyName System.Windows.Forms
  Add-Type -AssemblyName System.Drawing
  $d = New-Object System.Windows.Forms.Form
  $d.Text = 'Fathom - Problems and Fixes'; $d.StartPosition = 'CenterParent'; $d.FormBorderStyle = 'FixedDialog'; $d.MaximizeBox = $false; $d.MinimizeBox = $false
  $d.ClientSize = New-Object System.Drawing.Size(760, 560); $d.Font = New-Object System.Drawing.Font('Segoe UI', 9)
  $l1 = New-Object System.Windows.Forms.Label; $l1.Text = 'Pick your problem. You get a .bat file; double-click it and it fixes it or installs what is missing.'; $l1.Location = New-Object System.Drawing.Point(14, 10); $l1.Size = New-Object System.Drawing.Size(730, 20)
  $lb = New-Object System.Windows.Forms.ListBox; $lb.Location = New-Object System.Drawing.Point(14, 36); $lb.Size = New-Object System.Drawing.Size(440, 300); $lb.HorizontalScrollbar = $true
  foreach ($fx in $Fixes) { [void]$lb.Items.Add($fx.Title) }
  $desc = New-Object System.Windows.Forms.TextBox; $desc.Location = New-Object System.Drawing.Point(464, 36); $desc.Size = New-Object System.Drawing.Size(282, 250); $desc.Multiline = $true; $desc.ReadOnly = $true; $desc.BackColor = [System.Drawing.Color]::White
  $bGet = New-Object System.Windows.Forms.Button; $bGet.Text = 'Get this fix file'; $bGet.Location = New-Object System.Drawing.Point(464, 296); $bGet.Size = New-Object System.Drawing.Size(282, 40); $bGet.Enabled = $false
  $l2 = New-Object System.Windows.Forms.Label; $l2.Text = 'My problem is not in the list. Describe it here (what happens, any message you see):'; $l2.Location = New-Object System.Drawing.Point(14, 350); $l2.Size = New-Object System.Drawing.Size(730, 20)
  $tb = New-Object System.Windows.Forms.TextBox; $tb.Location = New-Object System.Drawing.Point(14, 374); $tb.Size = New-Object System.Drawing.Size(732, 90); $tb.Multiline = $true; $tb.ScrollBars = 'Vertical'
  $bMake = New-Object System.Windows.Forms.Button; $bMake.Text = 'Make a fix file from my description'; $bMake.Location = New-Object System.Drawing.Point(14, 472); $bMake.Size = New-Object System.Drawing.Size(260, 34)
  $note = New-Object System.Windows.Forms.Label; $note.Text = 'It picks the closest fixes for your words. If none match it repairs everything, checks it and saves a report with your text and the logs that you can send to get help.'; $note.Location = New-Object System.Drawing.Point(284, 470); $note.Size = New-Object System.Drawing.Size(462, 40); $note.ForeColor = [System.Drawing.Color]::FromArgb(96, 96, 96)
  $bClose = New-Object System.Windows.Forms.Button; $bClose.Text = 'Close'; $bClose.Location = New-Object System.Drawing.Point(656, 520); $bClose.Size = New-Object System.Drawing.Size(90, 30)
  $d.Controls.AddRange(@($l1, $lb, $desc, $bGet, $l2, $tb, $bMake, $note, $bClose))
  $d.CancelButton = $bClose
  $bGet.Tag = 'primary'; $bMake.Tag = 'primary'
  $thm = Get-Theme (Get-ThemeName); Apply-Theme $d $thm
  $d.Add_Shown({ Set-DarkTitleBar $d ($thm.Name -eq 'dark') })

  $save = {
    param($name, $content)
    $dlg = New-Object System.Windows.Forms.SaveFileDialog
    $dlg.Title = 'Where should the fix file go?'; $dlg.Filter = 'Batch file (*.bat)|*.bat'; $dlg.FileName = $name
    $dlg.InitialDirectory = [Environment]::GetFolderPath('Desktop')
    if ($dlg.ShowDialog() -ne 'OK') { return }
    Set-Content -LiteralPath $dlg.FileName -Value $content -Encoding ASCII
    $a = [System.Windows.Forms.MessageBox]::Show("Saved:`r`n" + $dlg.FileName + "`r`n`r`nRun it now? (Windows may ask for permission.)", 'Fathom', 'YesNo', 'Question')
    if ($a -eq 'Yes') { try { Start-Process -FilePath $dlg.FileName } catch {} }
  }
  $lb.Add_SelectedIndexChanged({
    if ($lb.SelectedIndex -ge 0) { $fx = $Fixes[$lb.SelectedIndex]; $desc.Text = $fx.Desc; $bGet.Enabled = $true }
  })
  $bGet.Add_Click({
    if ($lb.SelectedIndex -lt 0) { return }
    $fx = $Fixes[$lb.SelectedIndex]
    & $save ('Fathom-fix-' + $fx.Id + '.bat') (New-FixBat $fx.Title $fx.Body '')
  })
  $bMake.Add_Click({
    if (-not $tb.Text.Trim()) { [System.Windows.Forms.MessageBox]::Show('Please describe the problem first.', 'Fathom') | Out-Null; return }
    & $save 'Fathom-fix-my-problem.bat' (New-ProblemBat $tb.Text.Trim())
  })
  $bClose.Add_Click({ $d.Close() })
  [void]$d.ShowDialog()
}

# ----------------------------------------------------------------------------------------------- the window
function Show-Wizard {
  Add-Type -AssemblyName System.Windows.Forms
  Add-Type -AssemblyName System.Drawing
  [System.Windows.Forms.Application]::EnableVisualStyles()

  $ui = @{}      # every control, by name
  $st = @{ PrevMode = 'one'; Page = 0; Started = $null; Proc = $null; Done = $false; Failed = $false; Plan = $null; Installing = $false; StepStart = @{}; Edition = 'full'; OkCol = [System.Drawing.Color]::DarkGreen; BadCol = [System.Drawing.Color]::Firebrick }

  $fontText = New-Object System.Drawing.Font('Segoe UI', 9)
  $fontBold = New-Object System.Drawing.Font('Segoe UI', 9, [System.Drawing.FontStyle]::Bold)
  $fontBig = New-Object System.Drawing.Font('Segoe UI', 13, [System.Drawing.FontStyle]::Bold)
  $fontHead = New-Object System.Drawing.Font('Segoe UI', 11, [System.Drawing.FontStyle]::Bold)
  $gray = [System.Drawing.Color]::FromArgb(96, 96, 96)

  function New-Label($text, $x, $y, $w, $h) {
    $c = New-Object System.Windows.Forms.Label
    $c.Text = $text; $c.Location = New-Object System.Drawing.Point($x, $y); $c.Size = New-Object System.Drawing.Size($w, $h); $c.AutoSize = $false
    return $c
  }
  function New-Check($text, $x, $y, $w, $checked) {
    $c = New-Object System.Windows.Forms.CheckBox
    $c.Text = $text; $c.Location = New-Object System.Drawing.Point($x, $y); $c.Size = New-Object System.Drawing.Size($w, 22); $c.Checked = $checked
    return $c
  }
  function New-Radio($text, $x, $y, $w, $checked) {
    $c = New-Object System.Windows.Forms.RadioButton
    $c.Text = $text; $c.Location = New-Object System.Drawing.Point($x, $y); $c.Size = New-Object System.Drawing.Size($w, 22); $c.Checked = $checked
    return $c
  }
  function New-Box($x, $y, $w) {
    $c = New-Object System.Windows.Forms.TextBox
    $c.Location = New-Object System.Drawing.Point($x, $y); $c.Size = New-Object System.Drawing.Size($w, 23)
    return $c
  }
  function New-Button($text, $x, $y, $w, $h) {
    $c = New-Object System.Windows.Forms.Button
    $c.Text = $text; $c.Location = New-Object System.Drawing.Point($x, $y); $c.Size = New-Object System.Drawing.Size($w, $h); $c.FlatStyle = 'System'
    return $c
  }
  function New-Page() {
    $p = New-Object System.Windows.Forms.Panel
    $p.Location = New-Object System.Drawing.Point(0, 0); $p.Size = New-Object System.Drawing.Size(720, 440); $p.Visible = $false
    return $p
  }

  $f = New-Object System.Windows.Forms.Form
  $f.Text = 'Fathom Setup'
  $f.StartPosition = 'CenterScreen'
  $f.FormBorderStyle = 'FixedDialog'
  $f.MaximizeBox = $false
  $f.MinimizeBox = $true
  $f.AutoScaleMode = 'None'
  $f.ClientSize = New-Object System.Drawing.Size(720, 580)
  $f.Font = $fontText
  $f.BackColor = [System.Drawing.SystemColors]::Control
  try { $ico = Join-Path $AppDir 'assets\fathom.ico'; if (Test-Path -LiteralPath $ico) { $ms1 = New-Object IO.MemoryStream(, [IO.File]::ReadAllBytes($ico)); $f.Icon = New-Object System.Drawing.Icon($ms1) } } catch {}

  # header
  $head = New-Object System.Windows.Forms.Panel
  $head.Name = 'head'
  $head.Location = New-Object System.Drawing.Point(0, 0); $head.Size = New-Object System.Drawing.Size(720, 64); $head.BackColor = [System.Drawing.Color]::White
  $ui.Title = New-Label '' 20 8 550 28; $ui.Title.Font = $fontBig; $ui.Title.BackColor = [System.Drawing.Color]::White
  $ui.Sub = New-Label '' 22 38 550 20; $ui.Sub.ForeColor = $gray; $ui.Sub.BackColor = [System.Drawing.Color]::White
  $pic = New-Object System.Windows.Forms.PictureBox
  $pic.Location = New-Object System.Drawing.Point(656, 8); $pic.Size = New-Object System.Drawing.Size(48, 48); $pic.SizeMode = 'Zoom'; $pic.BackColor = [System.Drawing.Color]::White
  try { $png = Join-Path $AppDir 'assets\fathom.png'; if (Test-Path -LiteralPath $png) { $ms2 = New-Object IO.MemoryStream(, [IO.File]::ReadAllBytes($png)); $pic.Image = [System.Drawing.Image]::FromStream($ms2) } } catch {}
  $ui.ThemeBtn = New-Button 'Light' 580 18 64 28
  $head.Controls.AddRange(@($ui.Title, $ui.Sub, $pic, $ui.ThemeBtn))
  $f.Controls.Add($head)
  $line1 = New-Object System.Windows.Forms.Label
  $line1.Location = New-Object System.Drawing.Point(0, 64); $line1.Size = New-Object System.Drawing.Size(720, 2); $line1.BorderStyle = 'Fixed3D'
  $f.Controls.Add($line1)

  # content area
  $content = New-Object System.Windows.Forms.Panel
  $content.Location = New-Object System.Drawing.Point(0, 66); $content.Size = New-Object System.Drawing.Size(720, 440)
  $f.Controls.Add($content)

  # footer
  $line2 = New-Object System.Windows.Forms.Label
  $line2.Location = New-Object System.Drawing.Point(0, 508); $line2.Size = New-Object System.Drawing.Size(720, 2); $line2.BorderStyle = 'Fixed3D'
  $f.Controls.Add($line2)
  $ui.Back = New-Button '< Back' 448 526 84 30
  $ui.Next = New-Button 'Next >' 540 526 84 30
  $ui.Cancel = New-Button 'Cancel' 632 526 78 30
  $ui.Fixes = New-Button 'Problems and Fixes...' 14 526 130 30
  $ui.Details = New-Button 'Show log folder' 152 526 130 30
  $ui.Details.Visible = $false
  $f.Controls.AddRange(@($ui.Back, $ui.Next, $ui.Cancel, $ui.Details, $ui.Fixes))
  $f.AcceptButton = $ui.Next
  $ui.Next.Tag = 'primary'

  $tt = New-Object System.Windows.Forms.ToolTip
  $tt.AutoPopDelay = 12000

  # ---- page 0: welcome
  $p0 = New-Page
  $p0.Controls.Add((New-Label ('Fathom finds things inside any file, converts any file to any other supported type, and has a big toolbox, a private AI assistant, a forensics lab and more. Everything runs on your own PC and nothing is sent to us.') 24 14 670 52))
  $p0.Controls.Add((New-Label 'What do you want to install?' 24 78 400 20)); $p0.Controls[$p0.Controls.Count - 1].Font = $fontBold
  $ui.RAll = New-Radio 'Everything (recommended): Fathom, LibreOffice, Calibre, 7-Zip, the free AI assistant and Search by meaning' 38 104 650 $true
  $p0.Controls.Add((New-Label 'One click does it all, nothing else to choose. Everything is downloaded NOW, including every speech model, so no feature ever says ''downloading, please wait''. Needs about 30 GB free and a long first download. Anything already installed is skipped.' 60 126 620 36)); $p0.Controls[$p0.Controls.Count - 1].ForeColor = $gray
  $ui.RLite = New-Radio 'Smallest (Lite): Fathom only' 38 168 650 $false
  $p0.Controls.Add((New-Label 'Search, pictures, audio, video, PDF, text and data tools. Needs about 3 GB. You can add the rest later by opening this setup window again.' 60 190 620 36)); $p0.Controls[$p0.Controls.Count - 1].ForeColor = $gray
  $ui.RCustom = New-Radio 'Let me choose each part' 38 234 650 $false
  $p0.Controls.Add((New-Label 'You will tick the programs yourself on the Programs page.' 60 256 620 20)); $p0.Controls[$p0.Controls.Count - 1].ForeColor = $gray
  $p0.Controls.AddRange(@($ui.RAll, $ui.RLite, $ui.RCustom))
  $p0.Controls.Add((New-Label ('On the next page you choose ONE folder; everything (the app, its data and every program) goes inside it. Windows will ask for permission (administrator) once, when the installation starts. Please keep your PC awake and connected to the internet while it installs.') 24 300 670 60))
  $p0.Controls.Add((New-Label 'Click Next to continue.' 24 364 400 20))

  # ---- page 1: ONE folder for everything
  $best = Get-BestDrive
  $sysDrive = ($env:SystemDrive + '\').ToUpper()
  $p1 = New-Page
  $p1.Controls.Add((New-Label 'Install folder' 24 14 400 20)); $p1.Controls[$p1.Controls.Count - 1].Font = $fontBold
  $p1.Controls.Add((New-Label 'Everything of Fathom goes inside this ONE folder, on this one drive: the app, its data (settings, history, packages, speech and vision models, caches), Python, LibreOffice, Calibre, 7-Zip, Ollama and the AI models. Nothing is put on any other drive. (Windows keeps one tiny shortcut-like link at its usual data place so every program still finds things.)' 24 36 670 66)); $p1.Controls[$p1.Controls.Count - 1].ForeColor = $gray
  $ui.TbApp = New-Box 24 112 560; $ui.TbApp.Text = (Join-Path $best 'Fathom')
  $ui.BrApp = New-Button 'Browse...' 594 110 96 27
  $p1.Controls.Add((New-Label 'Inside it you will get:   Fathom (the app),   Fathom Data,   Programs' 24 148 670 20)); $p1.Controls[$p1.Controls.Count - 1].Font = $fontBold
  # (kept for the code below, but hidden: there is only one folder now)
  $ui.TbData = New-Box 24 0 100; $ui.TbData.Visible = $false
  $ui.BrData = New-Button '' 0 0 10 10; $ui.BrData.Visible = $false
  $ui.CbDataHome = New-Check '' 0 0 10 $false; $ui.CbDataHome.Visible = $false
  $ui.Drives = New-Label '' 24 200 670 40
  $ui.Space1 = New-Label '' 24 250 670 80
  $p1.Controls.AddRange(@($ui.TbApp, $ui.BrApp, $ui.Drives, $ui.Space1))

  # ---- page 2: programs
  $p2 = New-Page
  $ui.RmOne = New-Radio 'Keep the programs together in this folder:' 24 2 400 $true
  $ui.TbBase = New-Box 44 25 540; $ui.TbBase.Text = (Join-Path $best 'Fathom Programs')
  $ui.BrBase = New-Button 'Browse...' 594 23 96 27
  $ui.RmEach = New-Radio 'Choose a folder for each program myself (type or Browse in the boxes below)' 24 54 660 $false
  $ui.RmUsual = New-Radio 'Let Windows put them in its usual places (on the drive Windows is on)' 24 76 660 $false
  $p2.Controls.Add((New-Label 'Tick what to install. Everything you tick is downloaded NOW, during the install (including every speech model), so nothing has to download later when you use a feature.' 24 4 670 36))
  foreach ($c0 in @($ui.RmOne, $ui.TbBase, $ui.BrBase, $ui.RmEach, $ui.RmUsual)) { $c0.Visible = $false }
  $p2.Controls.AddRange(@($ui.RmOne, $ui.TbBase, $ui.BrBase, $ui.RmEach, $ui.RmUsual))
  $ui.Row = @{}
  $y = 48
  foreach ($pt in $Parts) {
    $row = @{}
    $row.Check = New-Check ($pt.Title + ':  ' + $pt.Desc) 24 $y 670 $true
    $row.Check.AutoSize = $false
    $row.Box = New-Box 46 ($y + 21) 538
    $row.Browse = New-Button 'Browse...' 594 ($y + 19) 96 26
    $row.Browse.Visible = $false
    if ($pt.Required) { $row.Check.Enabled = $false }
    $p2.Controls.AddRange(@($row.Check, $row.Box, $row.Browse))
    $ui.Row[$pt.Key] = $row
    $y += 46
  }
  $ui.Space2 = New-Label '' 24 ($y + 4) 670 52
  $p2.Controls.Add($ui.Space2)

  # ---- page 3: shortcuts
  $p3 = New-Page
  $p3.Controls.Add((New-Label 'Where should Fathom''s shortcuts go?' 24 14 500 20)); $p3.Controls[$p3.Controls.Count - 1].Font = $fontBold
  $ui.CbDesk = New-Check 'A Fathom icon on the Desktop' 38 48 400 $true
  $ui.CbStart = New-Check 'A Fathom entry in the Start menu' 38 76 400 $true
  $ui.CbSendTo = New-Check 'Add Fathom to the right-click menu: right-click any file > Send to > Fathom' 38 104 640 $true
  $ui.CbServe = New-Check 'Add a "Fathom Server" shortcut: use Fathom from your phone, tablet or another PC (it shows a private link)' 38 132 650 $false
  $ui.CbServeAuto = New-Check 'Start the server by itself when Windows starts' 62 158 600 $false
  $ui.CbServeAuto.Enabled = $false
  $ui.CbServe.Add_CheckedChanged({ $ui.CbServeAuto.Enabled = [bool]$ui.CbServe.Checked; if (-not $ui.CbServe.Checked) { $ui.CbServeAuto.Checked = $false } })
  $p3.Controls.AddRange(@($ui.CbDesk, $ui.CbStart, $ui.CbSendTo, $ui.CbServe, $ui.CbServeAuto))
  $p3.Controls.Add((New-Label ('Fathom does not add itself to Windows'' Settings > Apps list. To remove it later, open this setup window again and use Problems and Fixes > Remove Fathom: it asks before each part and never touches your own files.') 24 196 670 50))
  $p3.Controls.Add((New-Label ('Click Next to see a summary of your choices. Nothing is installed until you click Install.') 24 262 670 40))

  # ---- page 4: summary
  $p4 = New-Page
  $p4.Controls.Add((New-Label 'These are your choices. Click Back to change anything, or Install to begin.' 24 10 670 20))
  $ui.Summary = New-Object System.Windows.Forms.TextBox
  $ui.Summary.Location = New-Object System.Drawing.Point(24, 36); $ui.Summary.Size = New-Object System.Drawing.Size(670, 380)
  $ui.Summary.Multiline = $true; $ui.Summary.ReadOnly = $true; $ui.Summary.ScrollBars = 'Vertical'; $ui.Summary.BackColor = [System.Drawing.Color]::White
  $ui.Summary.Font = New-Object System.Drawing.Font('Consolas', 9)
  $p4.Controls.Add($ui.Summary)

  # ---- page 5: installing
  $p5 = New-Page
  $ui.Status = New-Label 'Starting ...' 24 12 670 22; $ui.Status.Font = $fontBold
  $ui.Bar = New-Object System.Windows.Forms.ProgressBar
  $ui.Bar.Location = New-Object System.Drawing.Point(24, 40); $ui.Bar.Size = New-Object System.Drawing.Size(670, 22); $ui.Bar.Style = 'Marquee'; $ui.Bar.MarqueeAnimationSpeed = 30
  $p5.Controls.Add((New-Label ('Windows may ask for permission now. Click Yes. A small black window may appear on your taskbar: that is Fathom working, please leave it alone.') 24 70 670 36))
  $ui.Log = New-Object System.Windows.Forms.TextBox
  $ui.Log.Location = New-Object System.Drawing.Point(24, 112); $ui.Log.Size = New-Object System.Drawing.Size(670, 270)
  $ui.Log.Multiline = $true; $ui.Log.ReadOnly = $true; $ui.Log.ScrollBars = 'Vertical'; $ui.Log.BackColor = [System.Drawing.Color]::White; $ui.Log.Font = New-Object System.Drawing.Font('Consolas', 8.5)
  $ui.Wait = New-Label 'Please wait, this takes time.' 24 388 670 44; $ui.Wait.Font = $fontBold
  $p5.Controls.AddRange(@($ui.Status, $ui.Bar, $ui.Log, $ui.Wait))

  # ---- page 6: finished
  $p6 = New-Page
  $ui.FinTitle = New-Label '' 24 14 670 28; $ui.FinTitle.Font = $fontHead
  $ui.FinText = New-Label '' 24 54 670 330
  $p6.Controls.AddRange(@($ui.FinTitle, $ui.FinText))

  $pages = @($p0, $p1, $p2, $p3, $p4, $p5, $p6)
  foreach ($p in $pages) { $content.Controls.Add($p) }
  $titles = @(
    @(('Welcome to Fathom ' + $Version), 'This wizard installs Fathom and the things it works with, where you choose.'),
    @('Where should Fathom go?', 'Pick ONE folder. Everything is kept inside it, on the same drive.'),
    @('What to install', 'Tick what you want. All of it is downloaded now, so nothing downloads later.'),
    @('Shortcuts', 'How you will open Fathom.'),
    @('Ready to install', 'Check your choices.'),
    @('Installing Fathom', 'Please keep this window open. Downloads are the long part.'),
    @('Finished', '')
  )

  # ---- tool tips
  $tt.SetToolTip($ui.TbApp, 'Everything of Fathom is installed inside this folder.')
  $tt.SetToolTip($ui.TbData, 'Where Fathom keeps its settings, history, results and downloaded packages.')
  $tt.SetToolTip($ui.CbDataHome, 'If ticked, the data stays on the drive Windows is on, in the usual place.')
  $tt.SetToolTip($ui.RmOne, 'Python, LibreOffice, Calibre, 7-Zip, Ollama and the AI model each get a sub-folder here.')
  $tt.SetToolTip($ui.RmEach, 'Every program gets exactly the folder you type or choose.')
  $tt.SetToolTip($ui.RmUsual, 'Nothing is moved: Windows installs each program in its normal folder.')

  # ---- logic (closures see $ui, $st, $Parts, $pages, $titles)
  $browse = {
    param($box, $text)
    $d = New-Object System.Windows.Forms.FolderBrowserDialog
    $d.Description = $text
    $d.ShowNewFolderButton = $true
    try { $cur = $box.Text.Trim().Trim('"'); if ($cur -and (Test-Path -LiteralPath (Split-Path -Parent $cur) -ErrorAction SilentlyContinue)) { $d.SelectedPath = (Split-Path -Parent $cur) } } catch {}
    if ($d.ShowDialog() -eq 'OK') { $box.Text = $d.SelectedPath }
  }

  # what the current choices mean: parts that are on, and the folder of each
  $getPlan = {
    $plan = @{}
    $plan.Root = Clean-Path $ui.TbApp.Text
    $plan.App = Join-Path $plan.Root 'Fathom'
    $plan.DataHome = $false
    $plan.Data = Join-Path $plan.Root 'Fathom Data'
    $plan.Mode = 'one'
    $plan.Base = Join-Path $plan.Root 'Programs'
    $plan.Desk = [bool]$ui.CbDesk.Checked
    $plan.Start = [bool]$ui.CbStart.Checked
    $plan.SendTo = [bool]$ui.CbSendTo.Checked
    $plan.Serve = [bool]$ui.CbServe.Checked
    $plan.ServeAuto = [bool]$ui.CbServeAuto.Checked
    $on = @{}; $dirs = [ordered]@{}
    foreach ($pt in $Parts) {
      $r = $ui.Row[$pt.Key]
      $isOn = [bool]$r.Check.Checked
      if ($pt.Key -eq 'models' -and -not [bool]$ui.Row['ollama'].Check.Checked) { $isOn = $false }
      $on[$pt.Key] = $isOn
      if ($isOn) {
        if ($plan.Mode -eq 'usual') { $dirs[$pt.Key] = '' }
        elseif ($plan.Mode -eq 'one') { $dirs[$pt.Key] = (Join-Path $plan.Base $pt.Folder) }
        else { $dirs[$pt.Key] = (Clean-Path $r.Box.Text) }
      }
    }
    $plan.On = $on; $plan.Dirs = $dirs
    return $plan
  }

  # space needed per drive, in GB (drive letter -> number)
  $getNeeds = {
    param($plan)
    $needs = @{}
    $add = {
      param($path, $gb)
      $k = ''
      if ($path) { $k = Get-DriveKey $path } else { $k = $env:SystemDrive.ToUpper() }
      if ($k) { if ($needs.ContainsKey($k)) { $needs[$k] = $needs[$k] + $gb } else { $needs[$k] = $gb } }
    }
    & $add $plan.App 0.1
    if ($plan.DataHome) { & $add '' 3.0 } else { & $add $plan.Data 22.0 }
    foreach ($pt in $Parts) {
      if ($plan.On[$pt.Key]) { & $add $plan.Dirs[$pt.Key] $pt.GB }
    }
    return $needs
  }

  $needsText = {
    param($plan, $needs)
    $lines = @(); $short = $false
    foreach ($k in ($needs.Keys | Sort-Object)) {
      $free = Get-FreeGB ($k + '\')
      $n = [math]::Round($needs[$k], 1)
      if ($free -lt 0) { $lines += ('{0}  needs about {1:N1} GB (this drive cannot be read)' -f $k, $n); $short = $true }
      elseif ($free -lt $n) { $lines += ('{0}  needs about {1:N1} GB but only {2:N1} GB is free: NOT ENOUGH' -f $k, $n, $free); $short = $true }
      else { $lines += ('{0}  needs about {1:N1} GB, {2:N1} GB free: OK' -f $k, $n, $free) }
    }
    return @{ Text = ($lines -join [Environment]::NewLine); Short = $short }
  }

  $refresh = {
    $plan = & $getPlan
    $needs = & $getNeeds $plan
    $nt = & $needsText $plan $needs
    $col = $st.OkCol
    if ($nt.Short) { $col = $st.BadCol }
    $prev = $st.PrevMode; $st.PrevMode = $plan.Mode
    if ($plan.Mode -eq 'each' -and $prev -ne 'each') { foreach ($pt in $Parts) { $ui.Row[$pt.Key].Box.Text = (Join-Path $plan.Base $pt.Folder) } }
    $ui.Space1.Text = $nt.Text; $ui.Space1.ForeColor = $col
    $ui.Space2.Text = $nt.Text; $ui.Space2.ForeColor = $col
    $ui.TbData.Enabled = -not $ui.CbDataHome.Checked; $ui.BrData.Enabled = -not $ui.CbDataHome.Checked
    # the program boxes: filled in and locked together in one folder / usual places, free to edit when each is chosen by hand
    foreach ($pt in $Parts) {
      $r = $ui.Row[$pt.Key]
      $isOn = [bool]$r.Check.Checked
      if ($pt.Key -eq 'models') { $isOn = $isOn -and [bool]$ui.Row['ollama'].Check.Checked }
      if ($plan.Mode -eq 'one') { $r.Box.Text = (Join-Path $plan.Base $pt.Folder) }
      elseif ($plan.Mode -eq 'usual') {
        if ($pt.Key -eq 'models') { $r.Box.Text = (Join-Path $env:USERPROFILE '.ollama') }
        elseif ($pt.Key -eq 'ollama') { $r.Box.Text = (Join-Path $env:LOCALAPPDATA 'Programs\Ollama') }
        elseif ($pt.Key -eq 'python') { $r.Box.Text = (Join-Path $env:ProgramFiles 'Python312') }
        else { $r.Box.Text = (Join-Path $env:ProgramFiles $pt.Folder) }
      }
      elseif (-not $r.Box.Text) { $r.Box.Text = (Join-Path $plan.Base $pt.Folder) }
      $r.Box.Enabled = ($plan.Mode -eq 'each') -and $isOn
      $r.Browse.Enabled = ($plan.Mode -eq 'each') -and $isOn
    }
    $ui.TbBase.Enabled = ($plan.Mode -eq 'one'); $ui.BrBase.Enabled = ($plan.Mode -eq 'one')
    $ui.Row['models'].Check.Enabled = [bool]$ui.Row['ollama'].Check.Checked
  }
  $ui.Refresh = $refresh

  $drivesText = @()
  foreach ($d in [IO.DriveInfo]::GetDrives()) { if ($d.DriveType -eq 'Fixed' -and $d.IsReady) { $drivesText += ('{0} {1:N0} GB free' -f $d.Name.Substring(0, 2), ($d.AvailableFreeSpace / 1GB)) } }
  $ui.Drives.Text = 'Drives on this PC:  ' + ($drivesText -join '     ')
  $ui.Drives.ForeColor = $gray

  $presetAll = { foreach ($pt in $Parts) { if (-not $pt.Required) { $ui.Row[$pt.Key].Check.Checked = $true } }; & $ui.Refresh }
  $presetLite = { foreach ($pt in $Parts) { if (-not $pt.Required) { $ui.Row[$pt.Key].Check.Checked = $false } }; & $ui.Refresh }
  $ui.RAll.Add_CheckedChanged({ if ($ui.RAll.Checked) { & $presetAll } })
  $ui.RLite.Add_CheckedChanged({ if ($ui.RLite.Checked) { & $presetLite } })

  foreach ($c in @($ui.TbApp, $ui.TbData, $ui.TbBase)) { $c.Add_TextChanged({ & $ui.Refresh }.GetNewClosure()) }
  foreach ($c in @($ui.CbDataHome, $ui.RmOne, $ui.RmEach, $ui.RmUsual)) { $c.Add_CheckedChanged({ & $ui.Refresh }.GetNewClosure()) }
  foreach ($pt in $Parts) {
    $r = $ui.Row[$pt.Key]
    $r.Check.Add_CheckedChanged({ & $ui.Refresh }.GetNewClosure())
    $r.Box.Add_TextChanged({ if ($ui.RmEach.Checked) { & $ui.Refresh } }.GetNewClosure())
    $bx = $r.Box; $ttl = ('Choose the folder for ' + $pt.Title)
    $r.Browse.Add_Click({ & $browse $bx $ttl }.GetNewClosure())
  }
  $ui.BrApp.Add_Click({ & $browse $ui.TbApp 'Choose the ONE folder where everything of Fathom will be kept' })
  $ui.BrData.Add_Click({ & $browse $ui.TbData 'Choose the folder for Fathom''s data' })
  $ui.BrBase.Add_Click({ & $browse $ui.TbBase 'Choose the folder that will hold the programs' })

  # ---- checks before moving on
  $validate = {
    param($page)
    $plan = & $getPlan
    if ($page -eq 1) {
      $m = Test-Folder $plan.Root 'Fathom'
      if ($m) { return $m }
    }
    if ($page -eq 99) {
      if ($plan.Mode -eq 'one') { $m = Test-Folder $plan.Base 'the programs'; if ($m) { return $m } }
      if ($plan.Mode -eq 'each') {
        foreach ($pt in $Parts) { if ($plan.On[$pt.Key]) { $m = Test-Folder $plan.Dirs[$pt.Key] $pt.Title; if ($m) { return $m } } }
        $seen = @{}
        foreach ($k in $plan.Dirs.Keys) { $v = $plan.Dirs[$k].ToLower(); if ($seen.ContainsKey($v)) { return 'Two programs have the same folder. Give each one its own folder.' }; $seen[$v] = $true }
      }
    }
    return ''
  }

  $buildSummary = {
    $plan = & $getPlan
    $nl = [Environment]::NewLine
    $t = @()
    $t += 'FATHOM ' + $Version
    $t += ''
    $t += 'Install folder (everything goes inside it): ' + $plan.Root
    $t += 'App folder:   ' + $plan.App
    if ($plan.DataHome) { $t += 'Data folder:  Windows'' usual place (' + $DataHome + ')' } else { $t += 'Data folder:  ' + $plan.Data }
    $t += ''
    $t += 'Programs:'
    foreach ($pt in $Parts) {
      if ($plan.On[$pt.Key]) {
        $where = $plan.Dirs[$pt.Key]; if (-not $where) { $where = "Windows' usual place" }
        $t += ('  [x] {0,-20} {1}' -f $pt.Title, $where)
      } else { $t += ('  [ ] {0,-20} not installed' -f $pt.Title) }
    }
    $t += ''
    $sc = @(); if ($plan.Desk) { $sc += 'Desktop icon' }; if ($plan.Start) { $sc += 'Start menu entry' }
    if ($sc.Count -eq 0) { $sc = @('none') }
    $t += 'Shortcuts:    ' + ($sc -join ', ')
    $t += 'Server mode shortcut: ' + $(if ($plan.Serve) { $(if ($plan.ServeAuto) { 'yes, starts with Windows' } else { 'yes' }) } else { 'no' })
    $t += 'Right-click menu (Send to > Fathom): ' + $(if ($plan.SendTo) { 'yes' } else { 'no' })
    $t += ''
    $needs = & $getNeeds $plan
    $nt = & $needsText $plan $needs
    $t += 'Space (about):'
    foreach ($l in ($nt.Text -split [Environment]::NewLine)) { $t += '  ' + $l }
    $ui.Summary.Text = ($t -join $nl)
    return $nt.Short
  }

  $setPage = {
    param($n)
    $st.Page = $n
    for ($i = 0; $i -lt $pages.Count; $i++) { $pages[$i].Visible = ($i -eq $n) }
    $ui.Title.Text = $titles[$n][0]; $ui.Sub.Text = $titles[$n][1]
    $ui.Back.Enabled = ($n -ge 1 -and $n -le 4)
    $ui.Back.Visible = ($n -le 4)
    $ui.Next.Text = 'Next >'
    $ui.Next.Enabled = $true
    $ui.Cancel.Enabled = $true
    $ui.Cancel.Text = 'Cancel'
    if ($n -eq 4) { $ui.Next.Text = 'Install'; [void](& $buildSummary) }
    if ($n -eq 5) { $ui.Next.Enabled = $false; $ui.Back.Visible = $false; $ui.Cancel.Text = 'Close' }
    if ($n -eq 6) { $ui.Next.Text = 'Finish'; $ui.Back.Visible = $false; $ui.Cancel.Visible = $false; $ui.Next.Enabled = $true }
    & $ui.Refresh
  }
  $ui.SetPage = $setPage

  # ---- writing the choices and starting the installation
  $startInstall = {
    $plan = & $getPlan
    $nl = "`r`n"
    $skip = @()
    foreach ($k in 'libreoffice', 'calibre', '7zip', 'ollama') { if (-not $plan.On[$k]) { $skip += $k } }
    $edition = 'custom'
    if ($skip.Count -eq 4) { $edition = 'lite' } elseif ($skip.Count -eq 0) { $edition = 'full' }
    $st.Edition = $(if ($skip.Count -ge 3) { 'lite' } else { 'full' })
    $parent = Split-Path -Parent $plan.App
    if (-not $parent) { $parent = $plan.App }
    $lines = @(
      '# Saved by the Fathom setup wizard. Delete this file to install in place without moving anything.',
      ('EDITION=' + $edition),
      ('DEST=' + $parent),
      ('APPDIR=' + $plan.App)
    )
    if ($plan.DataHome) { $lines += 'DATA=default' } else { $lines += ('DATADIR=' + $plan.Data) }
    if ($plan.Mode -eq 'usual') { $lines += 'PROGRAMS=default' }
    else {
      $lines += 'PROGRAMS=dest'
      if ($plan.Mode -eq 'one') { $lines += ('PROGBASE=' + $plan.Base) }
      else {
        $lines += ('PROGBASE=' + (Join-Path $parent 'Fathom Programs'))
        $pairs = @(); foreach ($k in $plan.Dirs.Keys) { $pairs += ($k + '=' + $plan.Dirs[$k]) }
        $lines += ('DIRS=' + ($pairs -join '|'))
      }
    }
    $lines += ('SKIP=' + ($skip -join ','))
    $lines += ('DESKTOP_SHORTCUT=' + $(if ($plan.Desk) { '1' } else { '0' }))
    $lines += ('START_SHORTCUT=' + $(if ($plan.Start) { '1' } else { '0' }))
    $lines += 'WIZARD=1'
    Set-Content -LiteralPath (Join-Path $AppDir 'install-choice.txt') -Value $lines -Encoding ASCII
    $bat = Join-Path $AppDir 'Fathom.bat'
    if (-not (Test-Path -LiteralPath $bat)) { return 'Fathom.bat was not found next to the wizard. Extract the whole Fathom zip first.' }
    $st.Started = Get-Date
    try {
      $st.Proc = Start-Process -FilePath $env:ComSpec -ArgumentList ('/c ""' + $bat + '" repair"') -WorkingDirectory $AppDir -Verb RunAs -WindowStyle Minimized -PassThru
    } catch {
      return 'Windows did not give permission (or the installation could not start). Nothing was installed. Click Install again and choose Yes when Windows asks.'
    }
    $st.Plan = $plan
    return ''
  }

  # ---- watching the installation (the log files Fathom writes)
  $readTail = {
    param($path, $count)
    try {
      if (-not (Test-Path -LiteralPath $path)) { return @() }
      $fs = New-Object IO.FileStream($path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
      $sr = New-Object IO.StreamReader($fs, [Text.Encoding]::UTF8)
      $all = $sr.ReadToEnd(); $sr.Close(); $fs.Close()
      $ls = @($all -split "`r?`n")
      if ($ls.Count -gt $count) { $ls = $ls[($ls.Count - $count)..($ls.Count - 1)] }
      return $ls
    } catch { return @() }
  }

  $finish = {
    param($ok, $why)
    $st.Done = $true
    $ui.Timer.Stop()
    $ui.Bar.Style = 'Continuous'
    if ($ok) {
      try {
        if ($st.Plan.SendTo) {
          $pyw = Join-Path $DataHome 'venv\Scripts\pythonw.exe'
          $launch = Join-Path $st.Plan.App 'launch.py'
          if ((Test-Path -LiteralPath $pyw) -and (Test-Path -LiteralPath $launch)) {
            $ws = New-Object -ComObject WScript.Shell
            $lnk = $ws.CreateShortcut((Join-Path ([Environment]::GetFolderPath('SendTo')) 'Fathom.lnk'))
            $lnk.TargetPath = $pyw; $lnk.Arguments = '"' + $launch + '"'; $lnk.WorkingDirectory = $st.Plan.App
            $ico = Join-Path $st.Plan.App 'assets\fathom.ico'; if (Test-Path -LiteralPath $ico) { $lnk.IconLocation = $ico }
            $lnk.Save()
          }
        }
      } catch {}
      try {
        if ($st.Plan.Serve) {
          $bat = Join-Path $st.Plan.App 'Fathom.bat'
          $ws2 = New-Object -ComObject WScript.Shell
          $ico2 = Join-Path $st.Plan.App 'assets\fathom.ico'
          $places = @()
          if ($st.Plan.Desk) { $places += [Environment]::GetFolderPath('Desktop') }
          if ($st.Plan.Start) { $places += [Environment]::GetFolderPath('Programs') }
          if ($places.Count -eq 0) { $places += [Environment]::GetFolderPath('Desktop') }
          foreach ($pl in $places) {
            $l2 = $ws2.CreateShortcut((Join-Path $pl 'Fathom Server.lnk'))
            $l2.TargetPath = $env:ComSpec; $l2.Arguments = '/k ""' + $bat + '" serve"'; $l2.WorkingDirectory = $st.Plan.App
            if (Test-Path -LiteralPath $ico2) { $l2.IconLocation = $ico2 }
            $l2.Save()
          }
          if ($st.Plan.ServeAuto) {
            $l3 = $ws2.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Startup')) 'Fathom Server.lnk'))
            $l3.TargetPath = $env:ComSpec; $l3.Arguments = '/c ""' + $bat + '" serve"'; $l3.WorkingDirectory = $st.Plan.App; $l3.WindowStyle = 7
            if (Test-Path -LiteralPath $ico2) { $l3.IconLocation = $ico2 }
            $l3.Save()
          }
        }
      } catch {}
      $ui.Bar.Value = 100
      & $setPage 6
      $ui.Title.Text = 'Fathom is installed'
      $ui.FinTitle.Text = 'Everything is ready.'
      $ui.FinText.Text = ('Fathom ' + $Version + ' was installed as you chose:' + [Environment]::NewLine + [Environment]::NewLine + '   App:   ' + $st.Plan.App + [Environment]::NewLine + $(if ($st.Plan.DataHome) { '   Data:  ' + $DataHome } else { '   Data:  ' + $st.Plan.Data }) + [Environment]::NewLine + [Environment]::NewLine + 'Fathom opens by itself in a moment. From now on, use the Fathom icon on your Desktop or in the Start menu.' + [Environment]::NewLine + [Environment]::NewLine + 'If the assistant is slow to answer the first time, wait a minute: it is loading into memory.')
    }
    else {
      & $setPage 6
      $ui.Title.Text = 'Setup did not finish'
      $ui.FinTitle.Text = 'Something went wrong.'
      $ui.FinText.Text = ($why + [Environment]::NewLine + [Environment]::NewLine + 'Nothing is broken: you can run this wizard again and it carries on from where it stopped. If it keeps failing, click "Show log folder" and send me the files setup.log and bat.log from it.')
      $ui.Details.Visible = $true
    }
  }

  # "Please wait, this takes time": rough minutes each of the 10 setup steps usually takes (the model download is the long one);
  # the guess is scaled by how fast the steps so far really went on this PC.
  $stepWeights = @{ full = @(1, 2, 3, 2, 3, 8, 10, 22, 2, 1); lite = @(1, 2, 3, 2, 3, 8, 0.5, 4, 2, 1) }
  $fmtLeft = {
    param([double]$min)
    if ($min -lt 1) { return 'less than a minute' }
    if ($min -lt 1.6) { return 'about a minute' }
    if ($min -lt 90) { return ('about ' + [int][math]::Round($min) + ' minutes') }
    return ('about ' + [math]::Round($min / 60, 1) + ' hours')
  }
  $waitText = {
    param($stepNo, $stepCount)
    $elapsedMin = ((Get-Date) - $st.Started).TotalMinutes
    $so = if ($elapsedMin -lt 1) { ([int](((Get-Date) - $st.Started).TotalSeconds)).ToString() + ' seconds' } else { ([int][math]::Round($elapsedMin)).ToString() + ' minutes' }
    $head = 'Please wait, this takes time. ' + $so + ' so far'
    if ($null -eq $stepNo -or $stepCount -ne 10) { return ($head + '; working out how long is left ...') }
    $w = $stepWeights[$st.Edition]; if (-not $w) { $w = $stepWeights['full'] }
    if (-not $st.StepStart.ContainsKey($stepNo)) { $st.StepStart[$stepNo] = Get-Date }
    $inStepMin = ((Get-Date) - $st.StepStart[$stepNo]).TotalMinutes
    $before = 0.0; for ($i = 1; $i -lt $stepNo; $i++) { $before += $w[$i - 1] }
    $cur = [double]$w[$stepNo - 1]
    $curDone = [math]::Min($inStepMin / [math]::Max($cur, 0.5), 0.9) * $cur
    $total = ($w | Measure-Object -Sum).Sum
    $doneW = $before + $curDone
    $factor = 1.0
    if ($doneW -ge 2) { $factor = [math]::Min(6.0, [math]::Max(0.4, $elapsedMin / $doneW)) }
    $left = ($total - $doneW) * $factor
    if ($inStepMin -gt ($cur * $factor * 1.3) -and $stepNo -lt 10) { $left = $left + ($cur * $factor * 0.3) }
    return ($head + ', ' + (& $fmtLeft $left) + ' left (a rough guess: it depends on your internet speed).')
  }

  $ui.Timer = New-Object System.Windows.Forms.Timer
  $ui.Timer.Interval = 1500
  $ui.Timer.Add_Tick({
    if ($st.Done) { return }
    $dataNow = $DataHome
    $okFile = Join-Path $dataNow 'installed-2.ok'
    $failFile = Join-Path $dataNow 'install-failed.txt'
    $since = $st.Started.AddSeconds(-3)
    # log: show whichever of the two log files was written last
    $cand = @()
    foreach ($n in 'setup.log', 'bat.log') {
      $pth = Join-Path $dataNow $n
      if (Test-Path -LiteralPath $pth) { $cand += Get-Item -LiteralPath $pth }
    }
    if ($cand.Count -gt 0) {
      $newest = $cand | Sort-Object LastWriteTime -Descending | Select-Object -First 1
      if ($newest.LastWriteTime -ge $since) {
        $tail = & $readTail $newest.FullName 60
        $ui.Log.Text = ($tail -join [Environment]::NewLine)
        $ui.Log.SelectionStart = $ui.Log.Text.Length; $ui.Log.ScrollToCaret()
        $stepLine = $null
        foreach ($l in $tail) { if ($l -match '^\[(\d+)/(\d+)\]\s*(.*)$') { $stepLine = $matches } }
        if ($stepLine) {
          $a = [int]$stepLine[1]; $b = [int]$stepLine[2]
          if ($b -gt 0) { $ui.Bar.Style = 'Continuous'; $ui.Bar.Value = [math]::Min(99, [int](100 * $a / ($b + 1))) }
          $ui.Status.Text = ('Step ' + $a + ' of ' + $b + ': ' + $stepLine[3])
          $ui.Wait.Text = (& $waitText $a $b)
        }
        else { $ui.Status.Text = 'Getting things ready ...'; $ui.Wait.Text = (& $waitText $null 0) }
      }
    }
    if ((Test-Path -LiteralPath $okFile) -and ((Get-Item -LiteralPath $okFile).LastWriteTime -ge $since)) { & $finish $true ''; return }
    if ((Test-Path -LiteralPath $failFile) -and ((Get-Item -LiteralPath $failFile).LastWriteTime -ge $since)) {
      $why = 'The installation stopped.'
      try { $why = 'The installation stopped: ' + ((Get-Content -LiteralPath $failFile -ErrorAction Stop) -join ' ') } catch {}
      & $finish $false $why; return
    }
    if (((Get-Date) - $st.Started).TotalMinutes -gt 150) { & $finish $false 'The installation has been running for over two and a half hours with no result.' }
  })

  # ---- buttons
  $ui.Next.Add_Click({
    $n = $st.Page
    if ($n -eq 6) { $f.DialogResult = 'OK'; $f.Close(); return }
    if ($n -eq 1 -or $n -eq 2) {
      $m = & $validate $n
      if ($m) { [System.Windows.Forms.MessageBox]::Show($m, 'Fathom Setup', 'OK', 'Information') | Out-Null; return }
    }
    if ($n -eq 3) { & $setPage 4; return }
    if ($n -eq 4) {
      $plan = & $getPlan
      $needs = & $getNeeds $plan
      $nt = & $needsText $plan $needs
      if ($nt.Short) {
        $a = [System.Windows.Forms.MessageBox]::Show("One of the drives does not have enough free space for these choices:`r`n`r`n" + $nt.Text + "`r`n`r`nInstall anyway? (Go Back to choose other folders or untick something.)", 'Fathom Setup', 'YesNo', 'Warning')
        if ($a -ne 'Yes') { return }
      }
      $msg = & $startInstall
      if ($msg) { [System.Windows.Forms.MessageBox]::Show($msg, 'Fathom Setup', 'OK', 'Information') | Out-Null; return }
      $st.Installing = $true
      & $setPage 5
      $ui.Timer.Start()
      return
    }
    & $setPage ($n + 1)
  })
  $ui.Back.Add_Click({ if ($st.Page -ge 1) { & $setPage ($st.Page - 1) } })
  $ui.Cancel.Add_Click({
    if ($st.Installing -and -not $st.Done) {
      $a = [System.Windows.Forms.MessageBox]::Show("The installation keeps running in its own window even if you close this one.`r`n`r`nClose this window anyway?", 'Fathom Setup', 'YesNo', 'Question')
      if ($a -ne 'Yes') { return }
    }
    elseif (-not $st.Done) {
      $a = [System.Windows.Forms.MessageBox]::Show("Close the wizard? Nothing has been installed yet.", 'Fathom Setup', 'YesNo', 'Question')
      if ($a -ne 'Yes') { return }
    }
    $f.DialogResult = 'Cancel'; $f.Close()
  })
  $ui.Fixes.Add_Click({ try { Show-Fixes } catch { [System.Windows.Forms.MessageBox]::Show('The fixes window could not open: ' + $_.Exception.Message, 'Fathom Setup') | Out-Null } })
  $ui.Details.Add_Click({ try { Start-Process -FilePath 'explorer.exe' -ArgumentList ('"' + $DataHome + '"') } catch {} })

  $st.ThemeName = Get-ThemeName
  $applyTheme = {
    $t = Get-Theme $st.ThemeName
    $st.OkCol = $t.Ok; $st.BadCol = $t.Bad
    Apply-Theme $f $t
    $ui.ThemeBtn.Text = $(if ($t.Name -eq 'dark') { 'Light' } else { 'Dark' })
    $ui.Bar.BackColor = $t.Accent
    if ($f.IsHandleCreated) { Set-DarkTitleBar $f ($t.Name -eq 'dark') }
    try { & $ui.Refresh } catch {}
  }
  $ui.ThemeBtn.Add_Click({ if ($st.ThemeName -eq 'dark') { $st.ThemeName = 'light' } else { $st.ThemeName = 'dark' }; Save-ThemeName $st.ThemeName; & $applyTheme })
  $f.Add_Shown({ Set-DarkTitleBar $f ($st.ThemeName -eq 'dark') })
  & $applyTheme
  if ($env:FATHOM_WIZARD_TEST) { $global:WizUi = $ui; $global:WizSt = $st; $global:WizFns = @{ GetPlan = $getPlan; Validate = $validate; Summary = $buildSummary } }
  & $setPage 0
  [void]$f.ShowDialog()
  try { $ui.Timer.Stop() } catch {}
  return @{ Installed = $st.Done -and -not $st.Failed; Started = $st.Installing }
}

# ----------------------------------------------------------------------------------------------- questions in the console (only if the window cannot open)
function Show-Console {
  Write-Host ''
  Write-Host 'Install Fathom' -ForegroundColor Cyan
  Write-Host 'The Fathom app itself is always installed. Answer Y or N for each extra.'
  function YN($q) { $a = Read-Host ($q + ' (Y/N)'); return ($a -match '^\s*(y|yes)\s*$') }
  $o = YN 'LibreOffice: open and convert Word, Excel, PowerPoint (about 350 MB)'
  $c = YN 'Calibre: convert e-books (about 200 MB)'
  $z = YN '7-Zip: open RAR and 7z files (small)'
  $a = YN 'Free AI assistant on this PC: Ollama and its model (about 3.3 GB)'
  $def = Join-Path (Get-BestDrive) 'Fathom'
  $p = Read-Host ("Folder for the Fathom app (press Enter for " + $def + ")")
  if (-not $p) { $p = $def }
  $p = Clean-Path $p
  $parent = Split-Path -Parent $p; if (-not $parent) { $parent = $p }
  $skip = @(); if (-not $o) { $skip += 'libreoffice' }; if (-not $c) { $skip += 'calibre' }; if (-not $z) { $skip += '7zip' }; if (-not $a) { $skip += 'ollama' }
  $lines = @('# Saved by the Fathom setup wizard.', 'EDITION=custom', ('DEST=' + $parent), ('APPDIR=' + $p), 'PROGRAMS=dest', ('SKIP=' + ($skip -join ',')), 'DESKTOP_SHORTCUT=1', 'START_SHORTCUT=1')
  Set-Content -LiteralPath (Join-Path $AppDir 'install-choice.txt') -Value $lines -Encoding ASCII
  Write-Host ('Installing Fathom into ' + $p + ' ...')
  $bat = Join-Path $AppDir 'Fathom.bat'
  if (-not (Test-Path -LiteralPath $bat)) { Write-Host 'Fathom.bat was not found next to the installer.'; return }
  Start-Process -FilePath $bat -WorkingDirectory $AppDir -Wait
}

try { [void](Show-Wizard) }
catch {
  $msg = 'The setup window could not open: ' + $_.Exception.Message
  try { Set-Content -LiteralPath (Join-Path $env:TEMP 'fathom-wizard-error.txt') -Value ($_ | Out-String) -Encoding UTF8 } catch {}
  if ($Host.Name -eq 'ConsoleHost' -and [Environment]::UserInteractive -and -not $env:FATHOM_NO_CONSOLE) {
    # started from Fathom.bat setup (a visible window): ask the questions here instead
    try { Write-Host ('(' + $msg + ') Using questions instead.'); Show-Console } catch { Write-Host $_.Exception.Message }
  }
}
