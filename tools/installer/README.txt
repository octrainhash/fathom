Fathom-Setup.exe is the one-file installer (the setup wizard) for GitHub Releases and the website.
It carries fathom.zip inside itself, unpacks it to a temporary folder and opens the setup window.
To rebuild it (needs Go): copy the finished fathom.zip into this folder, then run
  GOOS=windows GOARCH=amd64 go build -ldflags "-H=windowsgui -s -w" -o Fathom-Setup.exe
Rebuild it whenever fathom.zip changes. The exe is not code-signed, so Windows SmartScreen may say "unknown publisher": click More info > Run anyway.
