// Package httpapi exposes the authenticated local control plane.
package httpapi

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/ailune/ailune/internal/config"
	"github.com/ailune/ailune/internal/eventbus"
	"github.com/ailune/ailune/internal/niri"
	"github.com/ailune/ailune/internal/paths"
	"github.com/ailune/ailune/internal/state"
	"github.com/ailune/ailune/internal/version"
)

// Options configure the HTTP server.
type Options struct {
	Addr    string
	Token   string
	State   *state.Manager
	Bus     *eventbus.Bus
	Niri    *niri.Client
	Paths   paths.Paths
	Root    string
	OpenUI  func() error
	Quit    func()
	Logger  *slog.Logger
	Version string
}

// Server is the local control plane.
type Server struct {
	opts Options
	http *http.Server
}

// New builds a server. The caller must run ListenAndServe.
func New(opts Options) *Server {
	if opts.Logger == nil {
		opts.Logger = slog.Default()
	}
	if opts.Version == "" {
		opts.Version = version.Version
	}
	s := &Server{opts: opts}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /api/v1/health", s.handleHealth)
	mux.HandleFunc("GET /api/v1/state", s.auth(s.handleGetState))
	mux.HandleFunc("PATCH /api/v1/state", s.auth(s.handlePatchState))
	mux.HandleFunc("GET /api/v1/events", s.auth(s.handleEvents))
	mux.HandleFunc("GET /api/v1/info", s.auth(s.handleInfo))
	mux.HandleFunc("POST /api/v1/pet/commands", s.auth(s.handlePetCommand))
	mux.HandleFunc("POST /api/v1/actions/open-ui", s.auth(s.handleOpenUI))
	mux.HandleFunc("POST /api/v1/actions/quit", s.auth(s.handleQuit))
	mux.HandleFunc("GET /", s.handleRoot)
	s.http = &http.Server{
		Addr:              opts.Addr,
		Handler:           securityHeaders(mux),
		ReadHeaderTimeout: 5 * time.Second,
		IdleTimeout:       120 * time.Second,
		MaxHeaderBytes:    16 << 10,
	}
	return s
}

// Handler returns the HTTP handler (useful for tests).
func (s *Server) Handler() http.Handler { return s.http.Handler }

// Listen binds the control socket after verifying it is loopback-only.
func (s *Server) Listen() (net.Listener, error) {
	if !isLoopbackAddr(s.opts.Addr) {
		return nil, fmt.Errorf("refusing to listen on non-loopback address %q", s.opts.Addr)
	}
	ln, err := net.Listen("tcp", s.opts.Addr)
	if err != nil {
		return nil, err
	}
	s.opts.Logger.Info("control API listening", "addr", ln.Addr().String())
	return ln, nil
}

// Serve blocks until the server stops. Call Shutdown to stop it.
func (s *Server) Serve(ln net.Listener) error {
	err := s.http.Serve(ln)
	if errors.Is(err, http.ErrServerClosed) {
		return nil
	}
	return err
}

// ListenAndServe is a convenience wrapper around Listen and Serve.
func (s *Server) ListenAndServe() error {
	ln, err := s.Listen()
	if err != nil {
		return err
	}
	return s.Serve(ln)
}

// Shutdown gracefully stops the server.
func (s *Server) Shutdown(ctx context.Context) error {
	return s.http.Shutdown(ctx)
}

func isLoopbackAddr(addr string) bool {
	host, _, err := net.SplitHostPort(addr)
	if err != nil {
		return false
	}
	if host == "localhost" {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

func securityHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("Cache-Control", "no-store")
		next.ServeHTTP(w, r)
	})
}

func (s *Server) auth(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		header := r.Header.Get("Authorization")
		const prefix = "Bearer "
		if !strings.HasPrefix(header, prefix) {
			writeError(w, http.StatusUnauthorized, "unauthorized", "missing bearer token")
			return
		}
		got := strings.TrimSpace(strings.TrimPrefix(header, prefix))
		if s.opts.Token == "" || subtle.ConstantTimeCompare([]byte(got), []byte(s.opts.Token)) != 1 {
			writeError(w, http.StatusUnauthorized, "unauthorized", "invalid token")
			return
		}
		next(w, r)
	}
}

func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{"ok": true, "version": s.opts.Version})
}

func (s *Server) handleRoot(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/" {
		http.NotFound(w, r)
		return
	}
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	fmt.Fprintf(w, "Ailune core %s\n", s.opts.Version)
}

func (s *Server) handleGetState(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, s.opts.State.Snapshot())
}

type statePatch struct {
	ActiveCharacter json.RawMessage `json:"active_character"`
	Pet             *petPatch       `json:"pet"`
	Language        *string         `json:"language"`
}

type petPatch struct {
	Visible      *bool    `json:"visible"`
	X            *int     `json:"x"`
	Y            *int     `json:"y"`
	Scale        *float64 `json:"scale"`
	Output       *string  `json:"output"`
	ClickThrough *bool    `json:"click_through"`
}

func (s *Server) handlePatchState(w http.ResponseWriter, r *http.Request) {
	var patch statePatch
	dec := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&patch); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body: "+err.Error())
		return
	}
	snap, err := s.opts.State.Mutate(func(cfg *config.Config) error {
		if patch.Pet != nil {
			if err := applyPetPatch(&cfg.Pet, patch.Pet); err != nil {
				return err
			}
		}
		if patch.Language != nil {
			if *patch.Language != "en" && *patch.Language != "zh_CN" {
				return errors.New("language must be en or zh_CN")
			}
			cfg.Language = *patch.Language
		}
		if len(patch.ActiveCharacter) > 0 {
			if string(patch.ActiveCharacter) == "null" {
				cfg.ActiveCharacter = nil
			} else {
				var char config.Character
				if err := json.Unmarshal(patch.ActiveCharacter, &char); err != nil {
					return fmt.Errorf("invalid active_character: %w", err)
				}
				if err := validateCharacter(&char); err != nil {
					return err
				}
				cfg.ActiveCharacter = &char
			}
		}
		return nil
	})
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid_state", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, snap)
}

func applyPetPatch(pet *config.PetConfig, patch *petPatch) error {
	if patch.Visible != nil {
		pet.Visible = *patch.Visible
	}
	if patch.X != nil {
		pet.X = *patch.X
	}
	if patch.Y != nil {
		pet.Y = *patch.Y
	}
	if patch.Scale != nil {
		if *patch.Scale < 0.25 || *patch.Scale > 4 {
			return errors.New("pet.scale must be between 0.25 and 4")
		}
		pet.Scale = *patch.Scale
	}
	if patch.Output != nil {
		pet.Output = strings.TrimSpace(*patch.Output)
	}
	if patch.ClickThrough != nil {
		pet.ClickThrough = *patch.ClickThrough
	}
	return nil
}

func validateCharacter(char *config.Character) error {
	char.ID = strings.TrimSpace(char.ID)
	char.Name = strings.TrimSpace(char.Name)
	char.ModelPath = filepath.Clean(char.ModelPath)
	char.ModelEntry = filepath.Clean(char.ModelEntry)
	if char.ID == "" {
		return errors.New("active_character.id is required")
	}
	if char.Name == "" {
		char.Name = char.ID
	}
	if !filepath.IsAbs(char.ModelPath) {
		return errors.New("active_character.model_path must be absolute")
	}
	if char.ModelEntry == "" || char.ModelEntry == "." {
		return errors.New("active_character.model_entry is required")
	}
	if filepath.IsAbs(char.ModelEntry) {
		rel, err := filepath.Rel(char.ModelPath, char.ModelEntry)
		if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
			return errors.New("active_character.model_entry must be inside model_path")
		}
		char.ModelEntry = rel
	}
	if char.ModelEntry == ".." || strings.HasPrefix(char.ModelEntry, ".."+string(filepath.Separator)) {
		return errors.New("active_character.model_entry must not escape the model directory")
	}
	if !strings.HasSuffix(strings.ToLower(char.ModelEntry), ".model3.json") {
		return errors.New("active_character.model_entry must end with .model3.json")
	}
	if char.Scale < 0.25 || char.Scale > 4 {
		if char.Scale == 0 {
			char.Scale = 1
		} else {
			return errors.New("active_character.scale must be between 0.25 and 4")
		}
	}
	if char.ReplyLanguage != "" && char.ReplyLanguage != "auto" && char.ReplyLanguage != "en" && char.ReplyLanguage != "zh_CN" {
		return errors.New("active_character.reply_language must be auto, en or zh_CN")
	}
	return nil
}

func (s *Server) handleInfo(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 4*time.Second)
	defer cancel()
	info := map[string]any{
		"version": s.opts.Version,
		"paths": map[string]string{
			"config_dir":  s.opts.Paths.ConfigDir,
			"data_dir":    s.opts.Paths.DataDir,
			"runtime_dir": s.opts.Paths.RuntimeDir,
		},
		"runtime": map[string]any{
			"pid":        os.Getpid(),
			"go_version": runtimeVersion(),
		},
	}
	niriInfo := map[string]any{"available": s.opts.Niri != nil && s.opts.Niri.Available()}
	if s.opts.Niri != nil && s.opts.Niri.Available() {
		if v, err := s.opts.Niri.Version(ctx); err == nil {
			niriInfo["version"] = strings.TrimSpace(v)
		}
		if outputs, err := s.opts.Niri.Outputs(ctx); err == nil {
			niriInfo["outputs"] = outputs
		} else {
			niriInfo["outputs_error"] = err.Error()
		}
		if workspaces, err := s.opts.Niri.Workspaces(ctx); err == nil {
			niriInfo["workspaces"] = workspaces
		} else {
			niriInfo["workspaces_error"] = err.Error()
		}
	}
	info["niri"] = niriInfo
	writeJSON(w, http.StatusOK, info)
}

func (s *Server) handlePetCommand(w http.ResponseWriter, r *http.Request) {
	var command map[string]any
	dec := json.NewDecoder(http.MaxBytesReader(w, r.Body, 64<<10))
	if err := dec.Decode(&command); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	event := s.opts.Bus.Publish(state.EventPetCommand, command)
	writeJSON(w, http.StatusAccepted, map[string]any{"event_id": event.ID})
}

func (s *Server) handleQuit(w http.ResponseWriter, r *http.Request) {
	if s.opts.Quit == nil {
		writeError(w, http.StatusNotImplemented, "not_available", "quit is not configured")
		return
	}
	writeJSON(w, http.StatusAccepted, map[string]any{"ok": true})
	go func() {
		time.Sleep(150 * time.Millisecond)
		s.opts.Quit()
	}()
}

func (s *Server) handleOpenUI(w http.ResponseWriter, r *http.Request) {
	if s.opts.OpenUI == nil {
		writeError(w, http.StatusNotImplemented, "not_available", "UI autostart is not configured")
		return
	}
	if err := s.opts.OpenUI(); err != nil {
		writeError(w, http.StatusInternalServerError, "spawn_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusAccepted, map[string]any{"ok": true})
}

func (s *Server) handleEvents(w http.ResponseWriter, r *http.Request) {
	flusher, ok := w.(http.Flusher)
	if !ok {
		writeError(w, http.StatusInternalServerError, "no_streaming", "streaming unsupported")
		return
	}
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no")
	w.WriteHeader(http.StatusOK)
	fmt.Fprint(w, "retry: 2000\n\n")
	flusher.Flush()

	events, unsubscribe := s.opts.Bus.Subscribe(32)
	defer unsubscribe()

	// Re-sync immediately so a late subscriber has a complete snapshot.
	if err := writeSSE(w, eventbus.Event{
		Type:      state.EventStateChanged,
		Timestamp: time.Now().UTC(),
		Data:      s.opts.State.Snapshot(),
	}); err != nil {
		return
	}
	flusher.Flush()

	keepalive := time.NewTicker(15 * time.Second)
	defer keepalive.Stop()
	for {
		select {
		case <-r.Context().Done():
			return
		case <-keepalive.C:
			if _, err := fmt.Fprint(w, ": ping\n\n"); err != nil {
				return
			}
			flusher.Flush()
		case event, ok := <-events:
			if !ok {
				return
			}
			if err := writeSSE(w, event); err != nil {
				return
			}
			flusher.Flush()
		}
	}
}

func writeSSE(w http.ResponseWriter, event eventbus.Event) error {
	data, err := json.Marshal(event.Data)
	if err != nil {
		return err
	}
	_, err = fmt.Fprintf(w, "id: %d\nevent: %s\ndata: %s\n\n", event.ID, event.Type, data)
	return err
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

func writeError(w http.ResponseWriter, status int, code, message string) {
	writeJSON(w, status, map[string]any{
		"error": map[string]string{"code": code, "message": message},
	})
}
