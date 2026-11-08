// Package niri provides a small, optional wrapper around the niri IPC CLI.
//
// Ailune does not require niri to run: the pet window uses Wayland layer
// shell, which niri implements natively. The wrappers here are used for
// diagnostics and future workspace/display features.
package niri

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"time"
)

// Runner executes a command and returns stdout. It is injectable for tests.
type Runner func(ctx context.Context, name string, args ...string) ([]byte, error)

// Client talks to niri through its CLI.
type Client struct {
	path   string
	runner Runner
}

// New locates niri on PATH. A nil client is usable and reports unavailable.
func New() *Client {
	path, err := exec.LookPath("niri")
	if err != nil {
		return &Client{}
	}
	return &Client{path: path, runner: defaultRunner}
}

func defaultRunner(ctx context.Context, name string, args ...string) ([]byte, error) {
	cmd := exec.CommandContext(ctx, name, args...)
	cmd.Env = os.Environ()
	return cmd.Output()
}

// Available reports whether niri is on PATH and NIRI_SOCKET is set.
func (c *Client) Available() bool {
	return c != nil && c.path != "" && os.Getenv("NIRI_SOCKET") != ""
}

// Query runs `niri msg --json <args>` and returns decoded JSON.
func (c *Client) Query(ctx context.Context, args ...string) (any, error) {
	if !c.Available() {
		return nil, errors.New("niri is not available in this session")
	}
	ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	full := append([]string{"msg", "--json"}, args...)
	out, err := c.runner(ctx, c.path, full...)
	if err != nil {
		return nil, fmt.Errorf("niri %v: %w", args, err)
	}
	var value any
	if err := json.Unmarshal(out, &value); err != nil {
		return nil, fmt.Errorf("decode niri output: %w", err)
	}
	return value, nil
}

// Outputs returns connected outputs.
func (c *Client) Outputs(ctx context.Context) (any, error) { return c.Query(ctx, "outputs") }

// Workspaces returns workspaces.
func (c *Client) Workspaces(ctx context.Context) (any, error) { return c.Query(ctx, "workspaces") }

// Windows returns open windows.
func (c *Client) Windows(ctx context.Context) (any, error) { return c.Query(ctx, "windows") }

// Layers returns open layer-shell surfaces.
func (c *Client) Layers(ctx context.Context) (any, error) { return c.Query(ctx, "layers") }

// Version returns the running niri version string.
func (c *Client) Version(ctx context.Context) (string, error) {
	if !c.Available() {
		return "", errors.New("niri is not available in this session")
	}
	ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	out, err := c.runner(ctx, c.path, "msg", "version")
	if err != nil {
		return "", err
	}
	return string(out), nil
}

// Action runs `niri msg action ...`.
func (c *Client) Action(ctx context.Context, args ...string) error {
	if !c.Available() {
		return errors.New("niri is not available in this session")
	}
	ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	full := append([]string{"msg", "action"}, args...)
	_, err := c.runner(ctx, c.path, full...)
	return err
}
