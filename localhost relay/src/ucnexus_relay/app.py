"""The relay desktop app: a system-tray window that supervises the headless relay.

One pywebview window (the control panel) + a pystray system-tray icon. The relay itself runs as a
separate `serve` child process that this app starts and supervises via setup.start_serve/stop_serve - so
the existing headless serve, its relay.pid, and the self-updater's swap-and-restart all keep working
unchanged, and only `serve` holds the single backend connection.

UX: minimize hides the window to the tray (the relay keeps running); the window's X asks
"Shut down the relay? GP will stop" and, if confirmed, stops the relay and quits; the tray 'Open' brings
the window back, the tray 'Shut down' quits. Autostart launches this minimized to the tray (PR C).
"""

import sys
import threading
import time

from . import setup
from .config import DEFAULT_CONFIG_PATH
from .logging_setup import get_logger
from .ui import Api, _HTML, config_summary, relay_health

logger = get_logger()

_APP: "RelayApp | None" = None


def current() -> "RelayApp | None":
    """The running RelayApp, so ui.Api.shutdown_app / restart_relay can reach it (None outside app mode)."""
    return _APP


class RelayApp:
    def __init__(self) -> None:
        self._window = None
        self._tray = None
        self._shutting_down = False

    # --- serve child supervision ----------------------------------------------------------------------

    def _install_dir(self):
        return DEFAULT_CONFIG_PATH.parent

    def _serve_running(self) -> bool:
        cfg = config_summary()
        return relay_health(cfg.get("host", "127.0.0.1"), cfg.get("port", 7321)).get("running", False)

    def ensure_serve(self) -> None:
        """Start the serve child if it isn't already answering /health. Only from the packaged exe (a dev
        run has no exe to spawn)."""
        if self._serve_running() or not getattr(sys, "frozen", False):
            return
        setup.start_serve(sys.executable, self._install_dir())

    def restart_serve(self) -> None:
        """Stop + start the serve child so it re-reads config (picks up a freshly enrolled secret)."""
        setup.stop_serve(self._install_dir())
        time.sleep(1.5)  # let port 7321 free before the fresh serve binds it
        if getattr(sys, "frozen", False):
            setup.start_serve(sys.executable, self._install_dir())

    # --- lifecycle ------------------------------------------------------------------------------------

    def _stop_relay_and_tray(self) -> None:
        try:
            setup.stop_serve(self._install_dir())
        except Exception:
            logger.exception("error stopping the relay on shutdown")
        try:
            if self._tray is not None:
                self._tray.stop()
        except Exception:
            logger.exception("error stopping the tray")

    def shutdown(self) -> None:
        """Stop the relay + tray and close the window (used by the tray/Status 'Shut down')."""
        if self._shutting_down:
            return
        self._shutting_down = True
        self._stop_relay_and_tray()
        try:
            if self._window is not None:
                self._window.destroy()
        except Exception:
            logger.exception("error destroying the window")

    def _confirm_shutdown(self) -> bool:
        try:
            return bool(
                self._window.create_confirmation_dialog(
                    "Shut down the relay?",
                    "Cloud GP operations will stop until the relay is started again.",
                )
            )
        except Exception:
            logger.exception("confirmation dialog failed; honoring the close")
            return True

    # --- window + tray events -------------------------------------------------------------------------

    def _on_minimized(self) -> None:
        try:
            self._window.hide()  # minimize hides to the tray; the relay keeps running
        except Exception:
            logger.exception("error hiding the window on minimize")

    def _on_closing(self) -> bool:
        # X on the window: confirm, then either allow the close (after stopping the relay) or cancel it.
        if self._shutting_down:
            return True
        if self._confirm_shutdown():
            self._shutting_down = True
            self._stop_relay_and_tray()  # the window closes naturally via the returned True
            return True
        return False

    def _show_window(self) -> None:
        try:
            self._window.show()
            self._window.restore()
        except Exception:
            logger.exception("error showing the window")

    def _build_tray(self) -> None:
        import pystray
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (64, 64), (13, 16, 23))
        ImageDraw.Draw(img).ellipse((16, 16, 48, 48), fill=(46, 204, 113))
        menu = pystray.Menu(
            pystray.MenuItem("Open", lambda: self._show_window(), default=True),
            pystray.MenuItem("Shut down", lambda: self.shutdown()),
        )
        self._tray = pystray.Icon("ucnexus-relay", img, "UC Nexus Relay", menu)

    def run(self, minimized: bool = False) -> int:
        import webview

        global _APP
        _APP = self
        self.ensure_serve()
        self._window = webview.create_window(
            "UC Nexus Relay",
            html=_HTML,
            js_api=Api(),
            width=760,
            height=680,
            min_size=(560, 480),
            hidden=minimized,
        )
        self._window.events.minimized += self._on_minimized
        self._window.events.closing += self._on_closing
        self._build_tray()
        threading.Thread(target=self._tray.run, daemon=True).start()
        webview.start()  # blocks on the GUI loop until the window is destroyed
        return 0


def run_app(minimized: bool = False) -> int:
    return RelayApp().run(minimized=minimized)
