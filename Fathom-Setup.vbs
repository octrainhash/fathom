' Fathom Setup: double-click this file to open the Fathom setup wizard (a normal window).
' It only starts the wizard script that sits next to it, tools\wizard.ps1. Both files are plain text: open them in Notepad to read exactly what they do.
Option Explicit
Dim sh, fso, here, wiz
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
wiz = here & "\tools\wizard.ps1"
If Not fso.FileExists(wiz) Then wiz = here & "\fathom\tools\wizard.ps1"
If Not fso.FileExists(wiz) Then wiz = here & "\Fathom\tools\wizard.ps1"
If Not fso.FileExists(wiz) Then
  MsgBox "Fathom Setup cannot find its files next to this one." & vbCrLf & vbCrLf & "Please right-click the zip, choose Extract All, and open this file from the extracted Fathom folder.", 48, "Fathom Setup"
  WScript.Quit 1
End If
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & wiz & """", 0, False
