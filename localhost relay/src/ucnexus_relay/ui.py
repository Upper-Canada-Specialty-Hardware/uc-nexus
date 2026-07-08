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
import sys
import tomllib
import urllib.request
from pathlib import Path

from . import autostart, updater
from .config import DEFAULT_CONFIG_PATH

VERSION = "0.1.0"


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
    sql = data.get("sql") or {}
    channel = data.get("channel") or {}
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
        "backend_url": channel.get("backend_url") or "",
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
        }
    except (OSError, json.JSONDecodeError):
        return {"running": False}


def _tail_lines(path: Path, limit: int) -> list[str]:
    if not path.exists():
        return []
    # relay.log stays small (a few events per op); reading it whole and slicing is fine and avoids
    # seek-based tailing edge cases with the JSON-per-line format.
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.readlines()[-limit:]


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
    connect with a `category` (secret_rejected / slot_busy / dropped); a success logs 'channel connected'.
    Returns state in {connected, secret_rejected, slot_busy, disconnected, unknown}."""
    for row in reversed(recent_log_events(config_path, limit=400)):
        msg = (row.get("message") or "").lower()
        cat = row.get("category")
        if "channel connected" in msg:
            return {"state": "connected", "at": row.get("time")}
        if cat in ("secret_rejected", "slot_busy", "dropped"):
            mapped = "disconnected" if cat == "dropped" else cat
            return {"state": mapped, "at": row.get("time"), "message": row.get("message")}
        if "channel connection dropped" in msg:  # pre-#204 relays logged this without a category
            return {"state": "disconnected", "at": row.get("time")}
    return {"state": "unknown"}


def gather_status(config_path: str | Path | None = None) -> dict:
    """Everything the status panel shows, in one call."""
    cfg = config_summary(config_path)
    health = relay_health(cfg.get("host", "127.0.0.1"), cfg.get("port", 7321)) if cfg.get("present") else relay_health()
    return {
        "ui_version": VERSION,
        "build": updater.current_build(),
        "config": cfg,
        "relay": health,
        "channel": channel_state(config_path),
        "autostart": autostart.autostart_status() if autostart.winreg is not None else {"installed": None},
    }


def _frozen() -> bool:
    return getattr(sys, "frozen", False)


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

    def enroll(self, token: str, backend_url: str) -> dict:
        """Register this install with UC Nexus using a one-time token, writing the DPAPI-encrypted secret."""
        from .enroll import EnrollError, enroll_relay

        if not (token or "").strip() or not (backend_url or "").strip():
            return {"ok": False, "error": "both an enrollment token and the backend URL are required"}
        try:
            return enroll_relay(token=token.strip(), backend_url=backend_url.strip(), config_path=str(DEFAULT_CONFIG_PATH))
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

    # --- updater ---------------------------------------------------------------------------------------

    def check_update(self) -> dict:
        try:
            return updater.check_update()
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def apply_update(self, url: str) -> dict:
        if not _frozen():
            return {"ok": False, "error": "updates can only be applied to the packaged exe"}
        if not (url or "").strip():
            return {"ok": False, "error": "no download URL"}
        try:
            return updater.apply_update(url.strip(), DEFAULT_CONFIG_PATH.parent)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}


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
  .form input:focus { outline:none; border-color:#3a4a6b; }
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
        <p class="muted" style="margin:0 0 4px">Fill in the connection and backend, save, test GP, then enroll, install autostart, and start the relay.</p>
        <div class="step"><span class="stepn">1</span> GP connection + backend</div>
        <div class="form">
          <label>SQL server<input id="f-sql" placeholder="10.0.0.246,1435"></label>
          <label>SQL ODBC driver<input id="f-driver" placeholder="ODBC Driver 17 for SQL Server"></label>
          <label>Default company<input id="f-defco" placeholder="TUBC"></label>
          <label>Allowed companies (comma-separated)<input id="f-allowed" placeholder="TUBC, TUCSH"></label>
          <label>Fallback buyer (optional)<input id="f-buyer" placeholder="mira"></label>
          <label>Backend host<input id="f-host" placeholder="backend-production-7866.up.railway.app"></label>
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
        <div class="step"><span class="stepn">3</span> Autostart + run</div>
        <div class="actions">
          <button onclick="doAutostart()">Install autostart</button>
          <button onclick="startRelay()">Start relay</button>
          <button onclick="stopRelay()">Stop relay</button></div>
        <div id="r-run" class="result"></div>
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
    $('status').innerHTML =
      row('Build', esc(s.build) || '-') +
      row('Relay process', r.running ? pill(true,'running v'+(r.version||'?')) : pill(false,'not running')) +
      row('Backend channel', pill(connected, st, st==='unknown')) +
      row('Config', c.present ? (c.parse_error ? pill(false,'parse error') : pill(true,'loaded')) : pill(false,'not set up')) +
      row('Enrolled', c.present ? pill(!!c.enrolled, c.enrolled?'yes':'no') : '-') +
      row('Companies', (c.allowed_companies||[]).join(', ') || '-') +
      row('SQL server', c.sql_server || '-') +
      row('Backend URL', c.backend_url || '-') +
      row('Autostart', a.installed===null ? '-' : pill(!!a.installed, a.installed?'installed':'not installed'));
    const logs = await window.pywebview.api.get_logs(200);
    $('logs').innerHTML = logs.slice().reverse().map(l =>
      `<tr><td class="muted">${esc(l.time)}</td><td class="lvl ${l.level||''}">${esc(l.level)}</td>`+
      `<td>${esc(l.message)}</td><td class="muted">${esc(l.detail)}</td></tr>`).join('');
  }

  async function loadSetup() {
    const s = await window.pywebview.api.get_status();
    const c = s.config || {};
    if (c.present) {
      setVal('f-sql', c.sql_server); setVal('f-driver', c.odbc_driver);
      setVal('f-defco', c.default_company); setVal('f-allowed', (c.allowed_companies||[]).join(', '));
      const m = (c.backend_url||'').match(/wss:\\/\\/([^/]+)/); if (m) setVal('f-host', m[1]);
    }
  }
  function wssUrl() { const h = val('f-host'); return h ? 'wss://' + h + '/relay-link' : ''; }
  function gqlUrl() { const h = val('f-host'); return h ? 'https://' + h + '/graphql' : ''; }

  async function saveConfig() {
    const fields = {
      sql_server: val('f-sql'), sql_driver: val('f-driver'),
      default_company: val('f-defco'),
      allowed_companies: val('f-allowed').split(',').map(x => x.trim()).filter(Boolean),
      buyer_default: val('f-buyer'), backend_url: wssUrl(),
    };
    const r = await window.pywebview.api.save_config(fields);
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
    const r = await window.pywebview.api.enroll(val('f-token'), gqlUrl());
    result('r-enroll', r.ok, r.ok
      ? `enrolled ${r.install_id} as ${r.hostname} (${r.company}); secret written ${r.how}. now start/restart the relay.`
      : (r.error || 'enrollment failed'));
    refresh();
  }
  async function doAutostart() {
    const r = await window.pywebview.api.install_autostart();
    result('r-run', r.ok, r.ok ? ('autostart installed: ' + r.command) : (r.error || 'failed'));
    refresh();
  }
  async function startRelay() {
    const r = await window.pywebview.api.start_relay();
    result('r-run', r.ok, r.ok ? (r.already_running ? 'relay already running' : 'relay started') : (r.error || 'failed'));
    setTimeout(refresh, 1500);
  }
  async function stopRelay() {
    const r = await window.pywebview.api.stop_relay();
    result('r-run', r.ok, r.ok ? 'relay stopped' : (r.error || 'failed'));
    setTimeout(refresh, 1000);
  }

  let _updateUrl = null;
  async function loadUpdates() {
    const s = await window.pywebview.api.get_status();
    $('u-current').innerText = s.build || '-';
  }
  async function checkUpdate() {
    $('r-update').innerHTML = '<span class="muted">checking…</span>';
    $('u-apply').hidden = true; _updateUrl = null;
    const r = await window.pywebview.api.check_update();
    if (!r.ok) { result('r-update', false, r.error || 'check failed'); return; }
    $('u-current').innerText = r.current; $('u-latest').innerText = r.latest;
    if (r.update_available) {
      _updateUrl = r.url; $('u-apply').hidden = false;
      result('r-update', true, 'update available: ' + r.latest);
    } else {
      result('r-update', true, 'up to date');
    }
  }
  async function applyUpdate() {
    if (!_updateUrl) return;
    $('r-update').innerHTML = '<span class="muted">downloading and applying… the relay will restart</span>';
    $('u-apply').hidden = true;
    const r = await window.pywebview.api.apply_update(_updateUrl);
    result('r-update', r.ok, r.ok ? 'updated - relay restarted' : (r.error || 'update failed'));
    $('u-note').innerText = r.note || '';
    setTimeout(refresh, 2000);
  }

  window.addEventListener('pywebviewready', () => { refresh(); setInterval(() => { if ($('auto').checked) refresh(); }, 3000); });
</script></body></html>"""


def run_ui() -> int:
    """Open the native window. Blocks until the window is closed (webview.start runs the GUI loop)."""
    import webview  # lazy: only the `ui` subcommand needs the GUI backend

    webview.create_window("UC Nexus Relay", html=_HTML, js_api=Api(), width=760, height=680, min_size=(560, 480))
    webview.start()
    return 0
