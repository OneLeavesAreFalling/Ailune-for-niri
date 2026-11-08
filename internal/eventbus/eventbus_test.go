package eventbus

import (
	"testing"
	"time"
)

func TestPublishSubscribe(t *testing.T) {
	bus := New()
	events, unsubscribe := bus.Subscribe(4)
	defer unsubscribe()
	event := bus.Publish("test", map[string]string{"hello": "world"})
	if event.ID != 1 {
		t.Fatalf("id = %d, want 1", event.ID)
	}
	select {
	case got := <-events:
		if got.Type != "test" || got.ID != 1 {
			t.Fatalf("unexpected event: %+v", got)
		}
	case <-time.After(time.Second):
		t.Fatal("timed out waiting for event")
	}
}

func TestUnsubscribeClosesChannel(t *testing.T) {
	bus := New()
	events, unsubscribe := bus.Subscribe(1)
	unsubscribe()
	select {
	case _, ok := <-events:
		if ok {
			t.Fatal("channel should be closed")
		}
	case <-time.After(time.Second):
		t.Fatal("channel was not closed")
	}
	unsubscribe() // idempotent
}

func TestSlowSubscriberDoesNotBlock(t *testing.T) {
	bus := New()
	_, unsubscribe := bus.Subscribe(1)
	defer unsubscribe()
	done := make(chan struct{})
	go func() {
		for i := 0; i < 100; i++ {
			bus.Publish("spam", i)
		}
		close(done)
	}()
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("publish blocked on a slow subscriber")
	}
}

func TestClose(t *testing.T) {
	bus := New()
	events, _ := bus.Subscribe(1)
	bus.Close()
	select {
	case _, ok := <-events:
		if ok {
			t.Fatal("expected closed channel")
		}
	case <-time.After(time.Second):
		t.Fatal("close did not close subscriber")
	}
	bus.Publish("after", nil)
}
