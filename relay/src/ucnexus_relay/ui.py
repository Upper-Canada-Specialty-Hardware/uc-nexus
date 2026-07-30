"""Native desktop UI for the relay (pywebview window).

Purpose (per the product goal): guided first-time setup, updates, and event-log viewing. This first slice
is the always-available status + event-log window; the setup wizard and the updater land on top of it.

Model: the relay runs headless in the background (the autostarted `serve` process). This `ui` process is a
SEPARATE window that observes + (later) controls it. It reads the same on-disk config.toml and relay.log the
serve process uses, and probes the local /health endpoint - so it works whether or not the relay is running,
which matters for first-run setup when nothing is serving yet.

The window talks to Python through pywebview's js_api bridge (Api below); the data-gathering functions are
plain and importable without a display, so they unit-test without opening a window. `webview` is imported
lazily inside run_ui() for the same reason (and so a headless test host never needs the GUI backend).
"""

import json
import re
import sys
import tomllib
import urllib.request
from pathlib import Path

from pydantic import ValidationError as PydanticValidationError

from . import __version__ as VERSION
from . import autostart, updater
from .config import ChannelCfg, DEFAULT_CONFIG_PATH, KNOWN_COMPANIES, SqlCfg, primary_url


def _resolve_log_path(config_path: Path, logging_file: str) -> Path:
    """The relay writes [logging].file relative to its working dir, which for the installed relay is the
    dir holding config.toml (Start-Process -WorkingDirectory %LOCALAPPDATA%\\UCNexusRelay). Resolve the log
    beside config.toml so the UI reads the same file the serve process writes, wherever it's launched from."""
    p = Path(logging_file)
    return p if p.is_absolute() else config_path.parent / p


def config_summary(config_path: str | Path | None = None) -> dict:
    """Non-secret view of config.toml for the status panel. Never returns the shared_secret value - only
    whether one is set (enrolled). Tolerant of a missing or unparseable file (first-run has neither)."""
    p = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if not p.exists():
        return {"present": False, "path": str(p)}
    try:
        with open(p, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        return {"present": True, "path": str(p), "parse_error": str(e)}

    gp = data.get("gp") or {}
    # infra (SQL, channel) is baked into config.py, not written to config.toml - overlay the baked
    # defaults so the read-only display shows the EFFECTIVE values; a file override (dev) still wins.
    sql = {**SqlCfg().model_dump(), **(data.get("sql") or {})}
    # backend_url may be one URL or a list of them (#414). Build the model so the baked defaults fill
    # any gap and `backend_urls` does the normalizing; a malformed value falls back to the defaults
    # rather than breaking the whole status panel.
    try:
        channel_cfg = ChannelCfg(**(data.get("channel") or {}))
    except PydanticValidationError:
        channel_cfg = ChannelCfg()
    backend_urls = channel_cfg.backend_urls
    server = data.get("server") or {}
    auth = data.get("auth") or {}
    secret = auth.get("shared_secret") or ""
    return {
        "present": True,
        "path": str(p),
        "default_company": gp.get("default_company"),
        "allowed_companies": gp.get("allowed_companies") or [],
        "sql_server": sql.get("server"),
        "odbc_driver": sql.get("driver"),
        # Singular, and the PRIMARY (production) URL rather than merely the first configured one: it is
        # what the enroll wizard derives its GraphQL endpoint from, and enrolling against a PR
        # environment would rotate the workstation's secret away from production. The per-channel list
        # the status panel renders comes from /health (channel.channel_state_snapshot), which knows each
        # channel's live state - a second copy of the URLs here would have no consumer.
        "backend_url": primary_url(backend_urls),
        "host": server.get("host", "127.0.0.1"),
        "port": server.get("port", 7321),
        "enrolled": bool(secret),
        "logging_file": (data.get("logging") or {}).get("file", "relay.log"),
    }


def relay_health(host: str = "127.0.0.1", port: int = 7321) -> dict:
    """Probe the local relay /health. `running` is False if nothing answers (relay stopped / first-run)."""
    url = f"http://{host}:{port}/health"
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:  # noqa: S310 (fixed localhost URL)
            body = json.loads(resp.read().decode())
        return {
            "running": True,
            "status": body.get("status"),
            "version": body.get("version"),
            "uptime_seconds": body.get("uptime_seconds"),
            "channel": body.get("channel"),  # the serve process's REAL backend-channel state
        }
    except (OSError, json.JSONDecodeError):
        return {"running": False}


def _tail_lines(path: Path, limit: int) -> list[str]:
    if not path.exists():
        return []
    # Read only a bounded tail from the END rather than the whole file. relay.log is capped at ~2MB by
    # rotation (logging_setup), and the UI polls this every few seconds, so reading megabytes for the last
    # N events is wasteful. Grab ~400 bytes per requested line from the end, drop the partial first line.
    approx = max(int(limit), 1) * 400
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        start = max(0, size - approx)
        f.seek(start)
        data = f.read()
    lines = data.decode("utf-8", errors="replace").splitlines()
    if start > 0 and lines:
        lines = lines[1:]  # first line is likely truncated by the offset read
    return lines[-limit:]


def recent_log_events(config_path: str | Path | None = None, limit: int = 200) -> list[dict]:
    """Parse the last `limit` relay.log lines (structured JSON) into UI rows, newest last. A non-JSON line
    (shouldn't happen with the JSON formatter, but be safe) becomes a raw row."""
    summ = config_summary(config_path)
    p = Path(summ["path"])
    log_path = _resolve_log_path(p, summ.get("logging_file", "relay.log"))
    rows: list[dict] = []
    for line in _tail_lines(log_path, limit):
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
            rows.append(
                {
                    "time": o.get("asctime"),
                    "level": o.get("levelname"),
                    "message": o.get("message"),
                    "category": o.get("category"),
                    "detail": o.get("path") or o.get("op") or o.get("error"),
                }
            )
        except json.JSONDecodeError:
            rows.append({"time": None, "level": "RAW", "message": line, "category": None, "detail": None})
    return rows


def channel_state(config_path: str | Path | None = None) -> dict:
    """Infer the live channel state from the newest channel-related log event. The #204 fix tags a failed
    connect with a `category` (secret_rejected / slot_busy / dropped); a clean socket close is tagged
    closed_clean (#384); a success logs 'channel connected'.
    Returns state in {connected, secret_rejected, slot_busy, disconnected, unknown}."""
    for row in reversed(recent_log_events(config_path, limit=400)):
        msg = (row.get("message") or "").lower()
        cat = row.get("category")
        if "channel connected" in msg:
            return {"state": "connected", "at": row.get("time")}
        # closed_clean has to be listed here, not left to fall through: it is a DISCONNECT, and an
        # unrecognised category walks further back in the log to the "channel connected" that opened
        # the socket which just closed - so the panel would report a dead channel as connected (#384).
        if cat in ("secret_rejected", "slot_busy", "dropped", "closed_clean"):
            mapped = cat if cat in ("secret_rejected", "slot_busy") else "disconnected"
            return {"state": mapped, "at": row.get("time"), "message": row.get("message")}
        if "channel connection dropped" in msg:  # pre-#204 relays logged this without a category
            return {"state": "disconnected", "at": row.get("time")}
    return {"state": "unknown"}


def gather_status(config_path: str | Path | None = None) -> dict:
    """Everything the status panel shows, in one call."""
    cfg = config_summary(config_path)
    health = relay_health(cfg.get("host", "127.0.0.1"), cfg.get("port", 7321)) if cfg.get("present") else relay_health()
    # Backend-channel state: trust the serve process's LIVE report (/health.channel). If serve isn't
    # running the channel can't be up (it lives inside serve) -> disconnected. Fall back to the log
    # inference only if a running serve didn't report a channel (an older serve build).
    if not health.get("running"):
        channel = {"state": "disconnected", "channels": []}
    elif health.get("channel"):
        # `state` is the PRIMARY channel's, which is what the header dot has always meant. `channels`
        # is the per-URL detail a multi-channel relay reports (#414); a serve build that predates it
        # simply reports none and the panel shows the single-channel view, as before.
        channel = {
            "state": health["channel"].get("state", "unknown"),
            "channels": health["channel"].get("channels") or [],
        }
    else:
        channel = {**channel_state(config_path), "channels": []}
    return {
        "ui_version": VERSION,
        "build": updater.current_build(),
        "known_companies": KNOWN_COMPANIES,  # dev-determined options for the Setup company dropdowns
        "config": cfg,
        "relay": health,
        "channel": channel,
        "autostart": autostart.autostart_status() if autostart.winreg is not None else {"installed": None},
    }


def _frozen() -> bool:
    return getattr(sys, "frozen", False)


def _enroll_url_from_channel() -> str:
    """The enroll GraphQL URL derived from the baked channel.backend_url so the operator supplies only the
    token: wss://host/relay-link -> https://host/graphql (ws:// -> http://). '' if none is configured."""
    backend = config_summary().get("backend_url") or ChannelCfg().backend_url
    m = re.match(r"(wss?)://([^/]+)", backend or "")
    if not m:
        return ""
    scheme = "https" if m.group(1) == "wss" else "http"
    return f"{scheme}://{m.group(2)}/graphql"


class Api:
    """Exposed to the window's JS as window.pywebview.api. Methods must return JSON-serializable values.
    The setup-wizard methods below back the guided first-run flow; each returns a small {ok/...} dict the
    JS renders inline, and never raises across the bridge (a raised exception surfaces to JS as a rejected
    promise with no detail)."""

    def get_status(self) -> dict:
        return gather_status()

    def get_logs(self, limit: int = 200) -> list[dict]:
        return recent_log_events(limit=int(limit))

    # --- setup wizard ---------------------------------------------------------------------------------

    def save_config(self, fields: dict) -> dict:
        """Write config.toml from the wizard form (preserving an already-enrolled secret). See setup.py."""
        from . import setup

        try:
            return setup.write_config(fields or {}, DEFAULT_CONFIG_PATH)
        except Exception as e:  # noqa: BLE001 - report, don't cross the bridge as a rejected promise
            return {"ok": False, "error": str(e)}

    def test_connection(self) -> dict:
        """Read-only GP connectivity + identity probe against the saved config."""
        from . import setup

        try:
            return setup.test_gp_connection(DEFAULT_CONFIG_PATH)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def enroll(self, token: str) -> dict:
        """Register this install with UC Nexus using a one-time token, writing the DPAPI-encrypted secret.
        The backend URL is derived from the baked channel.backend_url (dev-determined), so the operator
        only supplies the token."""
        from .enroll import EnrollError, enroll_relay

        if not (token or "").strip():
            return {"ok": False, "error": "an enrollment token is required"}
        backend_url = _enroll_url_from_channel()
        if not backend_url:
            return {"ok": False, "error": "no backend URL is configured in the relay build"}
        try:
            return enroll_relay(token=token.strip(), backend_url=backend_url, config_path=str(DEFAULT_CONFIG_PATH))
        except EnrollError as e:
            return {"ok": False, "error": e.message, "detail": e.detail}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def install_autostart(self) -> dict:
        if not _frozen():
            return {"ok": False, "error": "autostart can only be registered from the packaged exe"}
        try:
            return {"ok": True, "command": autostart.install_autostart()}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def start_relay(self) -> dict:
        """Launch the serve process now (idempotent: no-op if it's already answering /health)."""
        from . import setup

        cfg = config_summary()
        if relay_health(cfg.get("host", "127.0.0.1"), cfg.get("port", 7321)).get("running"):
            return {"ok": True, "already_running": True}
        if not _frozen():
            return {"ok": False, "error": "the relay can only be started from the packaged exe"}
        try:
            return setup.start_serve(sys.executable, DEFAULT_CONFIG_PATH.parent)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def stop_relay(self) -> dict:
        from . import setup

        try:
            return setup.stop_serve(DEFAULT_CONFIG_PATH.parent)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def restart_relay(self) -> dict:
        """Restart the relay so it re-reads config (e.g. after enrolling). In the tray app this restarts
        the supervised serve child; standalone it stop+starts serve directly."""
        from . import app, setup

        running = app.current()
        if running is not None:
            running.restart_serve()
            return {"ok": True}
        setup.stop_serve(DEFAULT_CONFIG_PATH.parent)
        if _frozen():
            setup.start_serve(sys.executable, DEFAULT_CONFIG_PATH.parent)
        return {"ok": True}

    def shutdown_app(self) -> dict:
        """Stop the relay and quit the desktop app (the Status/tray 'Shut down'). The JS confirms first.
        user_shutdown so an in-flight update is cancelled rather than relaunched."""
        from . import app

        running = app.current()
        if running is None:
            return {"ok": False, "error": "not running as the desktop app"}
        running.user_shutdown()
        return {"ok": True}

    def uninstall_autostart(self) -> dict:
        try:
            existed = autostart.uninstall_autostart()
            return {"ok": True, "existed": existed}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    # --- updater ---------------------------------------------------------------------------------------

    def check_update(self) -> dict:
        try:
            return updater.check_update()
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def apply_update(self, url: str, build: str | None = None) -> dict:
        if not _frozen():
            return {"ok": False, "error": "updates can only be applied to the packaged exe"}
        if not (url or "").strip():
            return {"ok": False, "error": "no download URL"}
        from . import app

        running = app.current()
        try:
            if running is None:
                # standalone (not the desktop app): the hardened in-process swap
                return updater.apply_update(url.strip(), DEFAULT_CONFIG_PATH.parent)
            # desktop app: stage the update, then shut ourselves down so the helper can swap the now-
            # unlocked exe and relaunch - no renaming of a running exe. The app owns that sequence
            # (RelayApp.begin_update) because the background update poller has to run the same one.
            return running.begin_update(url, build)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def last_update_result(self) -> dict:
        """The last update outcome from the ledger (update-state.json), so the Updates tab can show
        'updated to build N' or a failure - instead of a silent mystery. {} if no update was ever run."""
        try:
            return updater.read_ledger(DEFAULT_CONFIG_PATH.parent)
        except Exception:  # noqa: BLE001
            return {}


_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>UC Nexus Relay</title>
<style>
  :root { color-scheme: dark; }
  body { font-family: 'Segoe UI', system-ui, sans-serif; margin: 0; background:#12151c; color:#e6e8ee; }
  header { padding:14px 18px; background:#0d1017; border-bottom:1px solid #232838; display:flex; align-items:center; gap:12px; }
  header h1 { font-size:16px; margin:0; font-weight:600; }
  .dot { width:11px; height:11px; border-radius:50%; background:#5a6072; box-shadow:0 0 0 3px rgba(255,255,255,0.04); }
  .dot.ok { background:#2ecc71; } .dot.bad { background:#e74c3c; } .dot.warn { background:#f39c12; }
  nav { display:flex; gap:4px; }
  .tab { background:transparent; border:1px solid transparent; color:#8b93a7; padding:4px 12px; border-radius:7px; cursor:pointer; font-size:12.5px; }
  .tab.active { background:#20283a; color:#e6e8ee; border-color:#2c364b; }
  main { padding:16px 18px; }
  .card { background:#171b24; border:1px solid #232838; border-radius:10px; padding:14px 16px; margin-bottom:16px; }
  .card h2 { font-size:12px; text-transform:uppercase; letter-spacing:.06em; color:#8b93a7; margin:0 0 10px; }
  .grid { display:grid; grid-template-columns:auto 1fr; gap:6px 16px; font-size:13px; }
  .grid .k { color:#8b93a7; } .grid .v { color:#e6e8ee; word-break:break-all; }
  .pill { display:inline-block; padding:1px 8px; border-radius:999px; font-size:12px; }
  .pill.ok { background:rgba(46,204,113,.15); color:#5be29a; } .pill.bad { background:rgba(231,76,60,.15); color:#f0857b; }
  .pill.warn { background:rgba(243,156,18,.15); color:#f6bd5b; }
  table { width:100%; border-collapse:collapse; font-size:12.5px; }
  th { text-align:left; color:#8b93a7; font-weight:500; padding:4px 8px; position:sticky; top:0; background:#171b24; }
  td { padding:3px 8px; border-top:1px solid #1f2431; vertical-align:top; }
  .lvl { font-weight:600; } .lvl.INFO{color:#7fb2ff;} .lvl.WARNING{color:#f6bd5b;} .lvl.ERROR{color:#f0857b;} .lvl.RAW{color:#8b93a7;}
  .logwrap { max-height:340px; overflow:auto; }
  .bar { display:flex; align-items:center; gap:10px; margin-bottom:10px; }
  button { background:#20283a; color:#cdd3e1; border:1px solid #2c364b; border-radius:7px; padding:5px 12px; cursor:pointer; font-size:12.5px; }
  button:hover { background:#28324a; }
  .muted { color:#6b7386; font-size:12px; }
  .form { display:grid; gap:10px; margin:6px 0 10px; }
  .form label { display:flex; flex-direction:column; gap:4px; font-size:11.5px; color:#8b93a7; }
  .form input { background:#0f131b; border:1px solid #2c364b; border-radius:6px; color:#e6e8ee; padding:7px 9px; font-size:13px; }
  .form input:focus, .form select:focus { outline:none; border-color:#3a4a6b; }
  .form select { background:#0f131b; border:1px solid #2c364b; border-radius:6px; color:#e6e8ee; padding:7px 9px; font-size:13px; }
  .fld { display:flex; flex-direction:column; gap:4px; }
  .fld .lbl { font-size:11.5px; color:#8b93a7; }
  .checks { display:flex; flex-wrap:wrap; gap:12px; padding:2px 0; }
  .checks label { display:flex; flex-direction:row; align-items:center; gap:5px; font-size:12.5px; color:#cdd3e1; }
  .step { display:flex; align-items:center; gap:8px; font-weight:600; font-size:13px; margin:16px 0 6px; }
  .stepn { display:inline-flex; width:20px; height:20px; align-items:center; justify-content:center; border-radius:50%; background:#20283a; color:#7fb2ff; font-size:12px; }
  .actions { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:4px; }
  .result { font-size:12.5px; min-height:16px; margin:2px 0 4px; }
  .result .ok { color:#5be29a; } .result .bad { color:#f0857b; }
</style></head>
<body>
  <header><span id="hdot" class="dot"></span><h1>UC Nexus Relay</h1><span id="hstate" class="muted"></span>
    <span style="flex:1"></span>
    <nav><button id="tab-status" class="tab active" onclick="showView('status')">Status</button>
      <button id="tab-setup" class="tab" onclick="showView('setup')">Setup</button>
      <button id="tab-updates" class="tab" onclick="showView('updates')">Updates</button></nav>
    <span id="uiver" class="muted"></span></header>
  <main>
    <section id="view-status">
      <div class="card"><h2>Status</h2><div id="status" class="grid"></div></div>
      <div class="card">
        <h2>Controls</h2>
        <label class="muted"><input type="checkbox" id="c-autostart" onchange="toggleAutostart()"> start at logon</label>
        <div class="actions" style="margin-top:8px">
          <button onclick="restartRelay()">Restart relay</button>
          <button onclick="shutDown()">Shut down</button></div>
        <div id="r-ctl" class="result"></div>
      </div>
      <div class="card">
        <div class="bar"><h2 style="margin:0">Event log</h2><span style="flex:1"></span>
          <label class="muted"><input type="checkbox" id="auto" checked> auto-refresh</label>
          <button onclick="refresh()">Refresh</button></div>
        <div class="logwrap"><table><thead><tr><th>Time</th><th>Level</th><th>Message</th><th>Detail</th></tr></thead>
          <tbody id="logs"></tbody></table></div>
      </div>
    </section>
    <section id="view-setup" hidden>
      <div class="card">
        <h2>Guided setup</h2>
        <p class="muted" style="margin:0 0 4px">Choose the GP company, test the connection, then enroll. Start-at-logon and shut down live on the Status tab.</p>
        <div class="step"><span class="stepn">1</span> GP company</div>
        <div class="form">
          <div class="fld"><span class="lbl">Allowed companies</span><div id="f-allowed-box" class="checks"></div></div>
          <label>Default company<select id="f-defco"></select></label>
        </div>
        <div class="actions">
          <button onclick="saveConfig()">Save configuration</button>
          <button onclick="testConn()">Test GP connection</button></div>
        <div id="r-save" class="result"></div>
        <div id="r-test" class="result"></div>
        <div class="step"><span class="stepn">2</span> Enroll with UC Nexus</div>
        <div class="form">
          <label>Enrollment token<input id="f-token" placeholder="paste the one-time token from UC Nexus admin"></label></div>
        <div class="actions"><button onclick="doEnroll()">Enroll</button></div>
        <div id="r-enroll" class="result"></div>
        <div class="step">Baked configuration <span class="muted" style="font-weight:400">(set by dev)</span></div>
        <div id="baked" class="grid"></div>
      </div>
    </section>
    <section id="view-updates" hidden>
      <div class="card">
        <h2>Updates</h2>
        <div class="grid" style="margin-bottom:10px">
          <div class="k">Installed build</div><div class="v" id="u-current">-</div>
          <div class="k">Latest release</div><div class="v" id="u-latest">-</div>
        </div>
        <div class="actions">
          <button onclick="checkUpdate()">Check for updates</button>
          <button id="u-apply" onclick="applyUpdate()" hidden>Update now</button></div>
        <div id="r-update" class="result"></div>
        <p class="muted" id="u-note" style="margin:6px 0 0"></p>
        <div id="u-last" class="result" style="margin-top:6px"></div>
      </div>
    </section>
  </main>
<script>
  const $ = id => document.getElementById(id);
  const val = id => $(id).value.trim();
  const setVal = (id, v) => { $(id).value = v || ''; };
  function row(k, v) { return `<div class="k">${k}</div><div class="v">${v}</div>`; }
  function pill(ok, txt, warn) { const c = warn ? 'warn' : (ok ? 'ok' : 'bad'); return `<span class="pill ${c}">${txt}</span>`; }
  function esc(s) { return String(s == null ? '' : s).replace(/</g, '&lt;'); }
  function result(id, ok, text) { $(id).innerHTML = `<span class="${ok ? 'ok' : 'bad'}">${esc(text)}</span>`; }

  function showView(v) {
    for (const name of ['status', 'setup', 'updates']) {
      $('view-' + name).hidden = v !== name;
      $('tab-' + name).classList.toggle('active', v === name);
    }
    if (v === 'setup') loadSetup();
    if (v === 'updates') loadUpdates();
  }

  async function refresh() {
    if (!window.pywebview) return;
    const s = await window.pywebview.api.get_status();
    $('uiver').innerText = 'ui ' + s.ui_version;
    const st = s.channel.state, connected = st === 'connected';
    $('hdot').className = 'dot ' + (connected ? 'ok' : (st === 'unknown' ? '' : 'bad'));
    $('hstate').innerText = connected ? 'connected to backend' : ('channel: ' + st);
    const c = s.config, r = s.relay, a = s.autostart;
    // One row per channel, but only once there is more than one to tell apart (#414). A single-channel
    // relay - every workstation, normally - keeps the panel it has always had.
    const chans = s.channel.channels || [];
    const chanRows = chans.length > 1 ? chans.map(ch =>
      row(ch.primary ? 'Channel (production)' : 'Channel (test)',
          pill(!!ch.connected, esc(ch.state), ch.state === 'unknown') +
          ` <span class="muted">${esc(ch.url)}</span>`)).join('') : '';
    $('status').innerHTML =
      row('Build', esc(s.build) || '-') +
      row('Relay process', r.running ? pill(true,'running v'+(r.version||'?')) : pill(false,'not running')) +
      row('Backend channel', pill(connected, st, st==='unknown')) +
      row('Config', c.present ? (c.parse_error ? pill(false,'parse error') : pill(true,'loaded')) : pill(false,'not set up')) +
      row('Enrolled', c.present ? pill(!!c.enrolled, c.enrolled?'yes':'no') : '-') +
      row('Companies', (c.allowed_companies||[]).join(', ') || '-') +
      row('SQL server', c.sql_server || '-') +
      row('Backend URL', c.backend_url || '-') +
      chanRows +
      row('Autostart', a.installed===null ? '-' : pill(!!a.installed, a.installed?'installed':'not installed'));
    if ($('c-autostart')) $('c-autostart').checked = !!a.installed;
    const logs = await window.pywebview.api.get_logs(200);
    $('logs').innerHTML = logs.slice().reverse().map(l =>
      `<tr><td class="muted">${esc(l.time)}</td><td class="lvl ${l.level||''}">${esc(l.level)}</td>`+
      `<td>${esc(l.message)}</td><td class="muted">${esc(l.detail)}</td></tr>`).join('');
  }

  function checkedAllowed() {
    return Array.from(document.querySelectorAll('#f-allowed-box input:checked')).map(i => i.value);
  }
  function renderDefaultOptions(allowed, current) {
    const cur = allowed.includes(current) ? current : (allowed[0] || '');
    $('f-defco').innerHTML = allowed.map(c => `<option value="${c}"${c === cur ? ' selected' : ''}>${c}</option>`).join('');
  }
  function onAllowedChange() { renderDefaultOptions(checkedAllowed(), $('f-defco').value); }

  async function loadSetup() {
    const s = await window.pywebview.api.get_status();
    const c = s.config || {};
    const known = s.known_companies || [];
    const allowed = c.allowed_companies || [];
    $('f-allowed-box').innerHTML = known.map(co =>
      `<label><input type="checkbox" value="${co}"${allowed.includes(co) ? ' checked' : ''} onchange="onAllowedChange()">${co}</label>`).join('');
    renderDefaultOptions(allowed.length ? allowed : known, c.default_company || (allowed[0] || known[0]));
    $('baked').innerHTML =
      row('Backend', c.backend_url || '-') +
      row('SQL server', c.sql_server || '-') +
      row('ODBC driver', c.odbc_driver || '-');
  }

  async function saveConfig() {
    const allowed = checkedAllowed();
    if (!allowed.length) { result('r-save', false, 'select at least one allowed company'); return; }
    const r = await window.pywebview.api.save_config({ allowed_companies: allowed, default_company: $('f-defco').value || allowed[0] });
    result('r-save', r.ok, r.ok ? ('saved ' + r.path) : (r.error || 'save failed'));
    refresh();
  }
  async function testConn() {
    $('r-test').innerHTML = '<span class="muted">testing…</span>';
    const r = await window.pywebview.api.test_connection();
    result('r-test', r.ok, r.ok
      ? `connected as ${r.connected_as} to ${r.database} (DYNGRP: ${r.is_member_dyngrp ? 'yes' : 'no'})`
      : (r.error || 'connection failed'));
  }
  async function doEnroll() {
    $('r-enroll').innerHTML = '<span class="muted">enrolling…</span>';
    const r = await window.pywebview.api.enroll(val('f-token'));
    result('r-enroll', r.ok, r.ok
      ? `enrolled ${r.install_id} as ${r.hostname} (${r.company}); secret written ${r.how}. restart the relay (Status tab) to use it.`
      : (r.error || 'enrollment failed'));
    refresh();
  }

  let _updateUrl = null, _updateBuild = null;
  function showLastUpdate(u) {
    if (!u || !u.status || !u.target_build) { $('u-last').innerHTML = ''; return; }
    const when = u.updated_at ? ' (' + esc(u.updated_at) + ')' : '';
    if (u.status === 'success') {
      $('u-last').innerHTML = `<span class="ok">last update: installed ${esc(u.target_build)}${when}</span>`;
    } else if (u.status === 'failed') {
      $('u-last').innerHTML = `<span class="bad">last update to ${esc(u.target_build)} failed: ${esc(u.last_error || 'unknown')}</span>`;
    } else if (u.status === 'cancelled') {
      $('u-last').innerHTML = `<span class="muted">last update to ${esc(u.target_build)} was cancelled${when}</span>`;
    } else {
      $('u-last').innerHTML = `<span class="muted">update to ${esc(u.target_build)}: ${esc(u.status)}…</span>`;
    }
  }
  async function loadUpdates() {
    const s = await window.pywebview.api.get_status();
    $('u-current').innerText = s.build || '-';
    try { showLastUpdate(await window.pywebview.api.last_update_result()); } catch (e) {}
  }
  async function checkUpdate() {
    $('r-update').innerHTML = '<span class="muted">checking…</span>';
    $('u-apply').hidden = true; _updateUrl = null; _updateBuild = null;
    const r = await window.pywebview.api.check_update();
    if (!r.ok) { result('r-update', false, r.error || 'check failed'); return; }
    $('u-current').innerText = r.current; $('u-latest').innerText = r.latest;
    if (r.update_available) {
      _updateUrl = r.url; _updateBuild = r.latest; $('u-apply').hidden = false;
      result('r-update', true, 'update available: ' + r.latest);
    } else {
      result('r-update', true, 'up to date');
    }
  }
  async function applyUpdate() {
    if (!_updateUrl) return;
    $('r-update').innerHTML = '<span class="muted">downloading and applying… the app will close and reopen on the new version</span>';
    $('u-apply').hidden = true;
    const r = await window.pywebview.api.apply_update(_updateUrl, _updateBuild);
    result('r-update', r.ok, r.ok ? 'updating - the app will close and reopen on the new version' : (r.error || 'update failed'));
    $('u-note').innerText = r.note || '';
    setTimeout(refresh, 2000);
  }

  async function toggleAutostart() {
    const on = $('c-autostart').checked;
    const r = on ? await window.pywebview.api.install_autostart() : await window.pywebview.api.uninstall_autostart();
    result('r-ctl', r.ok, r.ok ? ('start at logon ' + (on ? 'on' : 'off')) : (r.error || 'failed'));
    refresh();
  }
  async function restartRelay() {
    $('r-ctl').innerHTML = '<span class="muted">restarting the relay…</span>';
    const r = await window.pywebview.api.restart_relay();
    result('r-ctl', r.ok, r.ok ? 'relay restarting' : (r.error || 'failed'));
    setTimeout(refresh, 3000);
  }
  async function shutDown() {
    if (!confirm('Shut down the relay? Cloud GP operations will stop until it is started again.')) return;
    await window.pywebview.api.shutdown_app();
  }

  window.addEventListener('pywebviewready', () => { refresh(); setInterval(() => { if ($('auto').checked) refresh(); }, 3000); });
</script></body></html>"""
