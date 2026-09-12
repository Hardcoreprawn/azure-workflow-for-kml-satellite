"""Run a local capacity command with bounded Docker CPU and memory sampling."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import Any

CONTAINERS = {"canopex-local-exercise-runner", "canopex-local-exercise-azurite"}
MAX_OBSERVATION_SECONDS = 900


def docker_samples() -> list[dict[str, Any]]:
    result = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{json .}}"],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    timestamp = datetime.now(UTC).isoformat()
    samples = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    selected = [{**sample, "time": timestamp} for sample in samples if sample.get("Name") in CONTAINERS]
    if not selected:
        raise ValueError("empty resource sample for experiment containers")
    return selected


def observe(command: list[str], output: Path) -> int:
    observed: set[str] = set()
    errors: list[str] = []
    pause = Event()
    deadline = time.monotonic() + MAX_OBSERVATION_SECONDS
    with output.open("x") as stream:
        process = subprocess.Popen(command)
        try:
            while process.poll() is None and time.monotonic() < deadline:
                try:
                    samples = docker_samples()
                    observed.update(sample["Name"] for sample in samples)
                    for sample in samples:
                        stream.write(json.dumps(sample) + "\n")
                except (ValueError, OSError, subprocess.SubprocessError) as exc:
                    errors.append(str(exc))
                    stream.write(json.dumps({"time": datetime.now(UTC).isoformat(), "error": str(exc)}) + "\n")
                stream.flush()
                pause.wait(1)
            if process.poll() is None:
                raise TimeoutError("capacity command exceeded observation deadline")
            if errors or observed != CONTAINERS:
                raise ValueError(f"incomplete resource evidence: observed={observed}, errors={errors}")
            return process.returncode
        finally:
            if process.poll() is None:
                subprocess.run(
                    ["docker", "stop", "--time", "10", "canopex-local-exercise-runner"],
                    check=True,
                    timeout=30,
                )
                process.wait(timeout=30)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.command:
        parser.error("a workload command is required")
    raise SystemExit(observe(args.command, args.output))


if __name__ == "__main__":
    main()
