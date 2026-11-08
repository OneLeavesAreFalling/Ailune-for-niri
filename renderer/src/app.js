/**
 * Ailune pet renderer entry point.
 *
 * Layout model: the pet shell owns a full-output layer surface and clips input
 * to the rectangles reported here. The character itself lives in a 420×420
 * canvas that can be moved anywhere inside the output without moving the
 * Wayland surface, which makes dragging stable on layer-shell surfaces.
 */

import { hasNativeBridge, log, post } from "./bridge.js";
import { PlaceholderCharacter, SIZE } from "./placeholder.js";
import { createLive2DRenderer } from "./live2d/adapter.js";

const stage = document.getElementById("stage");
const canvas = document.getElementById("character");
const bubble = document.getElementById("bubble");
const menu = document.getElementById("menu");

const LABELS = {
  en: {
    chat: "Chat",
    settings: "Settings",
    hide: "Hide pet",
    reload: "Reload renderer",
    quit: "Quit Ailune",
    greet: (name) => `Hi, I'm ${name}.`,
  },
  zh_CN: {
    chat: "聊天",
    settings: "设置",
    hide: "隐藏桌宠",
    reload: "重新加载",
    quit: "退出 Ailune",
    greet: (name) => `你好，我是${name}。`,
  },
};

const MENU_ITEMS = [
  { action: "open-ui", label: "chat", icon: "💬" },
  { action: "open-ui", label: "settings", icon: "⚙" },
  { separator: true },
  { action: "hide", label: "hide", icon: "◐" },
  { action: "reload", label: "reload", icon: "↻" },
  { separator: true },
  { action: "quit", label: "quit", icon: "⏻", danger: true },
];

const layout = {
  x: 0,
  y: 0,
  scale: 1,
  clickThrough: false,
  language: "en",
};

let characterName = "Ailune";
let currentCharacter = null;
let liveRenderer = null;
let dragging = false;
let dragMoved = 0;
let dragStart = null;
let dragStartLayout = null;
let lastPositionSent = 0;
let lastRegion = "";
let menuOpen = false;
let bubbleVisible = false;
let bubbleTimer = 0;
let lastFrame = 0;

const placeholder = new PlaceholderCharacter(canvas);

function t(key) {
  const table = LABELS[layout.language] || LABELS.en;
  const value = table[key] ?? LABELS.en[key] ?? key;
  return typeof value === "function" ? value(characterName) : value;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function stageSize() {
  return SIZE * layout.scale;
}

function applyLayout({ notify = false } = {}) {
  const size = stageSize();
  const maxX = Math.max(0, window.innerWidth - size);
  const maxY = Math.max(0, window.innerHeight - size);
  const clampedX = clamp(Math.round(layout.x), 0, maxX);
  const clampedY = clamp(Math.round(layout.y), 0, maxY);
  const changed = clampedX !== layout.x || clampedY !== layout.y;
  layout.x = clampedX;
  layout.y = clampedY;

  stage.style.width = `${size}px`;
  stage.style.height = `${size}px`;
  stage.style.left = `${layout.x}px`;
  stage.style.top = `${layout.y}px`;
  stage.style.transform = "none";

  positionBubble();
  sendInputRegion();
  if ((changed || notify) && !dragging) {
    sendPosition(true);
  }
}

function sendInputRegion() {
  let rectangles = [];
  if (!layout.clickThrough) {
    const s = layout.scale;
    rectangles.push([
      Math.round(layout.x + 60 * s),
      Math.round(layout.y + 20 * s),
      Math.round(300 * s),
      Math.round(392 * s),
    ]);
    if (menuOpen) {
      const rect = menu.getBoundingClientRect();
      rectangles.push([Math.round(rect.left - 2), Math.round(rect.top - 2), Math.round(rect.width + 4), Math.round(rect.height + 4)]);
    }
  }
  const serialized = JSON.stringify(rectangles);
  if (serialized !== lastRegion) {
    lastRegion = serialized;
    post({ type: "input-region", rects: rectangles });
  }
}

function sendPosition(force = false) {
  const now = performance.now();
  if (!force && now - lastPositionSent < 40) return;
  lastPositionSent = now;
  post({ type: "position", x: layout.x, y: layout.y, scale: layout.scale });
}

function positionBubble() {
  if (!bubbleVisible) return;
  const stageTop = layout.y;
  const stageLeft = layout.x;
  const bubbleWidth = Math.min(280, window.innerWidth - 24);
  bubble.style.width = `${bubbleWidth}px`;
  bubble.style.left = `${clamp(stageLeft + 36, 8, window.innerWidth - bubbleWidth - 8)}px`;
  const height = bubble.offsetHeight;
  let top = stageTop - height - 16;
  if (top < 8) top = stageTop + stageSize() + 14;
  bubble.style.top = `${Math.max(8, top)}px`;
}

function showCaption(text, { sticky = false } = {}) {
  const clean = String(text || "").trim();
  if (!clean) {
    hideCaption();
    return;
  }
  bubble.replaceChildren();
  const name = document.createElement("span");
  name.className = "bubble-name";
  name.textContent = characterName;
  const body = document.createElement("span");
  body.textContent = clean.length > 240 ? `${clean.slice(0, 240)}…` : clean;
  bubble.append(name, body);
  bubble.classList.remove("hidden");
  bubbleVisible = true;
  positionBubble();
  clearTimeout(bubbleTimer);
  if (!sticky) {
    bubbleTimer = window.setTimeout(() => hideCaption(), 12000);
  }
}

function hideCaption() {
  bubble.classList.add("hidden");
  bubbleVisible = false;
}

function rebuildMenu() {
  menu.replaceChildren();
  for (const item of MENU_ITEMS) {
    if (item.separator) {
      const sep = document.createElement("div");
      sep.className = "sep";
      menu.append(sep);
      continue;
    }
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("role", "menuitem");
    const icon = document.createElement("span");
    icon.className = "icon";
    icon.textContent = item.icon;
    const label = document.createElement("span");
    label.textContent = t(item.label);
    button.append(icon, label);
    if (item.danger) button.classList.add("danger");
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      closeMenu();
      post({ type: "action", action: item.action });
    });
    menu.append(button);
  }
}

function openMenu(clientX, clientY) {
  rebuildMenu();
  menuOpen = true;
  menu.classList.remove("hidden");
  // Measure after layout; fall back to a conservative estimate if the
  // compositor has not laid the popup out yet.
  let rect = menu.getBoundingClientRect();
  const width = rect.width || 176;
  const height = rect.height || 260;
  let left = clientX + 4;
  let top = clientY + 4;
  if (left + width > window.innerWidth - 8) left = clientX - width - 4;
  if (top + height > window.innerHeight - 8) top = clientY - height - 4;
  left = clamp(left, 8, Math.max(8, window.innerWidth - width - 8));
  top = clamp(top, 8, Math.max(8, window.innerHeight - height - 8));
  menu.style.left = `${left}px`;
  menu.style.top = `${top}px`;
  rect = menu.getBoundingClientRect();
  post({
    type: "debug",
    menu: { left: rect.left, top: rect.top, width: rect.width, height: rect.height },
    viewport: [window.innerWidth, window.innerHeight, window.devicePixelRatio],
    stage: { x: layout.x, y: layout.y, size: stageSize() },
  });
  sendInputRegion();
}

function closeMenu() {
  if (!menuOpen) return;
  menuOpen = false;
  menu.classList.add("hidden");
  sendInputRegion();
}

function setLanguage(language) {
  layout.language = language === "zh_CN" ? "zh_CN" : "en";
  document.documentElement.lang = layout.language === "zh_CN" ? "zh-CN" : "en";
  if (menuOpen) rebuildMenu();
}

async function loadCharacter(payload) {
  let data = payload;
  if (typeof payload === "string") {
    try {
      data = JSON.parse(payload);
    } catch {
      data = {};
    }
  }
  if (!data || typeof data !== "object") data = {};
  currentCharacter = data;
  characterName = data.name || "Ailune";
  hideCaption();
  placeholder.setExpression("neutral");
  liveRenderer?.destroy?.();
  liveRenderer = null;

  if (data.model_url) {
    try {
      liveRenderer = await createLive2DRenderer({
        canvas,
        modelUrl: data.model_url,
        modelEntry: data.model_entry || "",
        name: characterName,
      });
    } catch (error) {
      console.warn("[ailune] Live2D load failed", error);
    }
  }
  if (liveRenderer) {
    post({ type: "renderer", renderer: "live2d", name: characterName });
    showCaption(t("greet"), {});
  } else {
    post({ type: "renderer", renderer: "placeholder", name: characterName });
    showCaption(t("greet"), {});
  }
}

function setLayout(payload) {
  let data = payload;
  if (typeof payload === "string") {
    try {
      data = JSON.parse(payload);
    } catch {
      return;
    }
  }
  if (!data || typeof data !== "object") return;
  if (typeof data.x === "number") layout.x = data.x;
  if (typeof data.y === "number") layout.y = data.y;
  if (typeof data.scale === "number" && data.scale > 0) layout.scale = clamp(data.scale, 0.25, 4);
  if (typeof data.clickThrough === "boolean") layout.clickThrough = data.clickThrough;
  if (typeof data.language === "string") setLanguage(data.language);
  stage.classList.add("visible");
  applyLayout();
}

function setVisible(visible) {
  placeholder.setVisible(Boolean(visible));
  stage.style.display = visible ? "block" : "none";
  if (!visible) {
    bubble.classList.add("hidden");
    bubbleVisible = false;
    closeMenu();
  } else {
    applyLayout();
  }
}

function normalizePoint(event) {
  const size = stageSize();
  const cx = layout.x + size / 2;
  const cy = layout.y + size / 2;
  return {
    x: clamp((event.clientX - cx) / (size * 0.45), -1, 1),
    y: clamp((event.clientY - cy) / (size * 0.45), -1, 1),
  };
}

function onPointerDown(event) {
  if (menuOpen && !menu.contains(event.target)) {
    closeMenu();
  }
  if (event.button === 2) return;
  if (event.button !== 0) return;
  if (menu.contains(event.target)) return;
  dragging = true;
  dragMoved = 0;
  dragStart = { x: event.clientX, y: event.clientY };
  dragStartLayout = { x: layout.x, y: layout.y };
  stage.classList.add("dragging");
  try {
    stage.setPointerCapture(event.pointerId);
  } catch {
    /* pointer capture is best-effort */
  }
  event.preventDefault();
}

function onPointerMove(event) {
  const look = normalizePoint(event);
  placeholder.setLook(look.x, look.y);
  if (!dragging || !dragStart || !dragStartLayout) return;
  const dx = event.clientX - dragStart.x;
  const dy = event.clientY - dragStart.y;
  dragMoved = Math.max(dragMoved, Math.hypot(dx, dy));
  layout.x = dragStartLayout.x + dx;
  layout.y = dragStartLayout.y + dy;
  applyLayout();
  sendPosition(false);
  event.preventDefault();
}

function onPointerUp(event) {
  if (!dragging) return;
  dragging = false;
  stage.classList.remove("dragging");
  try {
    stage.releasePointerCapture(event.pointerId);
  } catch {
    /* ignore */
  }
  const wasClick = dragMoved < 6;
  sendPosition(true);
  if (wasClick && !menu.contains(event.target)) {
    placeholder.reactHappy();
    post({ type: "interaction", action: "headpat", x: layout.x, y: layout.y });
  }
}

function onContextMenu(event) {
  event.preventDefault();
  openMenu(event.clientX, event.clientY);
}

function installEvents() {
  stage.addEventListener("pointerdown", onPointerDown);
  window.addEventListener("pointermove", onPointerMove, { passive: false });
  window.addEventListener("pointerup", onPointerUp);
  window.addEventListener("pointercancel", onPointerUp);
  stage.addEventListener("contextmenu", onContextMenu);
  stage.addEventListener("pointerleave", () => placeholder.setLook(0, 0));
  window.addEventListener("pointerdown", (event) => {
    if (menuOpen && !menu.contains(event.target)) closeMenu();
  }, true);
  window.addEventListener("resize", () => applyLayout({ notify: true }));
  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeMenu();
  });
  window.addEventListener("blur", () => {
    if (dragging) onPointerUp({ pointerId: 0, target: stage });
  });
}

function loop(now) {
  const dt = lastFrame ? now - lastFrame : 16;
  lastFrame = now;
  if (liveRenderer && typeof liveRenderer.draw === "function") {
    try {
      liveRenderer.draw(now, dt);
    } catch (error) {
      console.error("[ailune] Live2D draw failed; reverting to placeholder", error);
      liveRenderer = null;
    }
  } else {
    placeholder.draw(now);
  }
  requestAnimationFrame(loop);
}

// Public API called by the Python pet shell via evaluate_javascript.
window.AiluneBridge = {
  ready: true,
  setLayout,
  loadCharacter,
  setExpression(name) {
    placeholder.setExpression(name);
    liveRenderer?.setExpression?.(name);
  },
  playMotion(group = "", index = 0) {
    placeholder.playMotion(group, index);
    liveRenderer?.playMotion?.(group, index);
  },
  setMouth(value) {
    placeholder.setMouth(value);
    liveRenderer?.setMouth?.(value);
  },
  setSpeaking(value) {
    placeholder.setSpeaking(value);
    liveRenderer?.setSpeaking?.(value);
  },
  setCaption(text, sticky = false) {
    showCaption(text, { sticky: Boolean(sticky) });
  },
  hideCaption,
  setLanguage,
  setVisible,
  notifyState(state) {
    if (!state || typeof state !== "object") return;
    if (state.language) setLanguage(state.language);
    if (state.visible === false) setVisible(false);
    if (state.visible === true) setVisible(true);
  },
  react(kind = "happy") {
    if (kind === "happy") placeholder.reactHappy();
    else placeholder.playMotion(kind);
  },
  openMenuAt(x = window.innerWidth / 2, y = window.innerHeight / 2) {
    openMenu(x, y);
  },
  closeMenu() {
    closeMenu();
  },
};

installEvents();
placeholder.setExpression("neutral");
applyLayout();
requestAnimationFrame(loop);
setTimeout(() => {
  applyLayout();
  post({ type: "ready", native: hasNativeBridge() });
  log("renderer ready", hasNativeBridge() ? "native bridge" : "browser");
}, 60);
