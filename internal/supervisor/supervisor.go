// Package supervisor runs and restarts Ailune's child processes.
package supervisor

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"os"
	"os/exec"
	"sync"
	"time"
)

// Spec describes one supervised process.
type Spec struct {
	Name         string
	Path         string
	Args         []string
	Dir          string
	Env          []string
	Restart      bool
	RestartDelay time.Duration
}

// Manager starts a fixed set of child processes.
type Manager struct {
	specs    []Spec
	logger   *slog.Logger
	onStatus func(name, status string)
	mu       sync.Mutex
	pids     map[string]int
	wg       sync.WaitGroup
}

// New creates a manager. onStatus may be nil.
func New(specs []Spec, logger *slog.Logger, onStatus func(name, status string)) *Manager {
	if logger == nil {
		logger = slog.Default()
	}
	return &Manager{
		specs:    specs,
		logger:   logger,
		onStatus: onStatus,
		pids:     make(map[string]int),
	}
}

func (m *Manager) status(name, status string) {
	if m.onStatus != nil {
		m.onStatus(name, status)
	}
}

// Start launches every spec and returns immediately.
func (m *Manager) Start(ctx context.Context) {
	for _, spec := range m.specs {
		m.wg.Add(1)
		go m.run(ctx, spec)
	}
}

// Wait blocks until all supervisors have exited.
func (m *Manager) Wait() { m.wg.Wait() }

// PIDs returns the currently running PIDs by service name.
func (m *Manager) PIDs() map[string]int {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := make(map[string]int, len(m.pids))
	for k, v := range m.pids {
		out[k] = v
	}
	return out
}

func (m *Manager) setPID(name string, pid int) {
	m.mu.Lock()
	if pid == 0 {
		delete(m.pids, name)
	} else {
		m.pids[name] = pid
	}
	m.mu.Unlock()
}

func (m *Manager) run(ctx context.Context, spec Spec) {
	defer m.wg.Done()
	delay := spec.RestartDelay
	if delay <= 0 {
		delay = time.Second
	}
	attempt := 0
	for {
		if ctx.Err() != nil {
			m.status(spec.Name, "stopped")
			return
		}
		attempt++
		err := m.execOnce(ctx, spec, attempt)
		if ctx.Err() != nil {
			m.status(spec.Name, "stopped")
			return
		}
		if !spec.Restart {
			if err != nil {
				m.status(spec.Name, "failed")
				m.logger.Error("service exited", "service", spec.Name, "err", err)
			} else {
				m.status(spec.Name, "stopped")
			}
			return
		}
		m.status(spec.Name, "backoff")
		m.logger.Warn("service exited; restarting", "service", spec.Name, "err", err, "delay", delay, "attempt", attempt)
		select {
		case <-ctx.Done():
			m.status(spec.Name, "stopped")
			return
		case <-time.After(delay):
		}
		if delay < 30*time.Second {
			delay *= 2
			if delay > 30*time.Second {
				delay = 30 * time.Second
			}
		}
	}
}

func (m *Manager) execOnce(ctx context.Context, spec Spec, attempt int) error {
	cmd := exec.Command(spec.Path, spec.Args...)
	cmd.Dir = spec.Dir
	cmd.Env = append(os.Environ(), spec.Env...)
	cmd.Stdout = &prefixWriter{name: spec.Name, w: os.Stderr}
	cmd.Stderr = &prefixWriter{name: spec.Name, w: os.Stderr}
	cmd.SysProcAttr = childProcAttr()
	m.status(spec.Name, "starting")
	if err := cmd.Start(); err != nil {
		return fmt.Errorf("start: %w", err)
	}
	m.setPID(spec.Name, cmd.Process.Pid)
	m.status(spec.Name, "running")
	m.logger.Info("service started", "service", spec.Name, "pid", cmd.Process.Pid, "attempt", attempt)

	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	var err error
	select {
	case err = <-done:
	case <-ctx.Done():
		terminate(cmd)
		select {
		case <-done:
		case <-time.After(4 * time.Second):
			_ = cmd.Process.Kill()
			<-done
		}
		err = ctx.Err()
	}
	m.setPID(spec.Name, 0)
	return err
}

// KillAll sends SIGTERM to every running child. It is used by the CLI on
// shutdown when the context has a short deadline.
func (m *Manager) KillAll() {
	m.mu.Lock()
	defer m.mu.Unlock()
	for name, pid := range m.pids {
		proc, err := os.FindProcess(pid)
		if err != nil {
			continue
		}
		_ = proc.Signal(os.Interrupt)
		m.logger.Info("sent interrupt", "service", name, "pid", pid)
	}
}

// prefixWriter prefixes each line written by a child process.
type prefixWriter struct {
	name string
	w    io.Writer
	mu   sync.Mutex
	buf  []byte
}

func (p *prefixWriter) Write(b []byte) (int, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.buf = append(p.buf, b...)
	for {
		i := indexByte(p.buf, '\n')
		if i < 0 {
			break
		}
		line := p.buf[:i+1]
		if _, err := fmt.Fprintf(p.w, "[%s] %s", p.name, line); err != nil {
			return len(b), err
		}
		p.buf = p.buf[i+1:]
	}
	if len(p.buf) > 64*1024 {
		// Avoid unbounded memory if a child never emits a newline.
		if _, err := fmt.Fprintf(p.w, "[%s] %s\n", p.name, p.buf); err != nil {
			return len(b), err
		}
		p.buf = nil
	}
	return len(b), nil
}

func indexByte(b []byte, c byte) int {
	for i := range b {
		if b[i] == c {
			return i
		}
	}
	return -1
}
