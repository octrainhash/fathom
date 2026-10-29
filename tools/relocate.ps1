# Moves the big programs Fathom uses to the folders you chose and leaves a small link behind, so Windows and the programs
# still find them where they expect (nothing else has to change). Programs that are not installed yet get an empty
# link ready, so the installer writes straight there. (Ollama's models are the exception: no link, see below.) Safe to run twice. Called by Move-Fathom.cmd.
param(
  [string]$Dest = (Join-Path $env:SystemDrive '\Fathom Programs'),
  [string]$Log = '',
  [switch]$Lite,
  [string]$Skip = '',
  # your own folder for single parts, written  key=folder|key=folder  with the keys python, libreoffice, calibre, 7zip, ollama, models
  # (the installer wizard passes it in the FATHOM_DIRS setting; a part without an entry goes under -Dest)
  [string]$Dirs = ''
)
$ErrorActionPreference = 'Continue'
$skipSet = @($Skip.ToLower().Split(@(',', ';', ' '), [StringSplitOptions]::RemoveEmptyEntries))
if ($Lite) { $skipSet += @('libreoffice', 'calibre', '7zip', 'ollama') }

function Say([string]$m) {
  Write-Host $m
  if ($Log) { try { Add-Content -LiteralPath $Log -Value $m -Encoding UTF8 } catch {} }
}

# the places Fathom made (link -> real folder) are written down, so Uninstall-Fathom.cmd can find them again
$placesFile = Join-Path (Join-Path $env:LOCALAPPDATA 'Fathom') 'places.txt'
function Note-Place([string]$link, [string]$target) {
  try {
    New-Item -ItemType Directory -Path (Split-Path -Parent $placesFile) -Force -ErrorAction Stop | Out-Null
    Add-Content -LiteralPath $placesFile -Value ($link + '|' + $target) -Encoding ASCII
  } catch {}
}
$custom = @{}
if (-not $Dirs) { $Dirs = $env:FATHOM_DIRS }
foreach ($pair in @($Dirs -split '\|')) {
  $i = $pair.IndexOf('=')
  if ($i -gt 0) { $v = $pair.Substring($i + 1).Trim().Trim('"'); if ($v) { $custom[$pair.Substring(0, $i).Trim().ToLower()] = $v } }
}
function Pick([string]$key, [string]$fallback) { if ($custom.ContainsKey($key)) { return $custom[$key] } else { return $fallback } }

$pf = $env:ProgramFiles
$items = @(
  @{ Key = 'python';  Name = 'Python 3.12';                 Src = (Join-Path $pf 'Python312');                          Dst = (Pick 'python' (Join-Path $Dest 'Python312')) },
  @{ Key = 'libreoffice'; Name = 'LibreOffice';                 Src = (Join-Path $pf 'LibreOffice');                        Dst = (Pick 'libreoffice' (Join-Path $Dest 'LibreOffice')) },
  @{ Key = 'calibre'; Name = 'Calibre';                     Src = (Join-Path $pf 'Calibre2');                           Dst = (Pick 'calibre' (Join-Path $Dest 'Calibre2')) },
  @{ Key = '7zip'; Name = '7-Zip';                       Src = (Join-Path $pf '7-Zip');                              Dst = (Pick '7zip' (Join-Path $Dest '7-Zip')) },
  @{ Key = 'ollama'; Name = 'Ollama (program)';            Src = (Join-Path $env:LOCALAPPDATA 'Programs\Ollama');      Dst = (Pick 'ollama' (Join-Path $Dest 'Ollama')) },
  @{ Key = 'ollama'; Name = 'Ollama (AI model and data)';  Src = (Join-Path $env:USERPROFILE '.ollama');               Dst = (Pick 'models' (Join-Path $Dest 'Ollama Models')); NoLink = $true }
)

# programs that would keep files locked
foreach ($p in 'soffice', 'soffice.bin', 'ollama', 'ollama app', 'ollama_llama_server', '7zFM', 'calibre', 'ebook-convert') {
  Get-Process -Name $p -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2

function Dir-Size([string]$p) {
  $s = (Get-ChildItem -LiteralPath $p -Recurse -Force -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
  if ($s) { return [int64]$s } else { return [int64]0 }
}

if ($custom.Count -eq 0) { try { New-Item -ItemType Directory -Path $Dest -Force -ErrorAction Stop | Out-Null } catch { Say "  Could not create $Dest : $($_.Exception.Message)"; exit 2 } }

$bad = 0
foreach ($it in $items) {
  $name = $it.Name; $src = $it.Src; $dst = $it.Dst
  $driveName = 'C'
  try { $driveName = ([IO.Path]::GetPathRoot($dst)).Substring(0, 1) } catch {}
  try {
    $parent = Split-Path -Parent $src
    if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }

    if ($it.NoLink) {
      # Ollama 0.40 cannot read models through a link ("bad manifest ... cannot find the path"), so its models are NOT linked:
      # they are moved to your folder and Ollama is told where they are with the OLLAMA_MODELS setting (the way Ollama documents it).
      if ($skipSet -contains $it.Key) { continue }
      $m = Join-Path $dst 'models'
      New-Item -ItemType Directory -Path $m -Force | Out-Null
      if (Test-Path -LiteralPath $src) {
        $item = Get-Item -LiteralPath $src -Force
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
          $t = $item.Target | Select-Object -First 1
          if ($t) { $m = Join-Path $t 'models' }
          Say "  $name : was linked (the old way). Ollama is now pointed straight at $m."
        }
        else {
          $sm = Join-Path $src 'models'
          if (Test-Path -LiteralPath $sm) {
            $size = Dir-Size $sm
            $free = (Get-PSDrive -Name $driveName).Free
            if ($free -lt ($size * 1.05 + 50MB)) { Say ("  $name : NOT moved - the new drive has only {0:N1} GB free and this needs {1:N1} GB." -f ($free / 1GB), ($size / 1GB)); $bad++; continue }
            Say ("  $name : moving {0:N1} GB of models to $m ..." -f ($size / 1GB))
            & robocopy.exe $sm $m /E /COPY:DAT /DCOPY:DAT /R:2 /W:2 /NFL /NDL /NJH /NJS /NP | Out-Null
            if ($LASTEXITCODE -ge 8) { Say "  $name : the copy did not finish (robocopy code $LASTEXITCODE). Left where it was."; $bad++; continue }
            $oldCount = (Get-ChildItem -LiteralPath $sm -Recurse -Force -File -ErrorAction SilentlyContinue | Measure-Object).Count
            $newCount = (Get-ChildItem -LiteralPath $m -Recurse -Force -File -ErrorAction SilentlyContinue | Measure-Object).Count
            if ($newCount -lt $oldCount) { Say "  $name : the copy at the new place has $newCount of $oldCount files - keeping the original."; $bad++; continue }
            Remove-Item -LiteralPath $sm -Recurse -Force -ErrorAction SilentlyContinue
          }
        }
      }
      Note-Place 'OLLAMA_MODELS' $dst
      [Environment]::SetEnvironmentVariable('OLLAMA_MODELS', $m, 'User')
      $env:OLLAMA_MODELS = $m
      Say "  $name : stored at ($m). Ollama is told with the OLLAMA_MODELS setting (no link)."
      continue
    }
    if (Test-Path -LiteralPath $src) {
      $item = Get-Item -LiteralPath $src -Force
      if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        $t = $item.Target | Select-Object -First 1
        $same = $false
        try { $same = ($t -and ([IO.Path]::GetFullPath($t).TrimEnd('\') -ieq [IO.Path]::GetFullPath($dst).TrimEnd('\'))) } catch {}
        if ($same) {
          if (-not (Test-Path -LiteralPath $dst)) { New-Item -ItemType Directory -Path $dst -Force | Out-Null }
          Say "  $name : already at the new place (linked)."
          continue
        }
        if (-not ($t -and (Test-Path -LiteralPath $t))) {
          # the link points nowhere: just aim it at the new place
          New-Item -ItemType Directory -Path $dst -Force | Out-Null
          & cmd.exe /c rmdir "$src" | Out-Null
          try { New-Item -ItemType Junction -Path $src -Target $dst -ErrorAction Stop | Out-Null; Note-Place $src $dst; Say "  $name : the old link pointed nowhere; it now points to $dst." }
          catch { Say "  $name : could not make the link ($($_.Exception.Message))."; $bad++ }
          continue
        }
        # an earlier setup linked it to another folder: move the real program to the folder you chose now, then aim the link there
        $size = Dir-Size $t
        $free = (Get-PSDrive -Name $driveName).Free
        if ($free -lt ($size * 1.05 + 50MB)) { Say ("  $name : NOT moved - the new drive has only {0:N1} GB free and this needs {1:N1} GB." -f ($free / 1GB), ($size / 1GB)); $bad++; continue }
        Say ("  $name : was kept in $t ; moving {0:N1} GB to $dst ..." -f ($size / 1GB))
        New-Item -ItemType Directory -Path $dst -Force | Out-Null
        & robocopy.exe $t $dst /E /COPY:DAT /DCOPY:DAT /R:2 /W:2 /NFL /NDL /NJH /NJS /NP | Out-Null
        if ($LASTEXITCODE -ge 8) { Say "  $name : the copy did not finish (robocopy code $LASTEXITCODE). Left where it was."; $bad++; continue }
        $oldCount = (Get-ChildItem -LiteralPath $t -Recurse -Force -File -ErrorAction SilentlyContinue | Measure-Object).Count
        $newCount = (Get-ChildItem -LiteralPath $dst -Recurse -Force -File -ErrorAction SilentlyContinue | Measure-Object).Count
        if ($newCount -lt $oldCount) { Say "  $name : the copy at the new place has $newCount of $oldCount files - keeping it where it was."; $bad++; continue }
        & cmd.exe /c rmdir "$src" | Out-Null
        try { New-Item -ItemType Junction -Path $src -Target $dst -ErrorAction Stop | Out-Null }
        catch {
          Say "  $name : could not make the new link ($($_.Exception.Message)). Putting the old one back."
          try { New-Item -ItemType Junction -Path $src -Target $t -ErrorAction Stop | Out-Null } catch {}
          $bad++; continue
        }
        Note-Place $src $dst
        # the old folder is only renamed, never deleted: you can delete  "<name>.moved"  yourself once you have seen that everything works
        try { Rename-Item -LiteralPath $t -NewName ((Split-Path -Leaf $t) + '.moved') -ErrorAction Stop; Say "  $name : now at $dst . The old folder was renamed to $t.moved (you can delete it)." }
        catch { Say "  $name : now at $dst . The old folder $t is still there (it was in use); you can delete it later." }
        continue
      }
      $size = Dir-Size $src
      $free = (Get-PSDrive -Name $driveName).Free
      if ($free -lt ($size * 1.05 + 50MB)) {
        Say ("  $name : NOT moved - the new drive has only {0:N1} GB free and this needs {1:N1} GB." -f ($free / 1GB), ($size / 1GB))
        $bad++; continue
      }
      Say ("  $name : moving {0:N1} GB to $dst ..." -f ($size / 1GB))
      & robocopy.exe $src $dst /E /COPY:DAT /DCOPY:DAT /R:2 /W:2 /NFL /NDL /NJH /NJS /NP | Out-Null
      if ($LASTEXITCODE -ge 8) { Say "  $name : the copy did not finish (robocopy code $LASTEXITCODE). Left where it was."; $bad++; continue }
      $old = $src + '.moved'
      if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old -Recurse -Force -ErrorAction SilentlyContinue }
      try { Rename-Item -LiteralPath $src -NewName ((Split-Path -Leaf $src) + '.moved') -ErrorAction Stop }
      catch { Say "  $name : could not set the old folder aside ($($_.Exception.Message)). Close the program and run this again. Left where it was."; $bad++; continue }
      try { New-Item -ItemType Junction -Path $src -Target $dst -ErrorAction Stop | Out-Null }
      catch {
        Say "  $name : could not make the link ($($_.Exception.Message)). Putting it back."
        Rename-Item -LiteralPath $old -NewName (Split-Path -Leaf $src) -ErrorAction SilentlyContinue
        $bad++; continue
      }
      Note-Place $src $dst
      # only delete the old copy on C: when the copy on D: (seen through the link) has every file
      $oldCount = (Get-ChildItem -LiteralPath $old -Recurse -Force -File -ErrorAction SilentlyContinue | Measure-Object).Count
      $newCount = (Get-ChildItem -LiteralPath $src -Recurse -Force -File -ErrorAction SilentlyContinue | Measure-Object).Count
      if ($newCount -lt $oldCount) {
        Say "  $name : the copy at the new place has $newCount of $oldCount files - putting the original back and keeping it where it is."
        & cmd.exe /c rmdir "$src" | Out-Null
        Rename-Item -LiteralPath $old -NewName (Split-Path -Leaf $src) -ErrorAction SilentlyContinue
        $bad++; continue
      }
      Remove-Item -LiteralPath $old -Recurse -Force -ErrorAction SilentlyContinue
      if (Test-Path -LiteralPath $old) { Say "  $name : moved. (A few old files on C: were still in use; delete '$old' yourself later.)" }
      else { Say "  $name : moved to the new place and removed from the old one." }
    }
    else {
      # not installed yet: make the link now so the installer puts it on D: (Lite installs only need Python)
      if ($skipSet -contains $it.Key) { continue }
      New-Item -ItemType Directory -Path $dst -Force | Out-Null
      New-Item -ItemType Junction -Path $src -Target $dst -ErrorAction Stop | Out-Null
      Note-Place $src $dst
      Say "  $name : not installed yet - it will be installed in ($dst)."
    }
  }
  catch {
    Say "  $name : problem: $($_.Exception.Message)"
    $bad++
  }
}
if ($bad -gt 0) { Say "  $bad item(s) could not be moved; they stay where they were and still work."; exit 3 }
exit 0
