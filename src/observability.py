"""Best-effort process/system telemetry for log-line diagnostics.

Standalone stdlib-only module so both src/agent.py and src/nodes.py can
import it without import-graph friction. The single public function
returns a one-line summary suitable for inlining into a log message at
phase boundaries (run() entry, post tar-extract, ReAct loop entry/exit).

Used to triage CI failures from the agent's stdout — when a container
exits 137 (SIGKILL/OOM), having an RSS/cgroup_max/tmp_free snapshot at
each phase tells you exactly where the memory pressure landed.
"""

from __future__ import annotations

import os


def resource_snapshot() -> str:
    """One-line summary of process RSS, available RAM, cgroup memory cap, /tmp free.

    All sources are best-effort — silently dropped on platforms (or container
    runtimes) that don't expose them. The function never raises.
    """
    parts: list[str] = []

    # Process RSS — Linux /proc
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    rss_mb = int(line.split()[1]) // 1024
                    parts.append(f"rss={rss_mb}MB")
                    break
    except Exception:
        pass

    # System available memory — Linux /proc
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    avail_mb = int(line.split()[1]) // 1024
                    parts.append(f"mem_avail={avail_mb}MB")
                    break
    except Exception:
        pass

    # cgroup v2 memory.max (where the kernel's OOM-killer threshold lives in
    # containerized envs). v1 fallback: memory/memory.limit_in_bytes.
    for path in (
        "/sys/fs/cgroup/memory.max",
        "/sys/fs/cgroup/memory/memory.limit_in_bytes",
    ):
        try:
            with open(path) as f:
                v = f.read().strip()
        except Exception:
            continue
        if v == "max" or not v.isdigit():
            break
        bytes_v = int(v)
        # cgroup "no limit" sentinel ~ very large; skip if effectively unbounded
        if bytes_v < (1 << 50):
            parts.append(f"cgroup_max={bytes_v // (1 << 20)}MB")
        break

    # Free disk on /tmp (where staging + workspace land in CI)
    try:
        st = os.statvfs("/tmp")
        free_mb = (st.f_bavail * st.f_frsize) // (1 << 20)
        parts.append(f"tmp_free={free_mb}MB")
    except Exception:
        pass

    return " | ".join(parts) if parts else "(no resource snapshot available)"
