// Package eventbus is a small in-process fan-out broker used for SSE.
package eventbus

import (
	"sync"
	"time"
)

// Event is delivered to every current subscriber. Slow subscribers drop
// events rather than blocking the publisher.
type Event struct {
	ID        int64       `json:"id"`
	Type      string      `json:"type"`
	Timestamp time.Time   `json:"timestamp"`
	Data      interface{} `json:"data,omitempty"`
}

// Bus broadcasts events to subscribers.
type Bus struct {
	mu          sync.Mutex
	nextID      int64
	nextSubID   int
	subscribers map[int]chan Event
	closed      bool
}

// New returns an empty bus.
func New() *Bus {
	return &Bus{subscribers: make(map[int]chan Event)}
}

// Publish sends an event to all subscribers, dropping it for full channels.
func (b *Bus) Publish(eventType string, data interface{}) Event {
	b.mu.Lock()
	if b.closed {
		b.mu.Unlock()
		return Event{}
	}
	b.nextID++
	event := Event{
		ID:        b.nextID,
		Type:      eventType,
		Timestamp: time.Now().UTC(),
		Data:      data,
	}
	subs := make([]chan Event, 0, len(b.subscribers))
	for _, ch := range b.subscribers {
		subs = append(subs, ch)
	}
	b.mu.Unlock()

	for _, ch := range subs {
		select {
		case ch <- event:
		default: // Drop for slow consumers; SSE clients re-sync via snapshot.
		}
	}
	return event
}

// Subscribe returns a channel and an unsubscribe function.
func (b *Bus) Subscribe(buffer int) (<-chan Event, func()) {
	if buffer <= 0 {
		buffer = 16
	}
	ch := make(chan Event, buffer)
	b.mu.Lock()
	if b.closed {
		b.mu.Unlock()
		close(ch)
		return ch, func() {}
	}
	b.nextSubID++
	id := b.nextSubID
	b.subscribers[id] = ch
	b.mu.Unlock()

	var once sync.Once
	return ch, func() {
		once.Do(func() {
			b.mu.Lock()
			if existing, ok := b.subscribers[id]; ok {
				delete(b.subscribers, id)
				close(existing)
			}
			b.mu.Unlock()
		})
	}
}

// Close disconnects all subscribers and ignores further events.
func (b *Bus) Close() {
	b.mu.Lock()
	if b.closed {
		b.mu.Unlock()
		return
	}
	b.closed = true
	for id, ch := range b.subscribers {
		delete(b.subscribers, id)
		close(ch)
	}
	b.mu.Unlock()
}
