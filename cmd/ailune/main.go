// Command ailune is the launcher and control core for Ailune.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/ailune/ailune/internal/config"
	"github.com/ailune/ailune/internal/eventbus"
	"github.com/ailune/ailune/internal/httpapi"
	"github.com/ailune/ailune/internal/niri"
	"github.com/ailune/ailune/internal/paths"
	"github.com/ailune/ailune/internal/state"
	"github.com/ailune/ailune/internal/supervisor"
	"github.com/ailune/ailune/internal/version"
)

type coreRuntime struct {
	Addr      string    `json:"addr"`
	PID       int       `json:"pid"`
	Version   string    `json:"version"`
	StartedAt time.Time `json:"started_at"`
}

func main() {
	if err := runCLI(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, "ailune:", err)
		os.Exit(1)
	}
}

func runCLI(args []string) error {
	command := "run"
	if len(args) > 0 {
		command = args[0]
		args = args[1:]
	}
	_ = args
	switch command {
	case "help", "-h", "--help":
		usage()
		return nil
	case "version", "-v", "--version":
		fmt.Printf("ailune %s\n", version.Version)
		return nil
	case "run":
		return runStack(true, true)
	case "core":
		return runStack(false, false)
	case "ui":
		return runPythonModule("ailune.ui")
	case "service":
		return runPythonModule("ailune.service")
	case "pet":
		return runPythonModule("ailune.pet")
	case "open":
		return openUI()
	case "state":
		return printState()
	case "doctor":
		return doctor()
	default:
		usage()
		return fmt.Errorf("unknown command %q", command)
	}
}

func usage() {
	fmt.Print(`Ailune — customizable AI desktop companion

Usage:
  ailune run       Start the control core, AI service and pet shell
  ailune core      Start only the control core
  ailune ui        Open the settings and chat window
  ailune service   Run the AI service in the foreground
  ailune pet       Run the pet shell in the foreground
  ailune open      Ask a running core to open the UI
  ailune state     Print the current core state
  ailune doctor    Check dependencies and the Niri session
  ailune version   Print the version
`)
}

func runStack(startAI, startPet bool) error {
	logger := slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelInfo}))
	slog.SetDefault(logger)

	p, err := paths.Resolve()
	if err != nil {
		return err
	}
	if err := p.Ensure(); err != nil {
		return err
	}
	root, err := paths.ProjectRoot()
	if err != nil {
		return err
	}
	cfg, err := config.Load(p.ConfigFile)
	if err != nil {
		return err
	}
	token, err := p.LoadOrCreateToken()
	if err != nil {
		return err
	}
	signalCtx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	ctx, cancelRun := context.WithCancel(signalCtx)
	defer cancelRun()

	bus := eventbus.New()
	services := map[string]string{"core": "running"}
	if startAI {
		services["ai"] = "starting"
	}
	if startPet {
		services["pet"] = "starting"
	}
	manager := state.New(cfg, p.ConfigFile, bus, services)
	openUIFunc := func() error { return spawnUI(p, root, cfg, token, logger) }

	httpServer := httpapi.New(httpapi.Options{
		Addr:    cfg.Listen,
		Token:   token,
		State:   manager,
		Bus:     bus,
		Niri:    niri.New(),
		Paths:   p,
		Root:    root,
		OpenUI:  openUIFunc,
		Quit:    cancelRun,
		Logger:  logger,
		Version: version.Version,
	})
	listener, err := httpServer.Listen()
	if err != nil {
		return fmt.Errorf("start control server: %w", err)
	}
	runtimeFile := coreRuntime{Addr: listener.Addr().String(), PID: os.Getpid(), Version: version.Version, StartedAt: time.Now().UTC()}
	if err := writeRuntimeFile(p.CoreFile, runtimeFile); err != nil {
		logger.Warn("could not write runtime file", "err", err)
	}
	defer os.Remove(p.CoreFile)

	serverErr := make(chan error, 1)
	go func() { serverErr <- httpServer.Serve(listener) }()

	specs := make([]supervisor.Spec, 0, 2)
	if startAI {
		specs = append(specs, supervisor.Spec{
			Name:         "ai",
			Path:         paths.PythonExecutable(root),
			Args:         []string{"-m", "ailune.service"},
			Dir:          root,
			Env:          pythonEnv(root, p, cfg, token, "ai"),
			Restart:      true,
			RestartDelay: 2 * time.Second,
		})
	}
	if startPet {
		specs = append(specs, supervisor.Spec{
			Name:         "pet",
			Path:         paths.PythonExecutable(root),
			Args:         []string{"-m", "ailune.pet"},
			Dir:          root,
			Env:          pythonEnv(root, p, cfg, token, "pet"),
			Restart:      true,
			RestartDelay: 2 * time.Second,
		})
	}
	sup := supervisor.New(specs, logger, func(name, status string) {
		logger.Info("service status", "service", name, "status", status)
		manager.SetService(name, status)
	})
	sup.Start(ctx)

	logger.Info("Ailune core started", "version", version.Version, "root", root, "config", p.ConfigFile)
	if cfg.OpenUIOnStart {
		if err := openUIFunc(); err != nil {
			logger.Warn("could not open UI", "err", err)
		}
	}

	var runErr error
	select {
	case <-ctx.Done():
		logger.Info("shutdown requested")
	case err := <-serverErr:
		if err != nil {
			runErr = fmt.Errorf("control server: %w", err)
			cancelRun()
		}
	}

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 4*time.Second)
	defer cancel()
	_ = httpServer.Shutdown(shutdownCtx)
	sup.KillAll()
	waitDone := make(chan struct{})
	go func() { sup.Wait(); close(waitDone) }()
	select {
	case <-waitDone:
	case <-time.After(5 * time.Second):
		logger.Warn("timed out waiting for child processes")
	}
	bus.Close()
	return runErr
}

func pythonEnv(root string, p paths.Paths, cfg config.Config, token, role string) []string {
	env := map[string]string{
		"AILUNE_ROOT":        root,
		"AILUNE_CONFIG_DIR":  p.ConfigDir,
		"AILUNE_DATA_DIR":    p.DataDir,
		"AILUNE_RUNTIME_DIR": p.RuntimeDir,
		"AILUNE_CONFIG_FILE": p.ConfigFile,
		"AILUNE_TOKEN":       token,
		"AILUNE_CORE_URL":    "http://" + cfg.Listen,
		"AILUNE_AI_URL":      "http://" + cfg.AIServiceListen,
		"AILUNE_AI_LISTEN":   cfg.AIServiceListen,
		"AILUNE_ROLE":        role,
		"PYTHONUNBUFFERED":   "1",
		"PYTHONPATH":         prependPath(filepath.Join(root, "python"), os.Getenv("PYTHONPATH")),
	}
	return envWith(env)
}

func prependPath(first, rest string) string {
	if rest == "" {
		return first
	}
	return first + string(os.PathListSeparator) + rest
}

// envWith replaces keys in the inherited environment so duplicate entries are
// avoided (child processes see one value per key).
func envWith(overrides map[string]string) []string {
	env := make([]string, 0, len(os.Environ())+len(overrides))
	for _, item := range os.Environ() {
		key := item
		if i := strings.IndexByte(item, '='); i >= 0 {
			key = item[:i]
		}
		if _, replaced := overrides[key]; replaced {
			continue
		}
		env = append(env, item)
	}
	for key, value := range overrides {
		env = append(env, key+"="+value)
	}
	return env
}

func writeRuntimeFile(path string, rt coreRuntime) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	data, err := json.MarshalIndent(rt, "", "  ")
	if err != nil {
		return err
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, append(data, '\n'), 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

func readRuntimeFile(p paths.Paths) (coreRuntime, error) {
	var rt coreRuntime
	data, err := os.ReadFile(p.CoreFile)
	if err != nil {
		return rt, err
	}
	if err := json.Unmarshal(data, &rt); err != nil {
		return rt, err
	}
	if rt.Addr == "" {
		return rt, errors.New("runtime file has no address")
	}
	return rt, nil
}

func pythonCommand(root string, p paths.Paths, cfg config.Config, token, module string) *exec.Cmd {
	cmd := exec.Command(paths.PythonExecutable(root), "-m", module)
	cmd.Dir = root
	cmd.Env = pythonEnv(root, p, cfg, token, module)
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	return cmd
}

func runPythonModule(module string) error {
	p, err := paths.Resolve()
	if err != nil {
		return err
	}
	if err := p.Ensure(); err != nil {
		return err
	}
	root, err := paths.ProjectRoot()
	if err != nil {
		return err
	}
	cfg, err := config.Load(p.ConfigFile)
	if err != nil {
		return err
	}
	token, err := p.LoadOrCreateToken()
	if err != nil {
		return err
	}
	cmd := pythonCommand(root, p, cfg, token, module)
	if err := cmd.Run(); err != nil {
		var exitErr *exec.ExitError
		if errors.As(err, &exitErr) {
			return fmt.Errorf("%s exited with status %d", module, exitErr.ExitCode())
		}
		return err
	}
	return nil
}

func spawnUI(p paths.Paths, root string, cfg config.Config, token string, logger *slog.Logger) error {
	cmd := pythonCommand(root, p, cfg, token, "ailune.ui")
	cmd.Stdin = nil
	if err := cmd.Start(); err != nil {
		return err
	}
	logger.Info("opened UI", "pid", cmd.Process.Pid)
	go func() {
		if err := cmd.Wait(); err != nil {
			logger.Warn("UI exited", "err", err)
		}
	}()
	return nil
}

func openUI() error {
	p, err := paths.Resolve()
	if err != nil {
		return err
	}
	cfg, err := config.Load(p.ConfigFile)
	if err != nil {
		return err
	}
	addr := cfg.Listen
	if rt, err := readRuntimeFile(p); err == nil {
		addr = rt.Addr
	}
	token, err := p.LoadOrCreateToken()
	if err != nil {
		return err
	}
	req, err := http.NewRequest(http.MethodPost, "http://"+addr+"/api/v1/actions/open-ui", nil)
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+token)
	client := &http.Client{Timeout: 5 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("core is not running (start it with 'ailune run'): %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusAccepted {
		return fmt.Errorf("core returned %s", resp.Status)
	}
	fmt.Println("UI opened")
	return nil
}

func printState() error {
	p, _ := paths.Resolve()
	cfg, err := config.Load(p.ConfigFile)
	if err != nil {
		return err
	}
	addr := cfg.Listen
	if rt, err := readRuntimeFile(p); err == nil {
		addr = rt.Addr
	}
	token, err := p.LoadOrCreateToken()
	if err != nil {
		return err
	}
	req, err := http.NewRequest(http.MethodGet, "http://"+addr+"/api/v1/state", nil)
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+token)
	client := &http.Client{Timeout: 5 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("core is not running: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("core returned %s", resp.Status)
	}
	var value any
	if err := json.NewDecoder(resp.Body).Decode(&value); err != nil {
		return err
	}
	out, _ := json.MarshalIndent(value, "", "  ")
	fmt.Println(string(out))
	return nil
}
