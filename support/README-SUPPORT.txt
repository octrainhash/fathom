Fathom help scripts
===================
Double-click a numbered .cmd file in this folder if something is wrong. Each .cmd only starts the .ps1 file with the same number
(open both in Notepad to read exactly what they do). Each one saves a small text file with its result in your Downloads folder,
which you can send to whoever helps you. None of them deletes anything.

1-Check-Everything     Reads the state of Fathom and Ollama and asks the assistant a test question.   Saves Fathom-check.txt
2-Fix-Ollama           Fixes the Assistant saying "model not found" (a folder link on Ollama's model folder).
                       It removes only the small link (the models stay untouched), points Ollama at the real folder and tests it.
                       Asks for Windows permission once.                                              Saves Fathom-fix-ollama.txt
3-Scan-Leftovers       Lists every copy, link and leftover of Fathom on this PC. It only looks.        Saves Fathom-scan.txt
4-Update-From-Zip      Updates THIS Fathom from a newer fathom-final.zip or fathom.zip in Downloads.
                       Copies the new program files over this folder; your data and settings are not touched.   Saves Fathom-update.txt
5-Download-Fast-Model  Downloads the fast assistant model (qwen3-vl:4b-instruct, 3.3 GB), selects it, times an answer.   Saves Fathom-model.txt
6-Speed-Test           Times the assistant with Fathom's real instructions.                            Saves Fathom-speed.txt
7-Diagnose-Ollama      Collects Ollama's state and logs when it hides models.                           Saves Fathom-ollama-diagnosis.txt
8-Repair-Fathom        Runs Fathom's setup again (after an update, or if a part is missing). Windows asks once.
9-Open-Logs-Folder     Opens the folder with Fathom's logs and data.
10-Test-Voice          Tests Windows' own voice outside Fathom and plays a sentence (when you cannot hear the assistant).

Also in the Fathom folder: Fix-Ollama.cmd (the same as 2), Move-Fathom-to-D.cmd (move Fathom to another drive) and
Uninstall-Fathom.cmd (removes Fathom; asks before each part and never touches your own files).
These scripts find your Fathom folder by themselves, wherever you installed it.
