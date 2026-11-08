// Package config defines Ailune's persisted runtime settings.
package config

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// Character is the subset of character metadata the runtime needs. The AI
// service owns the full record; the core persists only what the pet and API
// need in order to start without the service.
type Character struct {
	ID            string  `json:"id"`
	Name          string  `json:"name"`
	ModelPath     string  `json:"model_path"`
	ModelEntry    string  `json:"model_entry"`
	PersonalityID string  `json:"personality_id,omitempty"`
	Scale         float64 `json:"scale,omitempty"`
	ReplyLanguage string  `json:"reply_language,omitempty"`
}

// PetConfig controls the desktop layer surface.
type PetConfig struct {
	Visible      bool    `json:"visible"`
	X            int     `json:"x"` // logical screen coordinate; -1 lets the shell choose.
	Y            int     `json:"y"`
	Scale        float64 `json:"scale"`
	Output       string  `json:"output,omitempty"`
	ClickThrough bool    `json:"click_through"`
}

// Config is the on-disk configuration. Unknown fields written by newer
// versions are preserved by decoding into a raw map when saving is not needed;
// the fields below are the contract for this release.
type Config struct {
	Version         int        `json:"version"`
	Language        string     `json:"language"`
	Listen          string     `json:"listen"`
	AIServiceListen string     `json:"ai_service_listen"`
	ActiveCharacter *Character `json:"active_character"`
	Pet             PetConfig  `json:"pet"`
	OpenUIOnStart   bool       `json:"open_ui_on_start"`
}

const CurrentVersion = 1

// Default returns the first-run configuration. English is the product default.
func Default() Config {
	return Config{
		Version:         CurrentVersion,
		Language:        "en",
		Listen:          "127.0.0.1:8766",
		AIServiceListen: "127.0.0.1:8765",
		Pet: PetConfig{
			Visible: true,
			X:       -1,
			Y:       -1,
			Scale:   1.0,
		},
	}
}

func (c *Config) Normalize() {
	if c.Version == 0 {
		c.Version = CurrentVersion
	}
	if c.Listen == "" {
		c.Listen = "127.0.0.1:8766"
	}
	if c.AIServiceListen == "" {
		c.AIServiceListen = "127.0.0.1:8765"
	}
	if c.Language == "" {
		c.Language = "en"
	}
	if c.ActiveCharacter != nil && c.ActiveCharacter.Scale <= 0 {
		c.ActiveCharacter.Scale = 1.0
	}
	if c.Pet.Scale <= 0 {
		c.Pet.Scale = 1.0
	}
	if c.Pet.Scale > 4 {
		c.Pet.Scale = 4
	}
	if c.Pet.X < -1 {
		c.Pet.X = -1
	}
	if c.Pet.Y < -1 {
		c.Pet.Y = -1
	}
}

// Validate rejects unsafe or unusable values. It deliberately does not touch
// the filesystem.
func (c Config) Validate() error {
	var problems []string
	if c.Version != CurrentVersion {
		problems = append(problems, fmt.Sprintf("unsupported config version %d", c.Version))
	}
	if !isLoopbackListen(c.Listen) {
		problems = append(problems, "listen address must bind to loopback")
	}
	if !isLoopbackListen(c.AIServiceListen) {
		problems = append(problems, "ai_service_listen address must bind to loopback")
	}
	if c.Language != "en" && c.Language != "zh_CN" {
		problems = append(problems, "language must be en or zh_CN")
	}
	if c.ActiveCharacter != nil {
		if strings.TrimSpace(c.ActiveCharacter.ID) == "" {
			problems = append(problems, "active_character.id is required")
		}
		if strings.TrimSpace(c.ActiveCharacter.ModelPath) == "" {
			problems = append(problems, "active_character.model_path is required")
		}
	}
	if len(problems) > 0 {
		return errors.New(strings.Join(problems, "; "))
	}
	return nil
}

func isLoopbackListen(addr string) bool {
	host := addr
	if i := strings.LastIndex(addr, ":"); i >= 0 {
		host = addr[:i]
	}
	host = strings.Trim(host, "[]")
	switch host {
	case "127.0.0.1", "localhost", "::1":
		return true
	}
	return false
}

// Load reads a config file, applying defaults for missing fields. A missing
// file is not an error and yields the default configuration.
func Load(path string) (Config, error) {
	cfg := Default()
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return cfg, nil
	}
	if err != nil {
		return cfg, fmt.Errorf("read config: %w", err)
	}
	if len(data) == 0 {
		return cfg, nil
	}
	if err := json.Unmarshal(data, &cfg); err != nil {
		return cfg, fmt.Errorf("parse config %s: %w", path, err)
	}
	cfg.Normalize()
	if err := cfg.Validate(); err != nil {
		return cfg, err
	}
	return cfg, nil
}

// Save writes the configuration atomically with mode 0600.
func Save(path string, cfg Config) error {
	cfg.Normalize()
	if err := cfg.Validate(); err != nil {
		return err
	}
	data, err := json.MarshalIndent(cfg, "", "  ")
	if err != nil {
		return fmt.Errorf("encode config: %w", err)
	}
	data = append(data, '\n')
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return fmt.Errorf("create config dir: %w", err)
	}
	tmp, err := os.CreateTemp(dir, ".config-*.json")
	if err != nil {
		return fmt.Errorf("create temp config: %w", err)
	}
	tmpName := tmp.Name()
	defer os.Remove(tmpName)
	if err := tmp.Chmod(0o600); err != nil {
		tmp.Close()
		return err
	}
	if _, err := tmp.Write(data); err != nil {
		tmp.Close()
		return fmt.Errorf("write config: %w", err)
	}
	if err := tmp.Sync(); err != nil {
		tmp.Close()
		return fmt.Errorf("sync config: %w", err)
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if err := os.Rename(tmpName, path); err != nil {
		return fmt.Errorf("replace config: %w", err)
	}
	return nil
}
