/**
 * Thin bridge between the Web renderer and the Python pet shell.
 *
 * The pet shell is a GTK4 layer-shell window hosting WebKitGTK. When the page
 * runs in a normal browser, messages are logged instead, which keeps the
 * renderer debuggable with any static HTTP server.
 */

const nativeBridge = globalThis.webkit?.messageHandlers?.ailune ?? null;

export function hasNativeBridge() {
  return nativeBridge !== null;
}

export function post(message) {
  if (nativeBridge) {
    try {
      nativeBridge.postMessage(message);
      return;
    } catch (error) {
      console.warn("Ailune bridge rejected a message", error);
      return;
    }
  }
  console.debug("[ailune bridge]", message);
}

export function log(...args) {
  console.log("[ailune]", ...args);
}
