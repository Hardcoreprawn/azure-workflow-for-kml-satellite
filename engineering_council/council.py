"""Bounded reviews, deterministic recommendations, and no automatic approvals."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import selectors
import shutil
import signal
import subprocess
import sys
import time
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TypedDict

HOME = Path(__file__).resolve().parent
ROLES = ("Ponytail", "Architect", "Hamilton", "Lambda", "Feynman", "Delivery", "Finisher")
PROFILES = dict.fromkeys(("change", "pr", "plan", "architecture"), ROLES)
PRIORITY = {
    agent: index
    for index, agent in enumerate(("Hamilton", "Ponytail", "Delivery", "Finisher", "Architect", "Lambda", "Feynman"))
}
WEIGHTS = {"safety": 5, "simplicity": 3, "delivery": 3, "completion": 3, "state": 2, "topology": 2, "assumptions": 1}
STOP_DISCUSSING = "STOP DISCUSSING. IMPLEMENT THE SIMPLEST WORKING VERSION."
SEVERITIES = {"blocker": 3, "major": 2, "minor": 1}
OLD_AGENTS = (
    "code-review-critic",
    "release-safety-guard",
    "persona-auditor",
    "contract-docs-keeper",
    "roadmap-orchestrator",
)
MAX_FILE_BYTES = 2_000_000


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def object_json(content: str | bytes) -> dict:
    value = json.loads(content, object_pairs_hook=unique_object)
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


@dataclass(frozen=True)
class Config:
    max_calls: int = 7
    max_seconds: int = 180
    max_input_bytes: int = 24_000
    max_output_bytes: int = 12_000
    max_findings: int = 3
    review_fraction: float = 0.25

    def __post_init__(self) -> None:
        bounds = {
            "max_calls": (1, 7),
            "max_seconds": (1, 600),
            "max_input_bytes": (1, 262_144),
            "max_output_bytes": (1, 65_536),
            "max_findings": (1, 3),
        }
        for name, (minimum, maximum) in bounds.items():
            value = asdict(self)[name]
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f"{name} must be an integer in [{minimum}, {maximum}]")
        if (
            isinstance(self.review_fraction, bool)
            or not isinstance(self.review_fraction, (int, float))
            or not math.isfinite(self.review_fraction)
            or not 0 < self.review_fraction <= 1
        ):
            raise ValueError("review_fraction must be finite and in (0, 1]")


DEFAULT_CONFIG = Config()


class Packet(TypedDict):
    version: int
    kind: str
    brief: str
    content: str
    implementation_minutes: float
    risk: str
    full: bool
    roles: list[str]
    budget_seconds: float
    config: dict
    request_id: str


@dataclass(frozen=True)
class Finding:
    target: str
    severity: str
    category: str
    action: str
    problem: str
    evidence: str
    recommendation: str
    without_change: str
    effort_minutes: int

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if name != "effort_minutes" and (not isinstance(value, str) or not value.strip() or len(value) > 2_000):
                raise ValueError(f"finding {name} must be nonempty text of at most 2000 characters")
        if (
            self.severity not in SEVERITIES
            or self.category not in WEIGHTS
            or self.action not in ("keep", "remove", "change")
        ):
            raise ValueError("invalid finding severity, category or action")
        if type(self.effort_minutes) is not int or not 0 <= self.effort_minutes <= 10_000:
            raise ValueError("effort_minutes must be an integer in [0, 10000]")


def make_packet(
    kind: str,
    brief: str,
    content: str,
    implementation_minutes: float,
    *,
    risk: str = "normal",
    full: bool = False,
    config: Config = DEFAULT_CONFIG,
) -> Packet:
    if kind not in PROFILES or risk not in ("normal", "high"):
        raise ValueError("unknown kind or risk")
    if not isinstance(brief, str) or not isinstance(content, str) or not brief.strip() or not content.strip():
        raise ValueError("brief and input must be nonempty")
    if type(full) is not bool:
        raise ValueError("full must be a boolean")
    if (
        isinstance(implementation_minutes, bool)
        or not math.isfinite(implementation_minutes)
        or implementation_minutes <= 0
    ):
        raise ValueError("implementation_minutes must be positive and finite")
    if len((brief + content).encode("utf-8")) > config.max_input_bytes:
        raise ValueError("input exceeds budget; supply a smaller, complete slice (never silently truncate)")
    roles: list[str] = list(ROLES if full else PROFILES[kind])
    if len(roles) > config.max_calls:
        raise ValueError("selected reviewers exceed max_calls; non-trivial council work requires max_calls=7")
    packet: Packet = {
        "version": 1,
        "kind": kind,
        "brief": brief,
        "content": content,
        "implementation_minutes": implementation_minutes,
        "risk": risk,
        "full": full,
        "roles": roles,
        "budget_seconds": min(config.max_seconds, implementation_minutes * 60 * config.review_fraction),
        "config": asdict(config),
        "request_id": "",
    }
    packet["request_id"] = hashlib.sha256(json.dumps(packet, sort_keys=True).encode()).hexdigest()
    return packet


def validate_packet(value: Packet | dict) -> Packet:
    if not isinstance(value, dict) or type(value.get("version")) is not int:
        raise ValueError("packet must be a versioned JSON object")
    config = Config(**value["config"])
    expected = make_packet(
        value["kind"],
        value["brief"],
        value["content"],
        value["implementation_minutes"],
        risk=value["risk"],
        full=value["full"],
        config=config,
    )
    if value != expected:
        raise ValueError("packet is altered, stale or has an unsupported version")
    return expected


def checked_reports(packet: Packet, reports: list[dict]) -> list[tuple[str, Finding]]:
    if not isinstance(reports, list):
        raise ValueError("reports must be a JSON array")
    if len(reports) > len(packet["roles"]):
        raise ValueError("too many reports")
    findings = []
    for index, report in enumerate(reports):
        if (
            len(json.dumps(report, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            > packet["config"]["max_output_bytes"]
        ):
            raise ValueError("report exceeds output budget")
        if set(report) != {"request_id", "agent", "findings"}:
            raise ValueError("report must contain exactly request_id, agent and findings")
        if report["agent"] != packet["roles"][index] or report["request_id"] != packet["request_id"]:
            raise ValueError("report has wrong order, duplicate agent or mismatched request_id")
        raw = report["findings"]
        if not isinstance(raw, list) or len(raw) > packet["config"]["max_findings"]:
            raise ValueError("findings must be a bounded list")
        for item in raw:
            try:
                findings.append((report["agent"], Finding(**item)))
            except TypeError as error:
                raise ValueError(f"invalid finding fields: {error}") from error
    return findings


def decide(packet: Packet | dict, reports: list[dict]) -> dict:
    checked = validate_packet(packet)
    findings = checked_reports(checked, reports)
    ranked = sorted(
        findings,
        key=lambda item: (
            item[0] == "Feynman",
            not (item[1].severity == "blocker" or item[1].category == "safety"),
            PRIORITY[item[0]],
            -SEVERITIES[item[1].severity],
            -WEIGHTS[item[1].category],
            item[1].effort_minutes,
            item[1].target,
            item[0],
        ),
    )
    unique = {}
    for agent, finding in ranked:
        if finding not in unique:
            unique[finding] = {"agent": agent, **asdict(finding)}
    authoritative = [(agent, finding) for agent, finding in findings if agent != "Feynman"]
    targets = sorted({finding.target for _, finding in authoritative})
    conflicts = [
        target
        for target in targets
        if len({finding.action for _, finding in authoritative if finding.target == target}) > 1
    ]
    missing = checked["roles"][len(reports) :]
    status = "recommend"
    if conflicts or any(finding.severity == "blocker" for _, finding in authoritative):
        status = "needs-human"
    if missing:
        status = "incomplete"
    next_action = "Human verifies findings, chooses the smallest useful change, implements it, and runs focused tests."
    if status != "recommend":
        next_action = (
            "Stop discussion. A human resolves safety blockers or missing evidence; "
            "then choose the smallest reversible implementation. No approval is implied."
        )
    if any(agent == "Finisher" and finding.recommendation == STOP_DISCUSSING for agent, finding in findings):
        next_action = f"{STOP_DISCUSSING} {next_action}"
    return {
        "version": 1,
        "request_id": checked["request_id"],
        "status": status,
        "completed": checked["roles"][: len(reports)],
        "missing": missing,
        "disagreements": conflicts,
        "findings": list(unique.values()),
        "next_action": next_action,
    }


def exchange(process: subprocess.Popen, payload: bytes, deadline: float, output_limit: int) -> bytes:
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    output, diagnostics = bytearray(), bytearray()
    offset = 0
    with selectors.DefaultSelector() as selector:
        for stream, mode in (
            (process.stdin, selectors.EVENT_WRITE),
            (process.stdout, selectors.EVENT_READ),
            (process.stderr, selectors.EVENT_READ),
        ):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, mode)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("adapter exceeded review time budget")
            for key, _ in selector.select(min(remaining, 0.1)):
                stream = key.fileobj
                if stream is process.stdin:
                    offset += os.write(process.stdin.fileno(), payload[offset : offset + 4096])
                    if offset == len(payload):
                        selector.unregister(stream)
                        process.stdin.close()
                    continue
                chunk = os.read(key.fd, 4096)
                if not chunk:
                    selector.unregister(stream)
                    continue
                destination = output if stream is process.stdout else diagnostics
                destination.extend(chunk)
                if len(output) + len(diagnostics) > output_limit:
                    raise ValueError("adapter stdout/stderr exceeded output budget")
        code = process.wait(timeout=max(0, deadline - time.monotonic()))
        if code != 0:
            raise ValueError(f"adapter exited {code}; raw diagnostics omitted to avoid leaking context")
        return bytes(output)


def invoke_adapter(command: list[str], payload: bytes, timeout: float, output_limit: int) -> bytes:
    if os.name != "posix":
        raise ValueError("adapter execution requires POSIX; use Docker on Windows (native Copilot needs no adapter)")
    if not command or timeout <= 0:
        raise ValueError("adapter command and positive remaining budget are required")
    process = subprocess.Popen(  # noqa: S603 - explicit operator-approved argv; no shell or repository-derived commands
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    try:
        return exchange(process, payload, time.monotonic() + timeout, output_limit)
    finally:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()


def run(packet: Packet | dict, command: list[str]) -> dict:
    checked = validate_packet(packet)
    started = time.monotonic()
    reports = []
    errors = []
    common = (HOME / "prompts" / "review.md").read_text(encoding="utf-8")
    for agent in checked["roles"]:
        remaining = checked["budget_seconds"] - (time.monotonic() - started)
        if remaining <= 0:
            errors.append("Review budget exhausted; no more agents will run.")
            break
        prompt = (HOME / ".github" / "agents" / f"{agent.lower()}.agent.md").read_text(encoding="utf-8")
        payload = json.dumps({"agent": agent, "instructions": common + "\n" + prompt, "packet": checked}).encode()
        try:
            raw = invoke_adapter(command, payload, remaining, checked["config"]["max_output_bytes"])
            report = object_json(raw)
            checked_reports(checked, [*reports, report])
        except (OSError, ValueError, TypeError, KeyError, TimeoutError, subprocess.TimeoutExpired) as error:
            errors.append(f"{agent}: {type(error).__name__}: {error}")
            break
        reports.append(report)
        findings = checked_reports(checked, reports)
        if any(agent != "Feynman" and finding.severity == "blocker" for agent, finding in findings):
            errors.append("Safety/correctness blocker found; remaining reviews stopped for human resolution.")
            break
        if any(agent == "Finisher" and finding.recommendation == STOP_DISCUSSING for agent, finding in findings):
            break
    return {**decide(checked, reports), "errors": errors, "elapsed_seconds": round(time.monotonic() - started, 3)}


def read_text(path: Path, limit: int = MAX_FILE_BYTES) -> str:
    with path.open("rb") as source:
        content = source.read(limit + 1)
    if len(content) > limit:
        raise ValueError(f"{path} exceeds {limit} bytes")
    return content.decode("utf-8")


def install_agents(repo: Path, *, replace_old: bool = False) -> None:
    repo = repo.resolve()
    destination = repo / ".github" / "agents"
    for directory in (repo / ".github", destination):
        if directory.is_symlink():
            raise ValueError(f"refusing to install through a symlink: {directory}")
    sources = sorted((HOME / ".github" / "agents").glob("*.agent.md"))
    if {source.stem for source in sources} != {f"{name.lower()}.agent" for name in (*ROLES, "Council")}:
        raise ValueError("installation requires all eight council agent definitions")
    for source in sources:
        target = destination / source.name
        if target.is_symlink():
            raise ValueError(f"refusing to overwrite a symlink: {target}")
        if target.exists() and target.read_bytes() != source.read_bytes():
            raise ValueError(f"refusing to overwrite a different agent: {target}")
    destination.mkdir(parents=True, exist_ok=True)
    for source in sources:
        shutil.copyfile(source, destination / source.name)
    if replace_old:
        for name in OLD_AGENTS:
            (destination / f"{name}.agent.md").unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    packet_parser = sub.add_parser("packet", help="Prepare bounded context for native Copilot or an adapter")
    packet_parser.add_argument("--input", type=Path, required=True)
    packet_parser.add_argument("--brief", required=True)
    packet_parser.add_argument("--kind", choices=PROFILES, default="change")
    packet_parser.add_argument("--risk", choices=("normal", "high"), default="normal")
    packet_parser.add_argument("--implementation-minutes", type=float, required=True)
    packet_parser.add_argument("--config", type=Path)
    packet_parser.add_argument("--full", action="store_true")
    for operation in ("run", "decide"):
        command_parser = sub.add_parser(operation)
        command_parser.add_argument("--packet", type=Path, required=True)
        if operation == "decide":
            command_parser.add_argument("--reports", type=Path, required=True)
        else:
            command_parser.add_argument("--adapter", nargs=argparse.REMAINDER, required=True)
    installer = sub.add_parser("install")
    installer.add_argument("--repo", type=Path, required=True)
    installer.add_argument(
        "--replace-old",
        action="store_true",
        help="Explicitly remove the five legacy Canopex agents",
    )
    for command_parser in (packet_parser, *[sub.choices[name] for name in ("run", "decide")]):
        command_parser.add_argument(
            "--output",
            type=Path,
            required=True,
            help="New JSON file; existing files are not overwritten",
        )
    args = parser.parse_args(argv)
    try:
        if args.operation == "install":
            install_agents(args.repo, replace_old=args.replace_old)
            return 0
        if args.output.exists() or args.output.is_symlink():
            raise FileExistsError(f"output already exists: {args.output}")
        if args.operation == "packet":
            config = Config(**object_json(read_text(args.config))) if args.config else Config()
            result = make_packet(
                args.kind,
                args.brief,
                read_text(args.input, config.max_input_bytes),
                args.implementation_minutes,
                risk=args.risk,
                full=args.full,
                config=config,
            )
        else:
            packet = object_json(read_text(args.packet))
            result = (
                run(packet, args.adapter)
                if args.operation == "run"
                else decide(
                    packet,
                    json.loads(read_text(args.reports), object_pairs_hook=unique_object),
                )
            )
        with args.output.open("x", encoding="utf-8") as output:
            output.write(json.dumps(result, indent=2) + "\n")
        return {"recommend": 0, "needs-human": 2, "incomplete": 3}.get(result.get("status", ""), 0)
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f"council: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
