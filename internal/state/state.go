// Package state owns the authoritative runtime snapshot shared by the API,
// the event stream and the supervised processes.
package state

import (
	"fmt"
	"sync"
	"time"

	"github.com/ailune/ailune/internal/config"
	"github.com/ailune/ailune/internal/eventbus"
)

// Event types published by the core.
const (
	EventStateChanged  = "state.changed"
	EventServiceStatus = "service.status"
	EventPetCommand    = "pet.command"
	EventNotice        = "app.notice"
)

// Snapshot is the JSON representation returned by GET /api/v1/state.
type Snapshot struct {
	Version         int               `json:"version"`
	StartedAt       time.Time         `json:"started_at"`
	Language        string            `json:"language"`
	ActiveCharacter *config.Character `json:"active_character"`
	Pet             config.PetConfig  `json:"pet"`
	Services        map[string]string `json:"services"`
}

// Manager serialises changes to the persisted configuration.
type Manager struct {
	mu         sync.RWMutex
	cfg        config.Config
	configPath string
	started    time.Time
	services   map[string]string
	bus        *eventbus.Bus
}

// New creates a manager. services is copied.
func New(cfg config.Config, configPath string, bus *eventbus.Bus, services map[string]string) *Manager {
	cfg.Normalize()
	copied := make(map[string]string, len(services))
	for k, v := range services {
		copied[k] = v
	}
	return &Manager{
		cfg:        cfg,
		configPath: configPath,
		started:    time.Now().UTC(),
		services:   copied,
		bus:        bus,
	}
}

// Snapshot returns a deep copy safe for concurrent readers.
func (m *Manager) Snapshot() Snapshot {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.snapshotLocked()
}

func (m *Manager) snapshotLocked() Snapshot {
	snap := Snapshot{
		Version:   1,
		StartedAt: m.started,
		Language:  m.cfg.Language,
		Pet:       m.cfg.Pet,
		Services:  make(map[string]string, len(m.services)),
	}
	for k, v := range m.services {
		snap.Services[k] = v
	}
	if m.cfg.ActiveCharacter != nil {
		char := *m.cfg.ActiveCharacter
		snap.ActiveCharacter = &char
	}
	return snap
}

// Config returns a copy of the current configuration.
func (m *Manager) Config() config.Config {
	m.mu.RLock()
	defer m.mu.RUnlock()
	cfg := m.cfg
	if cfg.ActiveCharacter != nil {
		char := *cfg.ActiveCharacter
		cfg.ActiveCharacter = &char
	}
	return cfg
}

// Mutate applies fn to a copy, validates and persists it, then publishes a
// state.changed event. The callback must not block.
func (m *Manager) Mutate(fn func(*config.Config) error) (Snapshot, error) {
	m.mu.Lock()
	next := m.cfg
	if next.ActiveCharacter != nil {
		char := *next.ActiveCharacter
		next.ActiveCharacter = &char
	}
	if err := fn(&next); err != nil {
		m.mu.Unlock()
		return Snapshot{}, err
	}
	next.Normalize()
	if err := next.Validate(); err != nil {
		m.mu.Unlock()
		return Snapshot{}, err
	}
	if err := config.Save(m.configPath, next); err != nil {
		m.mu.Unlock()
		return Snapshot{}, fmt.Errorf("persist state: %w", err)
	}
	m.cfg = next
	snap := m.snapshotLocked()
	m.mu.Unlock()

	if m.bus != nil {
		m.bus.Publish(EventStateChanged, snap)
	}
	return snap, nil
}

// SetService records a supervised process status and broadcasts it.
func (m *Manager) SetService(name, status string) Snapshot {
	m.mu.Lock()
	m.services[name] = status
	snap := m.snapshotLocked()
	m.mu.Unlock()
	if m.bus != nil {
		m.bus.Publish(EventServiceStatus, map[string]any{
			"service": name,
			"status":  status,
			"state":   snap,
		})
		m.bus.Publish(EventStateChanged, snap)
	}
	return snap
}
