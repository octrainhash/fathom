// Fathom-Setup.exe: the one-file installer. It carries the whole Fathom download inside itself, unpacks it into a temporary
// folder and opens the setup window (the wizard: pick Full or Lite and ONE folder, then Install). Nothing else is done here.
// Build:  GOOS=windows GOARCH=amd64 go build -ldflags "-H=windowsgui -s -w" -o Fathom-Setup.exe   (fathom.zip must sit next to main.go)
package main

import (
	"archive/zip"
	"bytes"
	_ "embed"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"unsafe"
)

//go:embed fathom.zip
var payload []byte

func msg(text string) {
	u := syscall.NewLazyDLL("user32.dll").NewProc("MessageBoxW")
	t, _ := syscall.UTF16PtrFromString(text)
	c, _ := syscall.UTF16PtrFromString("Fathom Setup")
	u.Call(0, uintptr(unsafe.Pointer(t)), uintptr(unsafe.Pointer(c)), 0x40)
}

func unpack(dest string) error {
	r, err := zip.NewReader(bytes.NewReader(payload), int64(len(payload)))
	if err != nil {
		return err
	}
	for _, f := range r.File {
		name := filepath.FromSlash(f.Name)
		target := filepath.Join(dest, name)
		if !strings.HasPrefix(target, filepath.Clean(dest)+string(os.PathSeparator)) {
			continue // never write outside the folder
		}
		if f.FileInfo().IsDir() {
			os.MkdirAll(target, 0o755)
			continue
		}
		if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
			return err
		}
		in, err := f.Open()
		if err != nil {
			return err
		}
		out, err := os.Create(target)
		if err != nil {
			in.Close()
			return err
		}
		_, err = io.Copy(out, in)
		in.Close()
		out.Close()
		if err != nil {
			return err
		}
	}
	return nil
}

func main() {
	dest := filepath.Join(os.TempDir(), "FathomSetup")
	os.RemoveAll(dest)
	if err := os.MkdirAll(dest, 0o755); err != nil {
		msg("Could not make a temporary folder:\n" + err.Error())
		return
	}
	if err := unpack(dest); err != nil {
		msg("Could not unpack the installer:\n" + err.Error())
		return
	}
	wiz := filepath.Join(dest, "fathom", "tools", "wizard.ps1")
	if _, err := os.Stat(wiz); err != nil {
		msg("The installer is damaged (setup window script missing). Please download it again.")
		return
	}
	// -STA: Windows Forms needs it. The output is captured so that, if the window cannot open, the reason is shown instead of nothing.
	cmd := exec.Command("powershell.exe", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-File", wiz)
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: 0x08000000} // no black console window
	if self, e := os.Executable(); e == nil {
		cmd.Env = append(os.Environ(), "FATHOM_SETUP_EXE="+self) // the wizard copies this installer into the Fathom folder
	}
	var buf bytes.Buffer
	cmd.Stdout = &buf
	cmd.Stderr = &buf
	err := cmd.Run()
	text := strings.TrimSpace(buf.String())
	os.WriteFile(filepath.Join(dest, "launch.log"), []byte(text), 0o644)
	if err != nil || text != "" {
		if len(text) > 1500 {
			text = text[:1500]
		}
		if err != nil {
			text = err.Error() + "\n\n" + text
		}
		msg("The setup window did not open normally.\n\n" + text + "\n\n(Also saved in " + filepath.Join(dest, "launch.log") + ")")
	}
}
