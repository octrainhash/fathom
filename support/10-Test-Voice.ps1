# Tests Windows' own voice the same way Fathom does, and plays it. Writes Fathom-voice.txt in Downloads. Nothing is deleted.
. (Join-Path $PSScriptRoot '_common.ps1')
Start-Report 'Fathom-voice'
L ('Windows: ' + [Environment]::OSVersion.VersionString)
L ('PowerShell: ' + $PSVersionTable.PSVersion)
try { Add-Type -AssemblyName System.Speech -ErrorAction Stop; L 'System.Speech: loaded' } catch { L ('System.Speech: NOT available: ' + $_.Exception.Message); Finish-Report; exit }
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voices = @($s.GetInstalledVoices())
L ('Installed voices: ' + $voices.Count)
foreach ($v in $voices) { L ('  - ' + $v.VoiceInfo.Name + ' (' + $v.VoiceInfo.Culture + ')  enabled=' + $v.Enabled) }
if ($voices.Count -eq 0) { L 'No voice is installed. Open Windows Settings > Time & language > Speech, and add a voice or language.' }
$out = Join-Path $env:TEMP 'fathom-voice-test.wav'
try {
  $s.SetOutputToWaveFile($out); $s.Speak('Hello. This is the Fathom voice test. If you can hear me, the voice works.'); $s.Dispose()
  L ('Made a sound file: ' + $out + '  (' + (Get-Item $out).Length + ' bytes)')
} catch { L ('Could not make the sound file: ' + $_.Exception.Message); Finish-Report; exit }
try {
  L 'Playing it now. Turn your volume up and listen ...'
  $p = New-Object System.Media.SoundPlayer $out; $p.PlaySync()
  L 'Finished playing.'
} catch { L ('Could not play the sound: ' + $_.Exception.Message) }
try {
  $svc = Get-Service -Name Audiosrv -ErrorAction Stop
  L ('Windows Audio service: ' + $svc.Status)
} catch { L 'Windows Audio service: unknown' }
try {
  $dev = Get-CimInstance Win32_SoundDevice -ErrorAction Stop | Select-Object -ExpandProperty Name
  L ('Sound devices: ' + ($dev -join '; '))
} catch { L 'Sound devices: could not be listed' }
# ---- part 2: the same thing through Fathom's own engine (what the Test button uses), without the window
L ''
L '--- Part 2: Fathom''s own voice code ---'
$py = Join-Path $env:LOCALAPPDATA 'Fathom\venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $py)) { L ('Fathom''s Python was not found at ' + $py); Finish-Report; exit }
$code = @'
import os, sys, traceback
sys.path.insert(0, os.environ["FATHOM_APP"])
from pathlib import Path
try:
    from app.ai import media
    r = media.speak("Hello. This is Fathom's own voice code.", Path(os.environ["TEMP"]) / "fathom-engine-say", "", "en")
    print("RESULT_OK", r["path"], os.path.getsize(r["path"]))
except Exception:
    traceback.print_exc()
    print("RESULT_FAILED")
'@
$tmpPy = Join-Path $env:TEMP 'fathom-voice-test.py'
Set-Content -LiteralPath $tmpPy -Value $code -Encoding UTF8
$env:FATHOM_APP = $AppDir
$res = & $py $tmpPy 2>&1 | Out-String
L $res
$m = [regex]::Match($res, 'RESULT_OK (.+?) (\d+)')
if ($m.Success) {
  L 'Fathom''s engine made the sound file. Playing it ...'
  try { (New-Object System.Media.SoundPlayer $m.Groups[1].Value).PlaySync(); L 'Finished playing.' } catch { L ('Could not play: ' + $_.Exception.Message) }
} else { L 'Fathom''s engine could NOT make the voice. Send this report to Claude.' }

L ''
L 'Did you hear the sentence? Tell Claude: yes or no, and send the file named above.'
Finish-Report
