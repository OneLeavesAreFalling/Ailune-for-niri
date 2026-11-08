package main

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"github.com/ailune/ailune/internal/config"
	"github.com/ailune/ailune/internal/niri"
	"github.com/ailune/ailune/internal/paths"
	"github.com/ailune/ailune/internal/version"
)

const dependencyProbe = `
import importlib, sys
mods = ["PyQt6", "httpx", "fastapi", "uvicorn", "gi"]
missing = []
for m in mods:
    try:
        importlib.import_module(m)
    except Exception:
        missing.append(m)
print("python", sys.version.split()[0])
print("missing", ",".join(missing) if missing else "none")
try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
    print("gtk", f"{Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}")
except Exception as e:
    print("gtk", "error:", e)
try:
    import gi
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gtk4LayerShell
    print("gtk4-layer-shell", "ok")
except Exception as e:
    print("gtk4-layer-shell", "error:", e)
try:
    import gi
    gi.require_version("WebKit", "6.0")
    from gi.repository import WebKit
    print("webkitgtk6", "ok")
except Exception as e:
    print("webkitgtk6", "error:", e)
`

func doctor() error {
	fmt.Printf("Ailune %s\n\n", version.Version)
	p, err := paths.Resolve()
	if err != nil {
		return err
	}
	fmt.Println("Paths")
	fmt.Printf("  config   %s\n", p.ConfigFile)
	fmt.Printf("  data     %s\n", p.DataDir)
	fmt.Printf("  runtime  %s\n", p.RuntimeDir)
	fmt.Printf("  token    %s\n", p.TokenFile)
	if info, err := os.Stat(p.TokenFile); err == nil {
		fmt.Printf("  token mode %s\n", info.Mode().Perm())
	} else {
		fmt.Println("  token not created yet")
	}

	root, rootErr := paths.ProjectRoot()
	if rootErr != nil {
		fmt.Printf("\nProject checkout: NOT FOUND (%v)\n", rootErr)
	} else {
		fmt.Printf("\nProject checkout: %s\n", root)
		renderer := filepath.Join(root, "renderer", "index.html")
		if _, err := os.Stat(renderer); err == nil {
			fmt.Printf("  renderer %s\n", renderer)
		} else {
			fmt.Printf("  renderer MISSING %s\n", renderer)
		}
	}

	cfg, err := config.Load(p.ConfigFile)
	if err != nil {
		fmt.Printf("\nConfig: INVALID (%v)\n", err)
	} else {
		fmt.Printf("\nConfig: %s (language=%s core=%s ai=%s)\n", p.ConfigFile, cfg.Language, cfg.Listen, cfg.AIServiceListen)
	}

	fmt.Println("\nNiri")
	n := niri.New()
	if !n.Available() {
		fmt.Println("  not available (NIRI_SOCKET unset or niri not on PATH)")
	} else {
		ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		defer cancel()
		if v, err := n.Version(ctx); err == nil {
			fmt.Printf("  version %s", ensureNewline(v))
		} else {
			fmt.Printf("  error: %v\n", err)
		}
		if layers, err := n.Layers(ctx); err == nil {
			fmt.Printf("  layer surfaces: %v\n", summarizeLayers(layers))
		}
	}

	fmt.Println("\nPython / GUI")
	if rootErr != nil {
		fmt.Println("  skipped: checkout not found")
		return nil
	}
	py := paths.PythonExecutable(root)
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, py, "-c", dependencyProbe)
	cmd.Dir = root
	cmd.Env = append(os.Environ(), "PYTHONPATH="+filepath.Join(root, "python"))
	var out bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = &out
	probeErr := cmd.Run()
	for _, line := range strings.Split(strings.TrimSpace(out.String()), "\n") {
		if strings.TrimSpace(line) != "" {
			fmt.Printf("  %s\n", line)
		}
	}
	if probeErr != nil {
		fmt.Printf("  probe failed: %v\n", probeErr)
	}

	fmt.Println("\nLayer shell note")
	fmt.Println("  PyGObject loads libwayland before gtk4-layer-shell; the pet launcher")
	fmt.Println("  preloads libgtk4-layer-shell.so automatically. See docs/NIRI.md.")
	if probeErr != nil {
		return fmt.Errorf("Python environment is incomplete; run ./scripts/setup.sh")
	}
	return nil
}

func ensureNewline(s string) string {
	if strings.HasSuffix(s, "\n") {
		return s
	}
	return s + "\n"
}

func summarizeLayers(value any) []string {
	list, ok := value.([]any)
	if !ok {
		return nil
	}
	out := make([]string, 0, len(list))
	for _, item := range list {
		m, ok := item.(map[string]any)
		if !ok {
			continue
		}
		ns, _ := m["namespace"].(string)
		layer, _ := m["layer"].(string)
		if ns != "" {
			out = append(out, ns+"("+layer+")")
		}
	}
	return out
}
