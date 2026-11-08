package httpapi

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/ailune/ailune/internal/config"
	"github.com/ailune/ailune/internal/eventbus"
	"github.com/ailune/ailune/internal/paths"
	"github.com/ailune/ailune/internal/state"
)

const testToken = "test-token-0123456789abcdef0123456789abcdef"

type testServer struct {
	server  *httptest.Server
	state   *state.Manager
	bus     *eventbus.Bus
	openUI  chan struct{}
	quit    chan struct{}
	manager *state.Manager
}

func newTestServer(t *testing.T) *testServer {
	t.Helper()
	dir := t.TempDir()
	configPath := filepath.Join(dir, "config.json")
	bus := eventbus.New()
	openUI := make(chan struct{}, 1)
	quit := make(chan struct{}, 1)
	manager := state.New(config.Default(), configPath, bus, map[string]string{"core": "running"})
	srv := New(Options{
		Addr:    "127.0.0.1:0",
		Token:   testToken,
		State:   manager,
		Bus:     bus,
		Paths:   paths.Paths{ConfigDir: dir, DataDir: dir, RuntimeDir: dir, ConfigFile: configPath},
		Root:    dir,
		OpenUI:  func() error { openUI <- struct{}{}; return nil },
		Quit:    func() { quit <- struct{}{} },
		Version: "test",
	})
	ts := httptest.NewServer(srv.Handler())
	t.Cleanup(func() {
		ts.Close()
		bus.Close()
	})
	return &testServer{server: ts, state: manager, bus: bus, openUI: openUI, quit: quit, manager: manager}
}

func (ts *testServer) request(t *testing.T, method, path string, body any, auth bool) *http.Response {
	t.Helper()
	var reader io.Reader
	if body != nil {
		raw, err := json.Marshal(body)
		if err != nil {
			t.Fatal(err)
		}
		reader = bytes.NewReader(raw)
	}
	req, err := http.NewRequest(method, ts.server.URL+path, reader)
	if err != nil {
		t.Fatal(err)
	}
	if auth {
		req.Header.Set("Authorization", "Bearer "+testToken)
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := ts.server.Client().Do(req)
	if err != nil {
		t.Fatal(err)
	}
	return resp
}

func decode(t *testing.T, resp *http.Response) map[string]any {
	t.Helper()
	defer resp.Body.Close()
	var value map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&value); err != nil {
		t.Fatal(err)
	}
	return value
}

func TestAuthentication(t *testing.T) {
	ts := newTestServer(t)
	if resp := ts.request(t, "GET", "/api/v1/state", nil, false); resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("unauthorized state = %d", resp.StatusCode)
		resp.Body.Close()
	}
	if resp := ts.request(t, "GET", "/api/v1/state", nil, true); resp.StatusCode != http.StatusOK {
		t.Fatalf("authorized state = %d", resp.StatusCode)
		resp.Body.Close()
	}
	if resp := ts.request(t, "GET", "/api/v1/health", nil, false); resp.StatusCode != http.StatusOK {
		t.Fatalf("health = %d", resp.StatusCode)
		resp.Body.Close()
	}
	if resp := ts.request(t, "GET", "/api/v1/state", nil, true); resp.Header.Get("Cache-Control") != "no-store" {
		t.Fatalf("missing security header")
		resp.Body.Close()
	}
}

func TestPatchState(t *testing.T) {
	ts := newTestServer(t)
	root := t.TempDir()
	char := map[string]any{
		"id": "char_1", "name": "Aria", "model_path": root,
		"model_entry": "Aria.model3.json", "scale": 1.2,
	}
	resp := ts.request(t, "PATCH", "/api/v1/state", map[string]any{
		"active_character": char,
		"pet":              map[string]any{"x": 40, "y": 60, "scale": 1.5, "visible": true},
		"language":         "zh_CN",
	}, true)
	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		t.Fatalf("patch status = %d: %s", resp.StatusCode, body)
	}
	result := decode(t, resp)
	if result["language"] != "zh_CN" {
		t.Fatalf("language = %v", result["language"])
	}
	active := result["active_character"].(map[string]any)
	if active["name"] != "Aria" {
		t.Fatalf("active = %v", active)
	}
	pet := result["pet"].(map[string]any)
	if pet["x"].(float64) != 40 || pet["scale"].(float64) != 1.5 {
		t.Fatalf("pet = %v", pet)
	}
}

func TestPatchRejectsInvalid(t *testing.T) {
	ts := newTestServer(t)
	cases := []map[string]any{
		{"language": "fr"},
		{"pet": map[string]any{"scale": 0.1}},
		{"pet": map[string]any{"x": "not-a-number"}},
		{"active_character": map[string]any{"id": "", "model_path": "/tmp", "model_entry": "a.model3.json"}},
		{"active_character": map[string]any{"id": "c", "model_path": "relative", "model_entry": "a.model3.json"}},
		{"active_character": map[string]any{"id": "c", "model_path": "/tmp", "model_entry": "../a.model3.json"}},
	}
	for i, body := range cases {
		resp := ts.request(t, "PATCH", "/api/v1/state", body, true)
		if resp.StatusCode == http.StatusOK {
			t.Errorf("case %d unexpectedly accepted", i)
		}
		resp.Body.Close()
	}
}

func TestPetCommandAndActions(t *testing.T) {
	ts := newTestServer(t)
	resp := ts.request(t, "POST", "/api/v1/pet/commands", map[string]any{"type": "expression", "name": "happy"}, true)
	if resp.StatusCode != http.StatusAccepted {
		t.Fatalf("pet command = %d", resp.StatusCode)
	}
	resp.Body.Close()
	resp = ts.request(t, "POST", "/api/v1/actions/open-ui", nil, true)
	if resp.StatusCode != http.StatusAccepted {
		t.Fatalf("open-ui = %d", resp.StatusCode)
	}
	resp.Body.Close()
	select {
	case <-ts.openUI:
	case <-time.After(time.Second):
		t.Fatal("OpenUI callback not invoked")
	}
	resp = ts.request(t, "POST", "/api/v1/actions/quit", nil, true)
	if resp.StatusCode != http.StatusAccepted {
		t.Fatalf("quit = %d", resp.StatusCode)
	}
	resp.Body.Close()
	select {
	case <-ts.quit:
	case <-time.After(2 * time.Second):
		t.Fatal("Quit callback not invoked")
	}
}

func TestEventStream(t *testing.T) {
	ts := newTestServer(t)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, "GET", ts.server.URL+"/api/v1/events", nil)
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Authorization", "Bearer "+testToken)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("stream status = %d", resp.StatusCode)
	}
	reader := bufio.NewReader(resp.Body)
	eventType, data := readEvent(t, reader)
	if eventType != state.EventStateChanged {
		t.Fatalf("initial event = %q", eventType)
	}
	var snapshot map[string]any
	if err := json.Unmarshal([]byte(data), &snapshot); err != nil {
		t.Fatal(err)
	}
	if _, ok := snapshot["pet"]; !ok {
		t.Fatalf("initial snapshot missing pet: %v", snapshot)
	}

	if _, err := ts.state.Mutate(func(cfg *config.Config) error {
		cfg.Pet.X = 77
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	eventType, data = readEvent(t, reader)
	if eventType != state.EventStateChanged {
		t.Fatalf("second event = %q", eventType)
	}
	if !strings.Contains(data, `"x":77`) {
		t.Fatalf("state event missing update: %s", data)
	}
}

func readEvent(t *testing.T, reader *bufio.Reader) (string, string) {
	t.Helper()
	eventType := "message"
	var data strings.Builder
	for {
		line, err := reader.ReadString('\n')
		if err != nil {
			t.Fatalf("read event: %v", err)
		}
		line = strings.TrimRight(line, "\r\n")
		if line == "" {
			if data.Len() > 0 {
				return eventType, data.String()
			}
			continue
		}
		if strings.HasPrefix(line, "event:") {
			eventType = strings.TrimSpace(strings.TrimPrefix(line, "event:"))
		} else if strings.HasPrefix(line, "data:") {
			data.WriteString(strings.TrimPrefix(strings.TrimPrefix(line, "data:"), " "))
		}
	}
}
