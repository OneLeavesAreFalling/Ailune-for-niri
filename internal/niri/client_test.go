package niri

import (
	"context"
	"errors"
	"testing"
)

func TestQueryDecodesJSON(t *testing.T) {
	t.Setenv("NIRI_SOCKET", "/tmp/niri.sock")
	var called []string
	client := &Client{
		path: "/usr/bin/niri",
		runner: func(_ context.Context, name string, args ...string) ([]byte, error) {
			called = append(called, name+" "+args[0]+" "+args[1])
			return []byte(`{"eDP-1":{"name":"eDP-1"}}`), nil
		},
	}
	value, err := client.Outputs(context.Background())
	if err != nil {
		t.Fatalf("Outputs: %v", err)
	}
	m, ok := value.(map[string]any)
	if !ok || m["eDP-1"] == nil {
		t.Fatalf("unexpected value: %#v", value)
	}
	if len(called) != 1 || called[0] != "/usr/bin/niri msg --json" {
		t.Fatalf("called = %#v", called)
	}
}

func TestUnavailableWithoutSocket(t *testing.T) {
	t.Setenv("NIRI_SOCKET", "")
	client := &Client{path: "/usr/bin/niri", runner: func(context.Context, string, ...string) ([]byte, error) {
		return nil, errors.New("should not run")
	}}
	if client.Available() {
		t.Fatal("expected unavailable")
	}
	if _, err := client.Outputs(context.Background()); err == nil {
		t.Fatal("expected error")
	}
}

func TestActionArguments(t *testing.T) {
	t.Setenv("NIRI_SOCKET", "/tmp/niri.sock")
	var got []string
	client := &Client{
		path: "niri",
		runner: func(_ context.Context, _ string, args ...string) ([]byte, error) {
			got = args
			return nil, nil
		},
	}
	if err := client.Action(context.Background(), "focus-window", "--id", "12"); err != nil {
		t.Fatal(err)
	}
	want := []string{"msg", "action", "focus-window", "--id", "12"}
	if len(got) != len(want) {
		t.Fatalf("args = %#v", got)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("args = %#v, want %#v", got, want)
		}
	}
}
