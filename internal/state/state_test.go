package state

import (
	"path/filepath"
	"testing"
	"time"

	"github.com/ailune/ailune/internal/config"
	"github.com/ailune/ailune/internal/eventbus"
)

func newManager(t *testing.T) (*Manager, *eventbus.Bus, string) {
	t.Helper()
	path := filepath.Join(t.TempDir(), "config.json")
	bus := eventbus.New()
	manager := New(config.Default(), path, bus, map[string]string{"core": "running"})
	return manager, bus, path
}

func TestSnapshotAndService(t *testing.T) {
	manager, _, _ := newManager(t)
	snap := manager.Snapshot()
	if snap.Services["core"] != "running" {
		t.Fatalf("services = %+v", snap.Services)
	}
	manager.SetService("ai", "online")
	if got := manager.Snapshot().Services["ai"]; got != "online" {
		t.Fatalf("ai status = %q", got)
	}
}

func TestMutatePersistsAndPublishes(t *testing.T) {
	manager, bus, path := newManager(t)
	events, unsubscribe := bus.Subscribe(4)
	defer unsubscribe()

	snap, err := manager.Mutate(func(cfg *config.Config) error {
		cfg.Language = "zh_CN"
		cfg.Pet.X = 12
		cfg.Pet.Y = 30
		cfg.ActiveCharacter = &config.Character{
			ID:         "char_1",
			Name:       "Aria",
			ModelPath:  "/models/Aria",
			ModelEntry: "Aria.model3.json",
		}
		return nil
	})
	if err != nil {
		t.Fatalf("Mutate: %v", err)
	}
	if snap.Language != "zh_CN" || snap.ActiveCharacter == nil {
		t.Fatalf("unexpected snapshot: %+v", snap)
	}
	select {
	case event := <-events:
		if event.Type != EventStateChanged {
			t.Fatalf("event type = %q", event.Type)
		}
	case <-time.After(time.Second):
		t.Fatal("no state event")
	}
	loaded, err := config.Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if loaded.Pet.X != 12 || loaded.Language != "zh_CN" {
		t.Fatalf("not persisted: %+v", loaded)
	}
}

func TestMutateRejectsInvalidAndKeepsState(t *testing.T) {
	manager, _, _ := newManager(t)
	_, err := manager.Mutate(func(cfg *config.Config) error {
		cfg.Listen = "0.0.0.0:1"
		return nil
	})
	if err == nil {
		t.Fatal("expected validation error")
	}
	if got := manager.Snapshot().Pet.Scale; got != 1 {
		t.Fatalf("state changed after failed mutation: %v", got)
	}
}
