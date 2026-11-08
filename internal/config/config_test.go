package config

import (
	"os"
	"path/filepath"
	"testing"
)

func TestDefaultIsValid(t *testing.T) {
	cfg := Default()
	if err := cfg.Validate(); err != nil {
		t.Fatalf("default config invalid: %v", err)
	}
	if cfg.Language != "en" {
		t.Fatalf("default language = %q, want en", cfg.Language)
	}
}

func TestSaveAndLoadRoundTrip(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "nested", "config.json")
	cfg := Default()
	cfg.Language = "zh_CN"
	cfg.Pet.Scale = 1.25
	cfg.ActiveCharacter = &Character{
		ID:         "char_1",
		Name:       "Aria",
		ModelPath:  "/models/Aria",
		ModelEntry: "Aria.model3.json",
		Scale:      1.1,
	}
	if err := Save(path, cfg); err != nil {
		t.Fatalf("Save: %v", err)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("mode = %o, want 600", info.Mode().Perm())
	}
	loaded, err := Load(path)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if loaded.Language != "zh_CN" || loaded.Pet.Scale != 1.25 {
		t.Fatalf("unexpected loaded config: %+v", loaded)
	}
	if loaded.ActiveCharacter == nil || loaded.ActiveCharacter.Name != "Aria" {
		t.Fatalf("character not round-tripped: %+v", loaded.ActiveCharacter)
	}
}

func TestLoadMissingReturnsDefaults(t *testing.T) {
	cfg, err := Load(filepath.Join(t.TempDir(), "missing.json"))
	if err != nil {
		t.Fatalf("Load missing: %v", err)
	}
	if cfg.Listen != "127.0.0.1:8766" {
		t.Fatalf("listen = %q", cfg.Listen)
	}
}

func TestValidateRejectsUnsafeValues(t *testing.T) {
	cases := []Config{
		func() Config { c := Default(); c.Listen = "0.0.0.0:8766"; return c }(),
		func() Config { c := Default(); c.AIServiceListen = "192.168.1.2:8765"; return c }(),
		func() Config { c := Default(); c.Language = "fr"; return c }(),
		func() Config { c := Default(); c.ActiveCharacter = &Character{ID: "", ModelPath: ""}; return c }(),
	}
	for i, cfg := range cases {
		if err := cfg.Validate(); err == nil {
			t.Errorf("case %d: expected validation error", i)
		}
	}
}

func TestNormalizeClampsScale(t *testing.T) {
	cfg := Default()
	cfg.Pet.Scale = 99
	cfg.Normalize()
	if cfg.Pet.Scale != 4 {
		t.Fatalf("scale = %v, want 4", cfg.Pet.Scale)
	}
	cfg.Pet.Scale = 0
	cfg.Normalize()
	if cfg.Pet.Scale != 1 {
		t.Fatalf("scale = %v, want 1", cfg.Pet.Scale)
	}
}
