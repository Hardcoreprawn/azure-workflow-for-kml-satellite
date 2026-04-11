#!/usr/bin/env python3
"""Live pipeline dashboard — kanban-style CLI monitor.

Usage:
    uv run python scripts/dashboard.py                          # use built-in defaults
    uv run python scripts/dashboard.py --host func-kmlsat-dev.jollysea-48e72cf8.uksouth.azurecontainerapps.io
    uv run python scripts/dashboard.py --app-insights 387f53d2-98ef-4fc8-9296-32fda4c74bb3

Requires: ``az`` CLI authenticated, ``rich`` Python package.
Refreshes every 10 seconds (configurable with --interval).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime

try:
    from rich.console import Console
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
except ImportError:
    print("ERROR: 'rich' is required.  pip install rich")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PHASE_ORDER = [
    "uploaded",
    "ingestion",
    "acquisition",
    "fulfilment",
    "enrichment",
    "completed",
    "failed",
]

_PHASE_STYLE = {
    "uploaded": "bold cyan",
    "ingestion": "bold yellow",
    "acquisition": "bold blue",
    "fulfilment": "bold magenta",
    "enrichment": "bold green",
    "completed": "bold green",
    "failed": "bold red",
}

_RUNTIME_TO_PHASE = {
    "Pending": "uploaded",
    "Running": None,  # use customStatus
    "Completed": "completed",
    "Failed": "failed",
    "Terminated": "failed",
    "Canceled": "failed",
    "Suspended": "uploaded",
}


def _az_query(app_id: str, query: str, timeout: int = 15) -> list[dict]:
    """Run a KQL query against App Insights via ``az monitor``."""
    try:
        proc = subprocess.run(
            [
                "az",
                "monitor",
                "app-insights",
                "query",
                "--app",
                app_id,
                "--analytics-query",
                query,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if proc.returncode != 0:
            return []
        data = json.loads(proc.stdout)
        tables = data.get("tables", [])
        if not tables:
            return []
        cols = [c["name"] for c in tables[0].get("columns", [])]
        return [dict(zip(cols, row, strict=False)) for row in tables[0].get("rows", [])]
    except Exception:
        return []


def _http_get(url: str, timeout: int = 8, headers: dict | None = None) -> dict | None:
    """Simple GET via curl (avoids extra Python deps)."""
    try:
        cmd = ["curl", "-sS", "--max-time", str(timeout)]
        if headers:
            for k, v in headers.items():
                cmd.extend(["-H", f"{k}: {v}"])
        cmd.append(url)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 2)
        if proc.returncode != 0:
            return None
        return json.loads(proc.stdout)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------


def fetch_health(host: str) -> dict:
    """Hit /api/health and return status + latency."""
    start = time.monotonic()
    result = _http_get(f"https://{host}/api/health")
    latency_ms = int((time.monotonic() - start) * 1000)
    if result:
        return {"status": "healthy", "latency_ms": latency_ms, "detail": result}
    return {"status": "unreachable", "latency_ms": latency_ms, "detail": {}}


def fetch_ops_dashboard(host: str, ops_key: str = "") -> dict | None:
    """Hit /api/ops/dashboard — returns the full ops payload or None on failure."""
    url = f"https://{host}/api/ops/dashboard"
    headers = {}
    if ops_key:
        headers["Authorization"] = f"Bearer {ops_key}"
    return _http_get(url, timeout=10, headers=headers or None)


def fetch_requests(app_id: str, minutes: int = 30) -> list[dict]:
    """Recent HTTP requests from App Insights."""
    return _az_query(
        app_id,
        f"""requests
        | where timestamp > ago({minutes}m)
        | project timestamp, name, resultCode, duration,
                  client_IP, user_AuthenticatedId
        | order by timestamp desc
        | take 20""",
    )


def fetch_errors(app_id: str, minutes: int = 60) -> list[dict]:
    """Recent errors and warnings."""
    return _az_query(
        app_id,
        f"""union traces, exceptions
        | where timestamp > ago({minutes}m)
        | where severityLevel >= 3
              or itemType == "exception"
        | project timestamp,
                  message = coalesce(message, outerMessage, ""),
                  operation_Name, severityLevel, itemType
        | order by timestamp desc
        | take 15""",
    )


def fetch_durable_instances(host: str) -> list[dict]:
    """Query the Durable Functions status endpoint for active instances.

    Requires the system key — returns empty list if unavailable (we fall
    back to App Insights traces for pipeline visibility).
    """
    url = (
        f"https://{host}/runtime/webhooks/durabletask/instances"
        f"?runtimeStatus=Running,Pending&top=20"
        f"&taskHub=TreeSightHub"
    )
    result = _http_get(url, timeout=10)
    if isinstance(result, list):
        return result
    return []


def fetch_pipeline_activity(app_id: str) -> list[dict]:
    """Correlate pipeline operations from App Insights into per-run views."""
    return _az_query(
        app_id,
        """requests
        | where timestamp > ago(6h)
        | where name has "orchestrator" or name has "pipeline"
              or name has "parse_kml" or name has "acquire"
              or name has "download" or name has "post_process"
              or name has "blob_trigger" or name has "enrich"
              or name has "submit" or name has "upload"
              or name has "write_metadata" or name has "prepare_aoi"
              or name has "store_aoi" or name has "poll"
              or name has "fulfil"
        | project timestamp, name, resultCode, duration, operation_Id, success
        | order by timestamp desc
        | take 50""",
    )


def fetch_recent_submissions(app_id: str) -> list[dict]:
    """Recent pipeline submissions (used by fetch_pipeline_activity KQL)."""
    return fetch_pipeline_activity(app_id)[:20]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _ts_short(ts: str | None) -> str:
    """Format an ISO timestamp to HH:MM:SS."""
    if not ts:
        return ""
    try:
        # Handle both full ISO and partial
        s = str(ts).replace("T", " ")[:19]
        return s[11:19] if len(s) >= 19 else s
    except Exception:
        return str(ts)[:8]


def _truncate(s: str, n: int) -> str:
    s = str(s).strip()
    return s[:n] + "…" if len(s) > n else s


def build_health_panel(health: dict, ops_data: dict | None = None) -> Panel:
    """App health status panel with user count from ops endpoint."""
    status = health["status"]
    latency = health["latency_ms"]

    if status == "healthy":
        style = "green"
        icon = "●"
    else:
        style = "red"
        icon = "○"

    detail = health.get("detail", {})
    version = detail.get("version", "?")
    commit = detail.get("commit", "")[:8]

    text = Text()
    text.append(f" {icon} ", style=style)
    text.append(f"{status.upper()}", style=f"bold {style}")
    text.append(f"  {latency}ms", style="dim")
    text.append(f"  v{version}", style="dim")
    if commit:
        text.append(f"  ({commit})", style="dim")

    if ops_data:
        app = ops_data.get("app", {})
        uptime_s = app.get("uptime_seconds", 0)
        if uptime_s:
            h, m = divmod(uptime_s // 60, 60)
            text.append(f"  up {h}h{m}m", style="dim")
        user_count = ops_data.get("activeUserCount", 0)
        text.append("  |  ", style="dim")
        text.append(f"{user_count} active user{'s' if user_count != 1 else ''}", style="bold cyan")
        req_summary = ops_data.get("requests", {})
        total = req_summary.get("total", 0)
        uploads = req_summary.get("uploads", 0)
        text.append(f"  |  {total} reqs", style="dim")
        if uploads:
            text.append(f" ({uploads} uploads)", style="bold yellow")

    return Panel(text, title="Health", border_style=style, height=3)


_ACTIVITY_TO_PHASE = {
    "blob_trigger": "uploaded",
    "upload": "uploaded",
    "submit": "uploaded",
    "parse_kml": "ingestion",
    "prepare_aoi": "ingestion",
    "store_aoi": "ingestion",
    "write_metadata": "ingestion",
    "load_offloaded": "ingestion",
    "acquire": "acquisition",
    "poll_order": "acquisition",
    "search": "acquisition",
    "download": "fulfilment",
    "post_process": "fulfilment",
    "fulfil": "fulfilment",
    "batch": "fulfilment",
    "enrich": "enrichment",
    "weather": "enrichment",
    "ndvi": "enrichment",
    "mosaic": "enrichment",
    "change_detect": "enrichment",
}


def _classify_activity(name: str) -> str:
    """Map an activity/function name to a pipeline phase."""
    name_lower = name.lower()
    for keyword, phase in _ACTIVITY_TO_PHASE.items():
        if keyword in name_lower:
            return phase
    if "orchestrator" in name_lower or "pipeline" in name_lower:
        return "ingestion"  # orchestrator start = ingestion
    return "uploaded"


def build_kanban(
    durable_instances: list[dict],
    pipeline_activity: list[dict],
) -> Panel:
    """Kanban board: one column per pipeline phase."""
    buckets: dict[str, list[dict]] = {phase: [] for phase in _PHASE_ORDER}

    # Classify durable instances by phase (if status API works)
    for inst in durable_instances:
        runtime = inst.get("runtimeStatus", "")
        custom = inst.get("customStatus") or {}

        # Ops endpoint provides phase/step at top level too
        if inst.get("phase"):
            phase = inst["phase"].lower()
            step = inst.get("step", "")
        elif isinstance(custom, dict):
            phase = custom.get("phase", "").lower()
            step = custom.get("step", "")
        elif isinstance(custom, str):
            phase = custom.lower()
            step = ""
        else:
            phase = ""
            step = ""

        if not phase:
            phase = _RUNTIME_TO_PHASE.get(runtime, "uploaded")
        if phase and phase not in buckets:
            phase = "uploaded"

        if phase:
            buckets[phase].append(
                {
                    "id": _truncate(inst.get("instanceId", "?"), 12),
                    "step": step,
                    "name": inst.get("name", ""),
                    "created": _ts_short(inst.get("createdTime")),
                    "updated": _ts_short(inst.get("lastUpdatedTime")),
                }
            )

    # Group pipeline activity by operation_Id → find latest phase per run
    runs: dict[str, dict] = {}
    for act in pipeline_activity:
        op_id = str(act.get("operation_Id", ""))
        if not op_id:
            continue
        name = str(act.get("name", ""))
        phase = _classify_activity(name)
        code = str(act.get("resultCode", ""))
        success = act.get("success")

        if op_id not in runs:
            runs[op_id] = {
                "id": op_id[:12],
                "phase": phase,
                "latest_name": name,
                "code": code,
                "ts": _ts_short(act.get("timestamp")),
                "failed": False,
            }
        else:
            # Track the furthest phase reached per run
            cur_idx = (
                _PHASE_ORDER.index(runs[op_id]["phase"])
                if runs[op_id]["phase"] in _PHASE_ORDER
                else 0
            )
            new_idx = _PHASE_ORDER.index(phase) if phase in _PHASE_ORDER else 0
            if new_idx > cur_idx:
                runs[op_id]["phase"] = phase
                runs[op_id]["latest_name"] = name
                runs[op_id]["code"] = code

        if success is False or (code and not code.startswith("2") and code != "0"):
            runs[op_id]["failed"] = True

    # Place each run in its phase bucket (or failed if it failed)
    for run in runs.values():
        target = "failed" if run["failed"] else run["phase"]
        if target not in buckets:
            target = "uploaded"
        # Avoid duplicating items already from durable instances
        existing_ids = {item["id"] for item in buckets[target]}
        if run["id"] not in existing_ids:
            buckets[target].append(
                {
                    "id": run["id"],
                    "step": run["latest_name"],
                    "name": "",
                    "created": run["ts"],
                    "updated": "",
                }
            )

    # Build columns as a single-row Table so all 7 fit without wrapping
    grid = Table(
        show_header=True,
        show_edge=False,
        pad_edge=False,
        expand=True,
        box=None,
    )

    # Header row with phase names + counts
    for phase in _PHASE_ORDER:
        items = buckets[phase]
        style = _PHASE_STYLE.get(phase, "white")
        count_str = f" ({len(items)})" if items else ""
        grid.add_column(
            f"{phase.upper()}{count_str}",
            ratio=1,
            style="dim",
            header_style=style,
            overflow="ellipsis",
            no_wrap=True,
        )

    # Fill up to 6 rows of items across all columns
    max_rows = 6
    for row_idx in range(max_rows):
        cells = []
        for phase in _PHASE_ORDER:
            items = buckets[phase]
            if row_idx < len(items):
                item = items[row_idx]
                step_str = f" [{_truncate(item['step'], 8)}]" if item.get("step") else ""
                cells.append(Text(f"{item['id']}{step_str}", overflow="ellipsis", no_wrap=True))
            elif row_idx == 0:
                cells.append(Text("—", style="dim italic"))
            else:
                cells.append(Text(""))
        grid.add_row(*cells)

    return Panel(
        grid,
        title="Pipeline Kanban",
        border_style="bright_blue",
    )


def build_requests_table(requests: list[dict]) -> Panel:
    """Recent HTTP requests panel."""
    table = Table(expand=True, show_edge=False, pad_edge=True)
    table.add_column("Time", width=8, style="dim")
    table.add_column("Endpoint", ratio=2)
    table.add_column("Code", width=5, justify="right")
    table.add_column("Dur(ms)", width=8, justify="right")
    table.add_column("User", width=14)

    for req in (requests or [])[:10]:
        code = str(req.get("resultCode", ""))
        code_style = (
            "green" if code.startswith("2") else "yellow" if code.startswith("4") else "red"
        )
        user = _truncate(str(req.get("user_AuthenticatedId", "") or "anon"), 14)
        dur = str(int(float(req.get("duration", 0)))) if req.get("duration") else ""
        table.add_row(
            _ts_short(req.get("timestamp")),
            _truncate(str(req.get("name", "")), 35),
            Text(code, style=code_style),
            dur,
            user,
        )

    if not requests:
        table.add_row("", Text("No requests in window", style="dim italic"), "", "", "")

    return Panel(table, title="Recent Requests", border_style="cyan")


def build_errors_panel(errors: list[dict]) -> Panel:
    """Recent errors panel."""
    table = Table(expand=True, show_edge=False, pad_edge=True)
    table.add_column("Time", width=8, style="dim")
    table.add_column("Sev", width=4)
    table.add_column("Function", width=20)
    table.add_column("Message", ratio=3)

    for err in (errors or [])[:8]:
        sev = err.get("severityLevel", 0)
        sev_str = {1: "WARN", 2: "WARN", 3: "ERR", 4: "CRIT"}.get(int(sev) if sev else 0, str(sev))
        sev_style = "yellow" if sev_str == "WARN" else "red"
        table.add_row(
            _ts_short(err.get("timestamp")),
            Text(sev_str, style=sev_style),
            _truncate(str(err.get("operation_Name", "") or ""), 20),
            _truncate(str(err.get("message", "")), 80),
        )

    if not errors:
        table.add_row("", "", "", Text("No errors — all clear", style="dim italic green"))

    return Panel(table, title="Errors & Warnings", border_style="red")


def build_users_panel(ops_data: dict | None) -> Panel:
    """Active users panel — shows who is using the app right now."""
    table = Table(expand=True, show_edge=False, pad_edge=True)
    table.add_column("User", ratio=2)
    table.add_column("Activity", ratio=3)

    if ops_data:
        users = ops_data.get("activeUsers", [])
        recent = ops_data.get("recentRequests", [])

        # Build last-seen per user
        user_last: dict[str, dict] = {}
        for r in recent:
            uid = r.get("user", "anon")
            if uid not in user_last:
                user_last[uid] = r

        for user in users[:8]:
            last = user_last.get(user, {})
            path = last.get("path", "")
            ts = _ts_short(last.get("ts"))
            status = last.get("status", "")
            status_style = "green" if str(status).startswith("2") else "red"
            activity = Text()
            if path:
                activity.append(f"{_truncate(path, 18)}", style="dim")
            if ts:
                activity.append(f" {ts}", style="dim italic")
            if status:
                activity.append(f" {status}", style=status_style)
            display_user = "anonymous" if user == "anon" else _truncate(user, 20)
            table.add_row(display_user, activity)

        if not users:
            table.add_row(Text("No recent users", style="dim italic"), Text(""))
    else:
        table.add_row(Text("Ops endpoint unavailable", style="dim italic"), Text(""))

    return Panel(table, title="Active Users", border_style="cyan")


def build_runs_panel(ops_data: dict | None) -> Panel:
    """Recent pipeline runs from Cosmos."""
    table = Table(expand=True, show_edge=False, pad_edge=True)
    table.add_column("Time", width=8, style="dim")
    table.add_column("ID", width=12)
    table.add_column("Status", width=10)
    table.add_column("AOIs", width=5, justify="right")
    table.add_column("User", ratio=1)

    if ops_data:
        runs = ops_data.get("recentRuns", [])
        for run in runs[:8]:
            status = str(run.get("status", "?"))
            status_style = (
                "green"
                if status in ("completed", "ready", "success")
                else "yellow"
                if status in ("pending", "processing", "submitted")
                else "red"
            )
            table.add_row(
                _ts_short(run.get("submitted_at")),
                _truncate(str(run.get("submission_id", run.get("id", "?"))), 12),
                Text(status, style=status_style),
                str(run.get("aoi_count", "")),
                _truncate(str(run.get("user_id", "")), 14),
            )
        if not runs:
            table.add_row("", Text("No runs yet", style="dim italic"), "", "", "")
    else:
        table.add_row("", Text("Ops endpoint unavailable", style="dim italic"), "", "", "")

    return Panel(table, title="Recent Runs", border_style="magenta")


def build_dashboard(
    health: dict,
    requests: list[dict],
    durable_instances: list[dict],
    pipeline_activity: list[dict],
    errors: list[dict],
    refresh_count: int,
    ops_data: dict | None = None,
    source: str = "ops",
) -> Layout:
    """Compose the full dashboard layout."""
    layout = Layout()

    # Header
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    header_text = Text()
    header_text.append("  CANOPEX PIPELINE DASHBOARD", style="bold bright_white on blue")
    header_text.append(f"    {now}  ", style="dim")
    header_text.append(f"  #{refresh_count}", style="dim italic")
    src_style = "green" if source == "ops" else "red" if source == "offline" else "yellow"
    header_text.append(f"  [{source}]", style=src_style)

    layout.split_column(
        Layout(Panel(header_text, style="blue", height=3), name="header", size=3),
        Layout(name="top", size=4),
        Layout(name="kanban", size=12),
        Layout(name="middle"),
        Layout(name="bottom"),
    )

    # Top row: health + user count
    layout["top"].update(build_health_panel(health, ops_data))

    # Middle: kanban
    layout["kanban"].update(build_kanban(durable_instances, pipeline_activity))

    # Middle row: users + runs side by side
    layout["middle"].split_row(
        Layout(build_users_panel(ops_data), name="users", ratio=2),
        Layout(build_runs_panel(ops_data), name="runs", ratio=3),
    )

    # Bottom: requests + errors side by side
    layout["bottom"].split_row(
        Layout(build_requests_table(requests), name="requests", ratio=3),
        Layout(build_errors_panel(errors), name="errors", ratio=2),
    )

    return layout


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Live pipeline monitoring dashboard")
    parser.add_argument(
        "--host",
        default="func-kmlsat-dev.jollysea-48e72cf8.uksouth.azurecontainerapps.io",
        help="Function app hostname",
    )
    parser.add_argument(
        "--app-insights",
        default="387f53d2-98ef-4fc8-9296-32fda4c74bb3",
        help="App Insights app ID (fallback when ops endpoint unavailable)",
    )
    parser.add_argument(
        "--ops-key",
        default=os.environ.get("OPS_DASHBOARD_KEY", ""),
        help="Bearer token for /api/ops/dashboard (or set OPS_DASHBOARD_KEY env var)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=10,
        help="Refresh interval in seconds (default: 10)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    console = Console()

    console.print("[bold blue]Starting Canopex Pipeline Dashboard...[/]")
    console.print(f"  Host: {args.host}")
    console.print(f"  Ops key: {'set' if args.ops_key else 'not set (dev mode)'}")
    console.print(f"  App Insights fallback: {args.app_insights}")
    console.print(f"  Refresh: every {args.interval}s")
    console.print("[dim]Press Ctrl+C to exit[/]\n")

    refresh_count = 0

    with Live(console=console, refresh_per_second=1, screen=True) as live:
        while True:
            refresh_count += 1
            try:
                # Always fetch health (fast, direct HTTP)
                health = fetch_health(args.host)

                # Try ops endpoint first (real-time, sub-second)
                ops_data = fetch_ops_dashboard(args.host, args.ops_key)

                if ops_data:
                    source = "ops"
                    # Extract orchestrations and requests from ops payload
                    durable = ops_data.get("orchestrations", [])
                    pipeline = []  # orchestrations already classified
                    recent_reqs = ops_data.get("recentRequests", [])
                    # Map in-memory requests to the table format
                    requests = [
                        {
                            "timestamp": r.get("ts", ""),
                            "name": r.get("path", ""),
                            "resultCode": str(r.get("status", "")),
                            "duration": r.get("dur_ms", 0),
                            "user_AuthenticatedId": r.get("user", ""),
                        }
                        for r in recent_reqs
                    ]
                    errors = []  # TODO: surface errors from ops endpoint
                elif health["status"] == "healthy":
                    # App is up but ops endpoint failed — try App Insights
                    source = "app-insights"
                    durable = fetch_durable_instances(args.host)
                    pipeline = fetch_pipeline_activity(args.app_insights)
                    requests = fetch_requests(args.app_insights)
                    errors = fetch_errors(args.app_insights)
                else:
                    # App is unreachable — show empty dashboard
                    source = "offline"
                    durable = []
                    pipeline = []
                    requests = []
                    errors = []

                dashboard = build_dashboard(
                    health=health,
                    requests=requests,
                    durable_instances=durable,
                    pipeline_activity=pipeline,
                    errors=errors,
                    refresh_count=refresh_count,
                    ops_data=ops_data,
                    source=source,
                )
                live.update(dashboard)

            except KeyboardInterrupt:
                break
            except Exception as exc:
                live.update(
                    Panel(
                        Text(f"Refresh error: {exc}", style="bold red"),
                        title="Dashboard Error",
                    )
                )

            try:
                time.sleep(args.interval)
            except KeyboardInterrupt:
                break

    console.print("\n[dim]Dashboard stopped.[/]")


if __name__ == "__main__":
    main()
