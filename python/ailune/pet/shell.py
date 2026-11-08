"""GTK4 layer-shell pet window hosting the Web renderer."""

from __future__ import annotations

import json
import logging
import os
import signal
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import quote

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("WebKit", "6.0")
gi.require_version("Gtk4LayerShell", "1.0")

from gi.repository import Gdk, GLib, Gtk, Gtk4LayerShell as LayerShell, WebKit  # noqa: E402

from ailune.common.paths import core_url, load_app_config, load_token, project_root  # noqa: E402

from .core_client import CoreClient  # noqa: E402
from .http_server import RendererServer  # noqa: E402

logger = logging.getLogger("ailune.pet")

BASE_SIZE = 420
MIN_SCALE = 0.25
MAX_SCALE = 4.0
DEFAULT_EDGE_GAP = 48
POSITION_SETTLE_SECONDS = 1.2


def _default_state(language: str = "en") -> dict[str, Any]:
    return {
        "version": 1,
        "language": language,
        "active_character": None,
        "pet": {
            "visible": True,
            "x": -1,
            "y": -1,
            "scale": 1.0,
            "output": "",
            "click_through": False,
        },
        "services": {},
    }


class PetShell:
    def __init__(self, application: Gtk.Application) -> None:
        self.application = application
        self.stop_event = threading.Event()
        root = project_root()
        self.renderer_dir = root / "renderer"
        self.server = RendererServer(self.renderer_dir)
        self.renderer_url = self.server.start()
        self.client = CoreClient(core_url(), load_token(), timeout=2.5)
        config = load_app_config()
        self.state = _default_state(config.get("language", "en") if isinstance(config, dict) else "en")
        self.window: Gtk.ApplicationWindow | None = None
        self.webview: WebKit.WebView | None = None
        self.page_ready = False
        self.page_load_finished = False
        self.input_rects: list[list[int]] = []
        self.view_visible = True
        self.persist_timer: int | None = None
        self.last_local_position_at = 0.0
        self.character_key: tuple[str, str, str] | None = None
        self.layout: dict[str, Any] = {
            "x": 0,
            "y": 0,
            "scale": 1.0,
            "clickThrough": False,
            "language": "en",
        }
        self.monitor_size = (1280, 800)
        self._event_thread: threading.Thread | None = None
        self._eval_errors_logged = False
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ailune-pet-io")
        self._window_visible = False
        self._last_persisted: tuple[int, int] | None = None

        initial = self.client.get_state()
        if initial:
            self.state = initial

    # ------------------------------------------------------------------ window

    def build(self) -> None:
        if self.window is not None:
            self.window.present()
            return
        display = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError("no GDK display; Ailune pet requires a Wayland session")
        monitor = self._select_monitor(display)
        geometry = monitor.get_geometry()
        self.monitor_size = (geometry.width, geometry.height)

        style = Gtk.CssProvider()
        style.load_from_data(
            b"window, window.background, .background { background-color: transparent; }"
        )
        Gtk.StyleContext.add_provider_for_display(
            display, style, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        window = Gtk.ApplicationWindow(application=self.application)
        window.set_title("Ailune")
        window.set_decorated(False)
        window.set_resizable(False)
        window.set_default_size(geometry.width, geometry.height)

        LayerShell.init_for_window(window)
        LayerShell.set_namespace(window, "ailune-pet")
        LayerShell.set_layer(window, LayerShell.Layer.OVERLAY)
        try:
            LayerShell.set_monitor(window, monitor)
        except Exception:
            logger.debug("could not select a layer-shell monitor", exc_info=True)
        for edge in (
            LayerShell.Edge.TOP,
            LayerShell.Edge.BOTTOM,
            LayerShell.Edge.LEFT,
            LayerShell.Edge.RIGHT,
        ):
            LayerShell.set_anchor(window, edge, True)
            LayerShell.set_margin(window, edge, 0)
        LayerShell.set_exclusive_zone(window, 0)
        LayerShell.set_keyboard_mode(window, LayerShell.KeyboardMode.NONE)

        manager = WebKit.UserContentManager()
        manager.register_script_message_handler("ailune")
        manager.connect("script-message-received::ailune", self._on_script_message)
        if os.environ.get("AILUNE_DEBUG") == "1":
            try:
                errors_script = WebKit.UserScript.new(
                    "window.__ailuneErrors=[];"
                    "window.addEventListener('error',function(e){"
                    "window.__ailuneErrors.push(String(e.message)+' @ '+String(e.filename)+':'+String(e.lineno));"
                    "try{window.webkit.messageHandlers.ailune.postMessage({type:'js-error',message:String(e.message),"
                    "filename:String(e.filename),line:e.lineno});}catch(_){}});",
                    WebKit.UserContentInjectedFrames.ALL_FRAMES,
                    WebKit.UserScriptInjectionTime.START,
                    None,
                    None,
                )
                manager.add_script(errors_script)
            except Exception:
                logger.debug("could not install JS error probe", exc_info=True)

        view = WebKit.WebView(user_content_manager=manager)
        view.set_background_color(Gdk.RGBA(0, 0, 0, 0))
        settings = view.get_settings()
        settings.set_enable_webgl(True)
        settings.set_enable_javascript(True)
        settings.set_enable_developer_extras(os.environ.get("AILUNE_PET_DEV") == "1")
        settings.set_javascript_can_access_clipboard(False)
        settings.set_allow_universal_access_from_file_urls(False)
        try:
            settings.set_enable_smooth_scrolling(False)
        except Exception:
            pass
        view.set_hexpand(True)
        view.set_vexpand(True)
        view.connect("load-changed", self._on_load_changed)
        view.connect("load-failed", self._on_load_failed)
        view.connect("web-process-terminated", self._on_web_process_terminated)

        window.set_child(view)
        window.connect("realize", self._on_realize)
        window.connect("map", self._on_map)
        self.window = window
        self.webview = view
        window.present()
        view.load_uri(self.renderer_url)

        self._apply_snapshot(self.state, initial=True)
        self._start_core_events()

    def _select_monitor(self, display: Gdk.Display) -> Gdk.Monitor:
        monitors = display.get_monitors()
        count = monitors.get_n_items()
        if count == 0:
            raise RuntimeError("no monitors available")
        wanted = str((self.state.get("pet") or {}).get("output") or "")
        if wanted:
            for index in range(count):
                monitor = monitors.get_item(index)
                connector = ""
                try:
                    connector = monitor.get_connector() or ""
                except Exception:
                    connector = ""
                if connector == wanted:
                    return monitor
        try:
            primary = display.get_primary_monitor()
            if primary is not None:
                return primary
        except Exception:
            pass
        return monitors.get_item(0)

    def _on_realize(self, window: Gtk.Window) -> None:
        logger.info("pet layer surface realized")
        self._apply_input_region()

    def _on_map(self, window: Gtk.Window) -> None:
        self._apply_input_region()

    # ------------------------------------------------------------------ input region

    def _surface(self) -> Gdk.Surface | None:
        if self.window is None:
            return None
        try:
            return self.window.get_surface()
        except Exception:
            return None

    def _apply_input_region(self) -> None:
        surface = self._surface()
        if surface is None:
            return
        region = cairo.Region()
        pet = self.state.get("pet") or {}
        if self.view_visible and not pet.get("click_through") and self.input_rects:
            for rect in self.input_rects[:12]:
                try:
                    x, y, width, height = (int(round(value)) for value in rect)
                except (TypeError, ValueError):
                    continue
                if width <= 0 or height <= 0:
                    continue
                region.union(cairo.RectangleInt(x, y, width, height))
        try:
            surface.set_input_region(region)
        except Exception:
            logger.debug("could not set layer surface input region", exc_info=True)

    # ------------------------------------------------------------------ state

    def _apply_snapshot(self, snapshot: dict[str, Any], initial: bool = False) -> None:
        if not isinstance(snapshot, dict):
            return
        pet = snapshot.get("pet") if isinstance(snapshot.get("pet"), dict) else {}
        character = snapshot.get("active_character")
        if character is not None and not isinstance(character, dict):
            character = None
        language = snapshot.get("language") or "en"
        self.state = snapshot
        self.state["language"] = language

        scale = float(pet.get("scale") or 1.0)
        if character and character.get("scale"):
            scale *= float(character.get("scale") or 1.0)
        scale = max(MIN_SCALE, min(MAX_SCALE, scale))

        now = GLib.get_monotonic_time() / 1_000_000
        skip_position = (
            not initial
            and self.last_local_position_at > 0
            and now - self.last_local_position_at < POSITION_SETTLE_SECONDS
        )
        x = self.layout["x"] if skip_position else pet.get("x", -1)
        y = self.layout["y"] if skip_position else pet.get("y", -1)
        if x is None or int(x) < 0 or y is None or int(y) < 0:
            x, y = self._default_position(scale)
        click_through = bool(pet.get("click_through"))
        visible = pet.get("visible", True) is not False

        self.layout.update(
            {
                "x": int(x),
                "y": int(y),
                "scale": scale,
                "clickThrough": click_through,
                "language": language,
            }
        )

        character_changed = False
        character_name = "Ailune"
        if character:
            model_path = character.get("model_path") or ""
            entry = character.get("model_entry") or ""
            character_name = character.get("name") or "Ailune"
            key = (str(character.get("id") or ""), str(model_path), str(entry))
            if key != self.character_key:
                self.character_key = key
                character_changed = True
                self._set_model(model_path, entry, character_name)
        else:
            if self.character_key is not None:
                self.character_key = None
                character_changed = True
                self.server.set_model_root(None)

        if not visible:
            self._set_window_visible(False)
        else:
            self._set_window_visible(True)
        self._push_layout()
        if self.page_ready and character_changed:
            if character:
                self._push_character(character)
            else:
                self._push_no_character()
        if initial and int(pet.get("x", -1)) < 0:
            self._last_persisted = None
            self._schedule_persist()
        elif not skip_position and int(pet.get("x", -1)) >= 0:
            self._last_persisted = (int(x), int(y))

    def _default_position(self, scale: float) -> tuple[int, int]:
        width, height = self.monitor_size
        size = int(BASE_SIZE * scale)
        x = max(0, width - size - DEFAULT_EDGE_GAP)
        y = max(0, height - size - DEFAULT_EDGE_GAP)
        return x, y

    def _set_model(self, model_path: str, entry: str, name: str) -> None:
        root = Path(model_path).expanduser() if model_path else None
        if root and root.is_dir():
            self.server.set_model_root(root)
        else:
            self.server.set_model_root(None)
            logger.warning("active character model directory is missing: %s", model_path)
        logger.info("active character: %s (%s)", name, entry)

    def _push_layout(self) -> None:
        layout = dict(self.layout)
        self._eval(f"window.AiluneBridge && window.AiluneBridge.setLayout({_js(layout)});")

    def _push_character(self, character: dict[str, Any]) -> None:
        name = character.get("name") or "Ailune"
        entry = character.get("model_entry") or ""
        model_url = ""
        if self.server.model_root is not None and entry:
            base = self.renderer_url.rsplit("/index.html", 1)[0]
            model_url = f"{base}/model/{quote(entry, safe='/')}"
        payload = {
            "name": name,
            "model_entry": entry,
            "model_url": model_url,
            "language": self.layout["language"],
        }
        self._eval(f"window.AiluneBridge && window.AiluneBridge.loadCharacter({_js(payload)});")

    def _push_no_character(self) -> None:
        payload = {"name": "Ailune", "model_entry": "", "model_url": ""}
        self._eval(f"window.AiluneBridge && window.AiluneBridge.loadCharacter({_js(payload)});")

    def _push_full_state(self) -> None:
        self._push_layout()
        self._set_view_visibility(self.view_visible)
        character = self.state.get("active_character")
        if isinstance(character, dict):
            self._push_character(character)
        else:
            self._push_no_character()

    def _set_window_visible(self, visible: bool) -> None:
        self.view_visible = visible
        if self.window is None:
            return
        if visible:
            if not self._window_visible:
                self.window.set_visible(True)
                self.window.present()
                self._window_visible = True
            self._set_view_visibility(True)
            self._apply_input_region()
        else:
            self._apply_input_region()
            if self._window_visible:
                self.window.set_visible(False)
                self._window_visible = False

    def _set_view_visibility(self, visible: bool) -> None:
        self._eval(f"window.AiluneBridge && window.AiluneBridge.setVisible({_js(visible)});")

    # ------------------------------------------------------------------ renderer messages

    def _on_script_message(self, _manager: WebKit.UserContentManager, message: Any) -> None:
        try:
            value = message.get_js_value() if hasattr(message, "get_js_value") else message
            if hasattr(value, "to_json"):
                raw = value.to_json(0)
            elif hasattr(value, "to_string"):
                raw = value.to_string()
            else:
                raw = str(value)
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                return
            kind = payload.get("type")
            if kind == "ready":
                self.page_ready = True
                logger.info("renderer bridge ready")
                self._push_full_state()
                self._schedule_persist()
            elif kind == "input-region":
                self._accept_input_region(payload.get("rects"))
            elif kind == "position":
                self._on_js_position(payload)
            elif kind == "action":
                self._on_action(str(payload.get("action") or ""))
            elif kind == "interaction":
                logger.debug("pet interaction: %s", payload.get("action"))
            elif kind == "renderer":
                logger.info("renderer: %s", payload.get("renderer"))
            elif kind == "js-error":
                logger.error(
                    "renderer JS error: %s (%s:%s)",
                    payload.get("message"),
                    payload.get("filename"),
                    payload.get("line"),
                )
            elif kind == "debug":
                logger.info("renderer debug message: %s", payload)
        except Exception:
            logger.debug("could not decode renderer message", exc_info=True)

    def _accept_input_region(self, rects: Any) -> None:
        if not isinstance(rects, list):
            return
        cleaned: list[list[int]] = []
        for rect in rects[:12]:
            if not isinstance(rect, (list, tuple)) or len(rect) != 4:
                continue
            try:
                values = [int(round(float(value))) for value in rect]
            except (TypeError, ValueError):
                continue
            if values[2] <= 0 or values[3] <= 0:
                continue
            cleaned.append(values)
        self.input_rects = cleaned
        self._apply_input_region()

    def _on_js_position(self, payload: dict[str, Any]) -> None:
        try:
            x = int(round(float(payload.get("x"))))
            y = int(round(float(payload.get("y"))))
        except (TypeError, ValueError):
            return
        self.layout["x"] = x
        self.layout["y"] = y
        self.last_local_position_at = GLib.get_monotonic_time() / 1_000_000
        self._schedule_persist()

    def _on_action(self, action: str) -> None:
        logger.info("pet action: %s", action)
        if action == "open-ui":
            self._run_io(self.client.action, "open-ui")
        elif action == "hide":
            self.view_visible = False
            if self.window is not None:
                self.window.set_visible(False)
                self._window_visible = False
            self._run_io(self.client.patch_state, {"pet": {"visible": False}})
        elif action == "reload":
            if self.webview is not None:
                self.webview.reload()
        elif action == "quit":
            self._run_io(self._quit_via_core)

    # ------------------------------------------------------------------ persistence

    def _schedule_persist(self) -> None:
        if self.persist_timer is not None:
            return
        self.persist_timer = GLib.timeout_add(300, self._flush_position)

    def _flush_position(self) -> bool:
        self.persist_timer = None
        position = (int(self.layout["x"]), int(self.layout["y"]))
        if position == self._last_persisted:
            return False
        self._last_persisted = position
        self._run_io(self.client.patch_state, {"pet": {"x": position[0], "y": position[1]}})
        return False

    # ------------------------------------------------------------------ webkit

    def _on_load_changed(self, view: WebKit.WebView, event: WebKit.LoadEvent) -> None:
        if event == WebKit.LoadEvent.FINISHED:
            self.page_load_finished = True
            logger.info("renderer page loaded")
            GLib.timeout_add(700, self._ready_fallback)
            if os.environ.get("AILUNE_DEBUG") == "1":
                GLib.timeout_add(900, self._debug_probe)

    def _debug_probe(self) -> bool:
        if self.webview is None:
            return False
        script = (
            "JSON.stringify({readyState:document.readyState,"
            "bridge:typeof window.AiluneBridge,"
            "webkit:typeof window.webkit,"
            "handlers:!!(window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.ailune),"
            "stage:!!document.getElementById('stage'),"
            "errors:(window.__ailuneErrors||[]),"
            "title:document.title})"
        )
        try:
            self.webview.evaluate_javascript(script, -1, None, None, None, self._debug_result, None)
        except Exception:
            logger.debug("debug probe failed", exc_info=True)
        return False

    def _debug_result(self, _view: WebKit.WebView, result: Any, _data: Any) -> None:
        try:
            value = self.webview.evaluate_javascript_finish(result)
            logger.info("renderer probe: %s", value.to_string())
        except Exception:
            logger.exception("renderer probe failed")

    def _ready_fallback(self) -> bool:
        if not self.page_ready:
            self.page_ready = True
            self._push_full_state()
        return False

    def _on_load_failed(
        self,
        _view: WebKit.WebView,
        _event: WebKit.LoadEvent,
        uri: str,
        error: GLib.Error,
    ) -> bool:
        logger.error("renderer load failed: %s (%s)", error.message, uri)
        return False

    def _on_web_process_terminated(
        self, _view: WebKit.WebView, reason: WebKit.WebProcessTerminationReason
    ) -> None:
        logger.error("WebKit web process terminated: %s", reason.value_nick)
        GLib.timeout_add(1200, self._reload_webview)

    def _reload_webview(self) -> bool:
        if self.webview is not None:
            self.page_ready = False
            self.webview.load_uri(self.renderer_url)
        return False

    def _eval(self, script: str) -> None:
        if self.webview is None or not self.page_ready:
            return
        try:
            # A trailing expression keeps WebKit from trying to deliver
            # `undefined` as a JavaScript result.
            script = f"{script}\n; true"
            self.webview.evaluate_javascript(
                script, -1, None, None, None, self._on_eval_finished, None
            )
        except Exception:
            logger.debug("javascript evaluation failed", exc_info=True)

    def _on_eval_finished(self, _view: WebKit.WebView, result: Any, _data: Any) -> None:
        try:
            self.webview.evaluate_javascript_finish(result)
        except Exception:
            if not self._eval_errors_logged:
                self._eval_errors_logged = True
                logger.debug("renderer rejected an evaluation", exc_info=True)

    # ------------------------------------------------------------------ core events

    def _start_core_events(self) -> None:
        if self._event_thread is not None:
            return

        def run() -> None:
            self.client.listen(self._on_core_event_threadsafe, self.stop_event)

        self._event_thread = threading.Thread(target=run, daemon=True, name="ailune-core-events")
        self._event_thread.start()

    def _on_core_event_threadsafe(self, event_type: str, data: Any) -> None:
        GLib.idle_add(self._on_core_event, event_type, data)

    def _on_core_event(self, event_type: str, data: Any) -> bool:
        try:
            if event_type == "state.changed" and isinstance(data, dict):
                self._apply_snapshot(data)
            elif event_type == "pet.command" and isinstance(data, dict):
                self._on_pet_command(data)
        except Exception:
            logger.exception("failed to handle core event %s", event_type)
        return False

    def _on_pet_command(self, command: dict[str, Any]) -> None:
        kind = str(command.get("type") or "")
        if kind == "caption":
            text = str(command.get("text") or "")[:600]
            sticky = bool(command.get("sticky"))
            self._eval(f"window.AiluneBridge && window.AiluneBridge.setCaption({_js(text)}, {_js(sticky)});")
            return
        if kind == "expression":
            name = str(command.get("name") or "neutral")[:40]
            self._eval(f"window.AiluneBridge && window.AiluneBridge.setExpression({_js(name)});")
            return
        if kind == "motion":
            group = str(command.get("group") or "")[:80]
            try:
                index = int(command.get("index") or 0)
            except (TypeError, ValueError):
                index = 0
            self._eval(
                f"window.AiluneBridge && window.AiluneBridge.playMotion({_js(group)}, {_js(index)});"
            )
            return
        if kind == "speaking":
            self._eval(
                f"window.AiluneBridge && window.AiluneBridge.setSpeaking({_js(bool(command.get('value')))});"
            )
            return
        if kind == "mouth":
            try:
                value = max(0.0, min(1.0, float(command.get("value") or 0)))
            except (TypeError, ValueError):
                value = 0.0
            self._eval(f"window.AiluneBridge && window.AiluneBridge.setMouth({_js(value)});")
            return
        if kind == "reload":
            if self.webview is not None:
                self.webview.reload()
            return
        if kind == "menu":
            try:
                x = int(command.get("x") or self.layout["x"] + BASE_SIZE * self.layout["scale"] / 2)
                y = int(command.get("y") or self.layout["y"] + BASE_SIZE * self.layout["scale"] / 2)
            except (TypeError, ValueError):
                x, y = 200, 200
            self._eval(
                f"window.AiluneBridge && window.AiluneBridge.openMenuAt({_js(x)}, {_js(y)});"
            )
            return

    # ------------------------------------------------------------------ lifecycle

    def _run_io(self, fn: Any, *args: Any) -> None:
        try:
            self._executor.submit(fn, *args)
        except RuntimeError:
            pass

    def _quit_via_core(self) -> None:
        if not self.client.action("quit"):
            GLib.idle_add(self.application.quit)

    def shutdown(self) -> None:
        self.stop_event.set()
        self.server.stop()
        self._executor.shutdown(wait=False, cancel_futures=True)


def _js(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def main() -> int:
    logging.basicConfig(
        level=logging.INFO if os.environ.get("AILUNE_DEBUG") != "1" else logging.DEBUG,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not os.environ.get("WAYLAND_DISPLAY"):
        logger.error("the pet shell requires a Wayland session (WAYLAND_DISPLAY is unset)")
        return 1

    app = Gtk.Application(application_id="dev.ailune.Pet")
    shell: PetShell | None = None

    def activate(_app: Gtk.Application) -> None:
        nonlocal shell
        try:
            if shell is None:
                shell = PetShell(app)
                app.connect("shutdown", lambda _app: shell.shutdown() if shell else None)
            shell.build()
        except Exception:
            logger.exception("could not create the pet window")
            app.quit()

    app.connect("activate", activate)

    def quit_handler() -> bool:
        app.quit()
        return False

    try:
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, quit_handler)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, quit_handler)
    except Exception:
        pass
    return app.run([]) or 0
