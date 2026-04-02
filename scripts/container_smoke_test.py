#!/usr/bin/env python3
"""Container smoke tests — validates the runtime image has all required components.

Run via bind-mount of the local scripts directory (no pytest needed):
    docker run --rm -v "$PWD/scripts:/scripts:ro" <image> python3 /scripts/container_smoke_test.py

Or against an already running container (with /scripts mounted):
    docker exec <container> python3 /scripts/container_smoke_test.py

Exit code 0 = all checks pass; non-zero = at least one failure.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    """Record a check result."""
    if condition:
        print(f"  {PASS} {name}")
    else:
        msg = f"{name}: {detail}" if detail else name
        failures.append(msg)
        print(f"  {FAIL} {name} — {detail}")


def main() -> int:
    print("Container smoke tests")
    print("=" * 50)

    # ── 1. Functions host binary ──
    print("\n[Functions Host]")
    host_dir = Path("/azure-functions-host")
    host_bin = host_dir / "Microsoft.Azure.WebJobs.Script.WebHost"
    check("Functions host binary exists", host_bin.exists())
    if host_bin.exists():
        check("Functions host is executable", os.access(host_bin, os.X_OK))

    # NuGet.Versioning is required by ScriptConstants at startup
    nuget_ver = host_dir / "NuGet.Versioning.dll"
    check("NuGet.Versioning.dll present (required by host)", nuget_ver.exists())

    # Verify JIT fallback DLL present
    jit_dll = host_dir / "Microsoft.Azure.WebJobs.Script.WebHost.dll"
    check("JIT host DLL present (non-R2R fallback)", jit_dll.exists())

    # R2R precompiled DLL — kept for scale-to-zero cold start performance
    r2r_dll = host_dir / "Microsoft.Azure.WebJobs.Script.WebHost.r2r.dll"
    check("R2R precompiled DLL present (cold start)", r2r_dll.exists())

    # ── 1b. Bloat stripped from host ──
    print("\n[Host Optimisation]")
    check(
        "Roslyn C# compiler removed", not (host_dir / "Microsoft.CodeAnalysis.CSharp.dll").exists()
    )
    check(
        "NuGet bloat DLLs removed",
        not any(f for f in host_dir.glob("NuGet.*.dll") if f.name != "NuGet.Versioning.dll"),
    )
    check("No PDB files remain", not any(host_dir.rglob("*.pdb")))

    # ── 2. Extension bundles ──
    print("\n[Extension Bundles]")
    bundle_dir = Path("/FuncExtensionBundles/Microsoft.Azure.Functions.ExtensionBundle")
    check("Extension bundle directory exists", bundle_dir.exists())
    if bundle_dir.exists():
        versions = list(bundle_dir.iterdir())
        check(
            "At least one bundle version present",
            len(versions) > 0,
            f"found {len(versions)} versions",
        )

    # Verify required extensions are present (Durable, HTTP, EventGrid, Blob, Timer)
    if bundle_dir.exists() and versions:
        bin_dir = versions[0] / "bin"
        if bin_dir.exists():
            dlls = [f.name for f in bin_dir.glob("*.dll")]
            check("DurableTask extension present", any("DurableTask" in d for d in dlls))
            check("EventGrid extension present", any("EventGrid" in d for d in dlls))
            check(
                "Storage.Blobs extension present",
                any("Storage.Blobs" in d or "Blobs" in d for d in dlls),
            )

    # ── 2b. Bloat stripped from bundles ──
    print("\n[Bundle Optimisation]")
    if bundle_dir.exists() and versions:
        v = versions[0]
        check("bin_v3/ removed (.NET isolated worker)", not (v / "bin_v3").exists())
        check("StaticContent/ removed (dashboard UI)", not (v / "StaticContent").exists())
        bin_dir = v / "bin"
        if bin_dir.exists():
            win_files = list(bin_dir.rglob("runtimes/win-*"))
            check("Windows runtimes removed", len(win_files) == 0, f"found {len(win_files)} files")
            osx_files = list(bin_dir.rglob("runtimes/osx*"))
            check("OSX runtimes removed", len(osx_files) == 0, f"found {len(osx_files)} files")
            kafka_files = list(bin_dir.rglob("*rdkafka*"))
            check(
                "Kafka native libs removed",
                len(kafka_files) == 0,
                f"found {len(kafka_files)} files",
            )

    # ── 3. Python worker ──
    print("\n[Python Worker]")
    worker_py = Path("/azure-functions-host/workers/python/3.12/LINUX/X64/worker.py")
    check("Python worker entry point exists", worker_py.exists())
    worker_config = Path("/azure-functions-host/workers/python/worker.config.json")
    check("Worker config exists", worker_config.exists())
    if worker_config.exists():
        cfg = json.loads(worker_config.read_text())
        check("Worker language is python", cfg.get("description", {}).get("language") == "python")

    # ── 4. .NET runtime ──
    print("\n[.NET Runtime]")
    try:
        result = subprocess.run(
            ["dotnet", "--list-runtimes"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        runtimes = result.stdout
        check("dotnet CLI available", result.returncode == 0)
        check(
            "ASP.NET Core 8.0 runtime present",
            "Microsoft.AspNetCore.App 8.0" in runtimes,
            f"got: {runtimes.strip()}",
        )
    except FileNotFoundError:
        check("dotnet CLI available", False, "dotnet not found in PATH")

    # ── 4b. ICU / globalization support ──
    print("\n[ICU / Globalization]")
    icu_found = any(Path("/usr/lib").rglob("libicuuc.so*")) or any(
        Path("/usr/lib/x86_64-linux-gnu").rglob("libicuuc.so*")
    )
    check("libicu installed (required by .NET)", icu_found, "missing libicu — .NET host will crash")
    # Verify the Functions host binary can at least start without an ICU crash.
    # The host doesn't support --version, so we just check it doesn't abort
    # with the 'Couldn't find a valid ICU package' error within a few seconds.
    host_bin = Path("/azure-functions-host/Microsoft.Azure.WebJobs.Script.WebHost")
    if host_bin.exists():
        try:
            probe = subprocess.run(
                [str(host_bin)],
                capture_output=True,
                text=True,
                timeout=5,
                env={**os.environ, "DOTNET_SYSTEM_GLOBALIZATION_INVARIANT": "0"},
            )
            stderr = probe.stderr or ""
            stderr_lower = stderr.lower()
            icu_crash = "couldn't find a valid icu package" in stderr_lower or (
                "icu" in stderr_lower and "libicu" in stderr_lower
            )
            check(
                "Functions host starts without ICU crash",
                probe.returncode == 0 and not icu_crash,
                stderr.strip()[:200] if icu_crash or probe.returncode != 0 else "",
            )
        except subprocess.TimeoutExpired:
            # Timeout is GOOD — it means the host started running (no ICU crash)
            check("Functions host starts without ICU crash", True)
        except Exception as e:
            check("Functions host starts without ICU crash", False, str(e)[:200])

    # ── 5. Startup scripts ──
    print("\n[Startup]")
    startup = Path("/opt/startup/start_nonappservice.sh")
    check("Startup script exists", startup.exists())
    if startup.exists():
        check("Startup script is executable", os.access(startup, os.X_OK))

    # ── 6. Environment variables ──
    print("\n[Environment]")
    check(
        "AzureWebJobsScriptRoot set",
        os.environ.get("AzureWebJobsScriptRoot") == "/home/site/wwwroot",  # noqa: SIM112
    )
    check("FUNCTIONS_WORKER_RUNTIME=python", os.environ.get("FUNCTIONS_WORKER_RUNTIME") == "python")
    check("ASPNETCORE_URLS set", "80" in os.environ.get("ASPNETCORE_URLS", ""))

    # ── 7. Application code (app image only) ──
    print("\n[Application]")
    app_root = Path("/home/site/wwwroot")
    host_json = app_root / "host.json"
    func_app = app_root / "function_app.py"

    if host_json.exists():
        hj = json.loads(host_json.read_text())
        check("host.json version is 2.0", hj.get("version") == "2.0")
    else:
        print("  — host.json not present (base image — skipping)")

    if func_app.exists():
        check("function_app.py present", True)
        # Verify all critical imports work (ensure app root is on sys.path)
        try:
            if str(app_root) not in sys.path:
                sys.path.insert(0, str(app_root))
            importlib.import_module("function_app")
            check("function_app.py importable", True)
        except Exception as e:
            check("function_app.py importable", False, str(e))
    else:
        print("  — function_app.py not present (base image — skipping import checks)")

    # ── 8. Critical Python packages ──
    print("\n[Python Packages]")
    critical_packages = [
        "azure.functions",
        "azure.storage.blob",
        "azure.data.tables",
        "rasterio",
        "fiona",
        "shapely",
        "pyproj",
        "pydantic",
        "httpx",
        "jwt",
        "stripe",
    ]
    for pkg in critical_packages:
        try:
            importlib.import_module(pkg)
            check(f"{pkg} importable", True)
        except ImportError:
            # In base image, app packages won't be present — that's OK
            if func_app.exists():
                check(f"{pkg} importable", False, "missing in app image")
            else:
                print(f"  — {pkg} not present (base image — expected)")
        except Exception as e:
            # Native-extension or other unexpected import failure
            check(f"{pkg} importable", False, f"import failed: {e}")

    # ── 9. No dev dependencies leaked ──
    print("\n[Security]")
    dev_packages = ["pytest", "ruff", "pip_audit"]
    for pkg in dev_packages:
        try:
            importlib.import_module(pkg)
            check(f"{pkg} NOT installed (dev leak)", False, "dev dependency found in prod image")
        except ImportError:
            check(f"{pkg} NOT installed (dev leak)", True)

    # ── Summary ──
    print("\n" + "=" * 50)
    if failures:
        print(f"\n{FAIL} {len(failures)} check(s) failed:")
        for f in failures:
            print(f"  - {f}")
        return 1
    else:
        print(f"\n{PASS} All checks passed.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
