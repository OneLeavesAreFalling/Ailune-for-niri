// Package paths resolves Ailune's XDG directories and small runtime files.
package paths

import (
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

const appName = "ailune"

// Paths groups every filesystem location used by the core.
type Paths struct {
	ConfigDir  string
	DataDir    string
	RuntimeDir string
	CacheDir   string
	ConfigFile string
	TokenFile  string
	CoreFile   string
}

func envDir(name, fallback string) string {
	if v := os.Getenv(name); v != "" {
		return v
	}
	return fallback
}

func homeDir() (string, error) {
	if h := os.Getenv("HOME"); h != "" {
		return h, nil
	}
	return os.UserHomeDir()
}

// Resolve returns the standard XDG locations for Ailune.
//
// AILUNE_CONFIG_DIR, AILUNE_DATA_DIR, AILUNE_RUNTIME_DIR and
// AILUNE_CONFIG_FILE are honoured for development and testing.
func Resolve() (Paths, error) {
	home, err := homeDir()
	if err != nil {
		return Paths{}, fmt.Errorf("resolve home directory: %w", err)
	}
	configHome := envDir("XDG_CONFIG_HOME", filepath.Join(home, ".config"))
	dataHome := envDir("XDG_DATA_HOME", filepath.Join(home, ".local", "share"))
	cacheHome := envDir("XDG_CACHE_HOME", filepath.Join(home, ".cache"))

	configDir := envDir("AILUNE_CONFIG_DIR", filepath.Join(configHome, appName))
	dataDir := envDir("AILUNE_DATA_DIR", filepath.Join(dataHome, appName))
	runtimeDir := os.Getenv("AILUNE_RUNTIME_DIR")
	if runtimeDir == "" {
		if xdg := os.Getenv("XDG_RUNTIME_DIR"); xdg != "" {
			runtimeDir = filepath.Join(xdg, appName)
		} else {
			runtimeDir = filepath.Join(os.TempDir(), fmt.Sprintf("%s-%d", appName, os.Getuid()))
		}
	}
	cacheDir := envDir("AILUNE_CACHE_DIR", filepath.Join(cacheHome, appName))

	configFile := envDir("AILUNE_CONFIG_FILE", filepath.Join(configDir, "config.json"))
	return Paths{
		ConfigDir:  configDir,
		DataDir:    dataDir,
		RuntimeDir: runtimeDir,
		CacheDir:   cacheDir,
		ConfigFile: configFile,
		TokenFile:  filepath.Join(configDir, "api-token"),
		CoreFile:   filepath.Join(runtimeDir, "core.json"),
	}, nil
}

// Ensure creates the writable directories with user-only permissions.
func (p Paths) Ensure() error {
	for _, dir := range []string{p.ConfigDir, p.DataDir, p.RuntimeDir, p.CacheDir} {
		if err := os.MkdirAll(dir, 0o700); err != nil {
			return fmt.Errorf("create %s: %w", dir, err)
		}
	}
	return nil
}

// LoadOrCreateToken returns the shared local API token, creating it on first
// use. The token is stored with mode 0600 and never logged.
func (p Paths) LoadOrCreateToken() (string, error) {
	if data, err := os.ReadFile(p.TokenFile); err == nil {
		token := strings.TrimSpace(string(data))
		if len(token) >= 32 {
			return token, nil
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return "", fmt.Errorf("read token: %w", err)
	}
	buf := make([]byte, 32)
	if _, err := rand.Read(buf); err != nil {
		return "", fmt.Errorf("generate token: %w", err)
	}
	token := hex.EncodeToString(buf)
	if err := os.MkdirAll(filepath.Dir(p.TokenFile), 0o700); err != nil {
		return "", err
	}
	if err := os.WriteFile(p.TokenFile, []byte(token+"\n"), 0o600); err != nil {
		return "", fmt.Errorf("write token: %w", err)
	}
	if err := os.Chmod(p.TokenFile, 0o600); err != nil {
		return "", fmt.Errorf("chmod token: %w", err)
	}
	return token, nil
}

// ProjectRoot locates the checkout that contains the Python package and the
// Web renderer. AILUNE_ROOT always wins; otherwise the current working
// directory and its parents are searched, then the executable directory.
func ProjectRoot() (string, error) {
	if root := os.Getenv("AILUNE_ROOT"); root != "" {
		if isProjectRoot(root) {
			return filepath.Abs(root)
		}
		return "", fmt.Errorf("AILUNE_ROOT=%q is not an Ailune checkout", root)
	}
	if cwd, err := os.Getwd(); err == nil {
		if root := searchUp(cwd); root != "" {
			return root, nil
		}
	}
	if exe, err := os.Executable(); err == nil {
		if root := searchUp(filepath.Dir(exe)); root != "" {
			return root, nil
		}
	}
	return "", errors.New("cannot locate the Ailune checkout; set AILUNE_ROOT")
}

func searchUp(start string) string {
	dir := start
	for {
		if isProjectRoot(dir) {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return ""
		}
		dir = parent
	}
}

func isProjectRoot(dir string) bool {
	_, errPy := os.Stat(filepath.Join(dir, "python", "pyproject.toml"))
	_, errRenderer := os.Stat(filepath.Join(dir, "renderer", "index.html"))
	return errPy == nil && errRenderer == nil
}

// PythonExecutable picks the virtualenv interpreter when present, falling back
// to AILUNE_PYTHON and then python3 on PATH.
func PythonExecutable(root string) string {
	if v := os.Getenv("AILUNE_PYTHON"); v != "" {
		return v
	}
	for _, candidate := range []string{
		filepath.Join(root, ".venv", "bin", "python"),
		filepath.Join(root, "venv", "bin", "python"),
	} {
		if info, err := os.Stat(candidate); err == nil && !info.IsDir() {
			return candidate
		}
	}
	if p, err := exec.LookPath("python3"); err == nil {
		return p
	}
	return "python3"
}
