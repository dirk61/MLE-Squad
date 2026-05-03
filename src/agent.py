import asyncio
import base64
import gc
import io
import logging
import os
import tarfile
import tempfile
import traceback
from pathlib import Path
from uuid import uuid4

from a2a.server.tasks import TaskUpdater
from a2a.types import FilePart, FileWithBytes, Message, Part, Role, TaskState, TextPart
from a2a.utils import get_message_text, new_agent_text_message

from messenger import Messenger
from src.observability import resource_snapshot

log = logging.getLogger("mle_agent")


class Agent:
    def __init__(self):
        self.messenger = Messenger()

    async def run(self, message: Message, updater: TaskUpdater) -> None:
        """Main agent entry point.

        First invocation: receives competition data (tar + instructions),
        runs the LangGraph pipeline, and submits the result.
        Subsequent invocation on the same context: handles validation
        replies from the green agent.
        """
        log.info("Agent.run() — %d parts | %s", len(message.parts), resource_snapshot())

        # ── Detect validation reply from green agent ─────────────────────
        has_file = any(isinstance(p.root, FilePart) for p in message.parts)
        if not has_file:
            validation_text = get_message_text(message)
            log.info("Validation reply: %s", validation_text)
            await updater.update_status(
                TaskState.working,
                new_agent_text_message(
                    f"Validation response received: {validation_text}"
                ),
            )
            return

        # ── Step 1: Extract competition tar to staging directory ─────────
        await updater.update_status(
            TaskState.working,
            new_agent_text_message("Extracting competition data..."),
        )

        tar_bytes = _extract_tar_bytes(message)
        if tar_bytes is None:
            await updater.update_status(
                TaskState.failed,
                new_agent_text_message("No competition tar file found in message."),
            )
            return

        # Stage to /data1 when available so the 150-850MB tar extract doesn't
        # land on /tmp (often tmpfs in containers, or near-full on lab boxes).
        # Mirrors the workspace-root logic in nodes.py:_DEFAULT_WORKSPACE.
        staging_root = "/data1/six004/tmp" if os.path.isdir("/data1/six004/tmp") else None
        staging_dir = tempfile.mkdtemp(prefix="mle_staging_", dir=staging_root)
        tar_members: list[str] = []
        tar_size_mb = len(tar_bytes) // (1 << 20)
        try:
            with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tar:
                tar_members = [m.name for m in tar.getmembers()]
                log.info(
                    "Tar members (%d, gz=%dMB): %s",
                    len(tar_members), tar_size_mb, tar_members[:10],
                )
                tar.extractall(path=staging_dir, filter="data")
        except Exception as e:
            log.error("Tar extraction failed: %s", traceback.format_exc())
            await updater.update_status(
                TaskState.failed,
                new_agent_text_message(f"Failed to extract competition tar: {e}"),
            )
            return

        # Free the in-memory tar buffer immediately — for large competitions
        # (dogs-vs-cats: ~840MB gz) it would otherwise stay pinned through the
        # entire LangGraph run and triple-budget against /tmp tmpfs (840MB
        # bytes + 1.1GB extracted + 1.1GB workspace copy = 3GB+ RAM pressure
        # in CI). gc.collect() is a one-time ~200ms cost worth the headroom.
        del tar_bytes
        # Also clear the base64-encoded bytes inside the original message's
        # FilePart. The a2a framework keeps the message parameter alive for
        # the entire Agent.run() lifetime (= the whole pipeline), and the
        # base64 string is ~1.4× the tar bytes (so ~1.4GB for dogs-vs-cats).
        # On a 7-8GB GHA runner this is the difference between OOM and
        # successful graph invocation.
        for _part in message.parts:
            if isinstance(_part.root, FilePart):
                _file_data = _part.root.file
                if isinstance(_file_data, FileWithBytes):
                    _file_data.bytes = ""
        gc.collect()
        log.info("[PHASE] tar_extracted | %s", resource_snapshot())

        # ── Step 2: Extract instructions and detect competition ──────────
        instructions = get_message_text(message) or "No instructions provided."
        competition_id = _detect_competition_id(instructions, tar_members, staging_dir)
        log.info(
            "Competition: %s | Staging: %s",
            competition_id or "(unknown)", staging_dir,
        )

        # ── Step 3: Build graph and initial state ────────────────────────
        await updater.update_status(
            TaskState.working,
            new_agent_text_message(
                f"Starting ML pipeline (competition: {competition_id or 'unknown'})..."
            ),
        )

        from src.graph import build_graph

        app = build_graph()

        initial_state = {
            "messages": [{"role": "user", "content": instructions}],
            "all_messages": [],
            "handoff_message": staging_dir,
            "current_phase": "architecture",
            "target_model": "opus",
            "iteration_count": 0,
            "micro_tasks": [],
            "workspace_dir": "",
            "competition_id": competition_id,
        }

        # ── Step 4: Run the graph ────────────────────────────────────────
        # Graph nodes are synchronous — run in a thread to avoid blocking
        # the async event loop.
        log.info("[PHASE] graph_invoked | %s", resource_snapshot())
        try:
            final_state = await asyncio.to_thread(app.invoke, initial_state)
        except Exception as e:
            log.error("Graph invocation failed:\n%s", traceback.format_exc())
            await updater.update_status(
                TaskState.failed,
                new_agent_text_message(f"Pipeline failed: {e}"),
            )
            return
        log.info(
            "Graph finished. workspace_dir=%s",
            final_state.get("workspace_dir", ""),
        )
        log.info(
            "[GHA_MILESTONE] graph_complete | iter=%d | elapsed=%s",
            final_state.get("iteration_count", 0), resource_snapshot(),
        )

        # ── Step 5: Read submission and submit ───────────────────────────
        workspace_dir = final_state.get("workspace_dir", "")
        submission_path = (
            os.path.join(workspace_dir, "submission.csv") if workspace_dir else ""
        )

        # Emergency fallback: copy sample_submission.csv so we at least submit
        # something scoreable rather than failing entirely.
        if workspace_dir and (not submission_path or not os.path.isfile(submission_path)):
            log.warning("No submission.csv — attempting sample_submission fallback")
            sample = os.path.join(workspace_dir, "data", "raw", "sample_submission.csv")
            fallback = os.path.join(workspace_dir, "submission.csv")
            if os.path.isfile(sample):
                import shutil
                shutil.copy2(sample, fallback)
                submission_path = fallback
                log.info("Fallback: copied sample_submission.csv as submission.csv")

        if not submission_path or not os.path.isfile(submission_path):
            await updater.update_status(
                TaskState.failed,
                new_agent_text_message(
                    "Pipeline completed but no submission.csv found."
                ),
            )
            return

        csv_bytes = Path(submission_path).read_bytes()
        # Sanity-extract row count + first-row sample for the GHA log
        try:
            row_count = csv_bytes.decode("utf-8", errors="ignore").count("\n") - 1
        except Exception:
            row_count = -1
        from src.nodes import _elapsed_min
        log.info(
            "[GHA_MILESTONE] submission_ready | path=%s | bytes=%d | rows=%d | total_min=%.1f",
            submission_path, len(csv_bytes), row_count, _elapsed_min(),
        )

        # ── Step 6: Validate with green agent ────────────────────────────
        await updater.update_status(
            TaskState.working,
            message=Message(
                kind="message",
                role=Role.agent,
                parts=[
                    Part(root=TextPart(text="validate")),
                    Part(
                        root=FilePart(
                            file=FileWithBytes(
                                bytes=base64.b64encode(csv_bytes).decode("ascii"),
                                name="submission.csv",
                                mime_type="text/csv",
                            )
                        )
                    ),
                ],
                message_id=uuid4().hex,
            ),
        )

        # ── Step 7: Submit final artifact ────────────────────────────────
        await updater.update_status(
            TaskState.working,
            new_agent_text_message("Submitting final submission..."),
        )
        log.info("[GHA_MILESTONE] artifact_submit_start | bytes=%d", len(csv_bytes))
        await updater.add_artifact(
            parts=[
                Part(
                    root=FilePart(
                        file=FileWithBytes(
                            bytes=base64.b64encode(csv_bytes).decode("ascii"),
                            name="submission.csv",
                            mime_type="text/csv",
                        )
                    )
                )
            ],
            name="submission",
        )
        log.info("[GHA_MILESTONE] artifact_submit_done")


# ── Helpers (module-level, not on the class) ─────────────────────────────


def _extract_tar_bytes(message: Message) -> bytes | None:
    """Extract the first FilePart's bytes from an A2A message."""
    for part in message.parts:
        if isinstance(part.root, FilePart):
            file_data = part.root.file
            if isinstance(file_data, FileWithBytes):
                return base64.b64decode(file_data.bytes)
    return None


def _detect_competition_id(
    instructions: str, tar_members: list[str], staging_dir: str = ""
) -> str:
    """Best-effort competition_id detection.

    Tries: (1) directory prefix in tar members, (2) description.md content
    from extracted tar, (3) instructions text.
    Returns empty string if no match — graceful degradation.
    """
    from src.medal_thresholds import MEDAL_THRESHOLDS

    # Strategy 1: tar directory prefix
    for member in tar_members:
        parts = member.split("/")
        if len(parts) > 1 and parts[0] in MEDAL_THRESHOLDS:
            return parts[0]

    # Strategy 2: check description.md from extracted tar
    if staging_dir:
        desc_path = os.path.join(staging_dir, "home", "data", "description.md")
        if os.path.isfile(desc_path):
            try:
                desc_text = Path(desc_path).read_text(errors="ignore").lower()
                for comp_id in sorted(MEDAL_THRESHOLDS, key=len, reverse=True):
                    if comp_id in desc_text:
                        return comp_id
            except Exception:
                pass

    # Strategy 3: match known IDs in instructions (longest first to avoid
    # partial matches like "ai" matching before "ai4code")
    instructions_lower = instructions.lower()
    for comp_id in sorted(MEDAL_THRESHOLDS, key=len, reverse=True):
        if comp_id in instructions_lower:
            return comp_id

    return ""
