"""The relay desktop app: a system-tray window that supervises the headless relay.

One pywebview window (the control panel) + a pystray system-tray icon. The relay itself runs as a
separate `serve` child process that this app starts and supervises via setup.start_serve/stop_serve - so
the existing headless serve, its relay.pid, and the self-updater's swap-and-restart all keep working
unchanged, and only `serve` holds the single backend connection.

UX: minimize hides the window to the tray (the relay keeps running); the window's X asks
"Shut down the relay? GP will stop" and, if confirmed, stops the relay and quits; the tray 'Open' brings
the window back, the tray 'Shut down' quits. Autostart launches this minimized to the tray (PR C).

Single instance (packaged exe only; see ucnexus_relay.single_instance): before opening a window, run() runs
a gate. A newer exe launched from anywhere promotes itself over the installed exe and relaunches from the
install dir; otherwise the process either becomes the sole owner (writing app.lock + a loopback control
server), focuses the already-running instance, or evicts an older one and takes over.
"""

import os
import sys
import threading
import time
from pathlib import Path

from . import setup, single_instance
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
        self._mutex = None  # single_instance.MutexResult while we own the app slot
        self._control = None  # single_instance.ControlServer answering ping / show / quit_for_upgrade

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
        self._release_single_instance()
        try:
            if self._tray is not None:
                self._tray.stop()
        except Exception:
            logger.exception("error stopping the tray")

    def _release_single_instance(self) -> None:
        """Give up the app slot: drop app.lock, stop the control server, release the mutex. Runs on every
        teardown path (X-close, tray 'Shut down', and the quit_for_upgrade handoff) so a newcomer sees the
        slot freed."""
        try:
            single_instance.clear_lock(self._install_dir())
        except Exception:
            logger.exception("error clearing app.lock")
        try:
            if self._control is not None:
                self._control.stop()
        except Exception:
            logger.exception("error stopping the control server")
        try:
            single_instance.release_mutex(self._mutex)
        except Exception:
            logger.exception("error releasing the single-instance mutex")
        self._mutex = None

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

    # --- single instance ------------------------------------------------------------------------------

    def _ipc_show(self) -> None:
        """A newcomer asked us to surface (it already granted us foreground rights). Restore the window and
        pull it to the front."""
        self._show_window()
        single_instance.bring_to_front()

    def _ipc_quit(self) -> None:
        """A newer instance is taking over: tear down WITHOUT the shutdown-confirm dialog, then guarantee we
        exit so our exe lock frees for the swap (mirrors the updater's hard-exit fallback)."""
        logger.info("relay app evicted by a newer instance; shutting down for handoff")
        self.shutdown()
        timer = threading.Timer(2.0, lambda: os._exit(0))
        timer.daemon = True
        timer.start()

    def _maybe_promote(self, force: bool) -> bool:
        """If this frozen exe was launched from OUTSIDE the install dir, converge on the installed exe:
        promote (swap self in + relaunch) when we're newer / forced / there's no install yet, otherwise
        delegate to the installed exe. Returns True if the caller should exit (we handed off)."""
        cfg_dir = self._install_dir()
        me = Path(sys.executable)
        installed = single_instance.installed_exe_path(cfg_dir)
        # Short-circuit the common case (launched from the install dir) before probing the installed exe's
        # build, so a normal startup never spawns a `print-build` subprocess.
        if single_instance.same_path(me, installed):
            return False
        my_build = single_instance.current_build()
        decision = single_instance.promote_decision(
            frozen=True,
            same_path=False,
            installed_build=single_instance.installed_build(cfg_dir),
            my_build=my_build,
            force=force,
        )
        if decision == "skip":
            return False
        if decision == "delegate":
            # the installed exe is same/newer: surface it if it's running, else launch it. Never run from here.
            owner = single_instance.live_owner(cfg_dir)
            if owner is not None:
                single_instance.allow_foreground(owner["pid"])
                single_instance.send_show(owner["port"], owner["nonce"])
                logger.info("installed relay is current and running; focused it instead of running from %s", me)
            else:
                single_instance.launch_installed(cfg_dir)
                logger.info("installed relay is current; launched it instead of running from %s", me)
            return True
        # promote: evict a running (installed) owner so its exe unlocks, swap, relaunch from the install dir
        owner = single_instance.live_owner(cfg_dir)
        if owner is not None:
            single_instance.evict(owner, cfg_dir)
        res = single_instance.promote_swap(me, cfg_dir)
        if not res.get("ok"):
            logger.error("promote failed (%s); running in place from %s", res.get("error"), me)
            return False  # fall back to running from where we are rather than not running at all
        single_instance.refresh_autostart_if_present(cfg_dir)
        single_instance.launch_installed(cfg_dir)
        logger.info("promoted %s -> %s (build %s) and relaunched", me, installed, my_build)
        return True

    def _acquire_single_instance(self, force: bool) -> bool:
        """Become the single app owner, or signal an existing one and bow out. Returns True to proceed as
        owner, False if the caller should exit (we focused / handed off to another instance)."""
        cfg_dir = self._install_dir()
        my_build = single_instance.current_build()

        owner = single_instance.live_owner(cfg_dir)
        evicted = False
        if owner is not None:
            if single_instance.decide_action(my_build, owner["build"], force) == "focus":
                single_instance.allow_foreground(owner["pid"])
                single_instance.send_show(owner["port"], owner["nonce"])
                logger.info("relay already running (build %s); brought it to the front", owner["build"])
                return False
            logger.info("newer relay launched; evicting the running build %s", owner["build"])
            single_instance.evict(owner, cfg_dir)
            evicted = True

        # serialise cold-start races: whoever creates the mutex first owns the slot. This only matters when
        # we did NOT just evict an owner - after an eviction the mutex may still exist (the outgoing owner's
        # handle closes a beat after its control server stops), and we're the rightful owner regardless.
        self._mutex = single_instance.acquire_mutex()
        if not evicted and not self._mutex.acquired and not force:
            rival = single_instance.wait_for_owner(cfg_dir)
            if rival is not None:
                single_instance.allow_foreground(rival["pid"])
                single_instance.send_show(rival["port"], rival["nonce"])
                logger.info("lost the startup race; brought the winning instance to the front")
                single_instance.release_mutex(self._mutex)
                self._mutex = None
                return False  # the rival is the owner

        nonce = single_instance.new_nonce()
        self._control = single_instance.ControlServer(
            build=my_build, nonce=nonce, on_show=self._ipc_show, on_quit=self._ipc_quit
        )
        port = self._control.start()
        single_instance.write_lock(
            cfg_dir, pid=os.getpid(), build=my_build, exe_path=sys.executable, control_port=port, nonce=nonce
        )
        return True

    # --- run ------------------------------------------------------------------------------------------

    def run(self, minimized: bool = False, force: bool = False) -> int:
        import webview

        global _APP
        _APP = self
        # Single-instance + promote gate. Only meaningful for the packaged exe: a dev run has
        # sys.executable = python (no exe to promote/relaunch, build 'dev'), so keep today's behaviour there.
        if getattr(sys, "frozen", False):
            if self._maybe_promote(force):
                return 0
            if not self._acquire_single_instance(force):
                return 0
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


def run_app(minimized: bool = False, force: bool = False) -> int:
    return RelayApp().run(minimized=minimized, force=force)
