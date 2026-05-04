import argparse
import os
import sys
from pathlib import Path

# Ensure the project root is on sys.path so `from src.xxx import ...` works.
# uv run src/server.py only adds src/ (the script dir), not the project root.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# Load .env if it exists (local dev). In Docker/CI env vars are already injected.
_env_file = _PROJECT_ROOT / ".env"
if _env_file.is_file():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

import logging

# ── Logging ──────────────────────────────────────────────────────────────
# File-based log captures everything (agent loop, LLM calls, errors)
# for post-run diagnosis. Also streams to stderr for live monitoring.
_DEFAULT_LOG = "/data1/six004/tmp/mle_agent.log" if os.path.isdir("/data1") else "/tmp/mle_agent.log"
_LOG_PATH = os.environ.get("MLE_AGENT_LOG", _DEFAULT_LOG)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(_LOG_PATH, mode="w"),
        logging.StreamHandler(),
    ],
)
logging.getLogger("mle_agent").info("Log file: %s", _LOG_PATH)

import uvicorn

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
)

from executor import Executor


def main():
    parser = argparse.ArgumentParser(description="Run the A2A agent.")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind the server")
    parser.add_argument("--port", type=int, default=9009, help="Port to bind the server")
    parser.add_argument("--card-url", type=str, help="URL to advertise in the agent card")
    args = parser.parse_args()

    # Fill in your agent card
    # See: https://a2a-protocol.org/latest/tutorials/python/3-agent-skills-and-card/
    
    skill = AgentSkill(
        id="mle-bench-submission",
        name="MLE Bench Submission",
        description="Generates a submission CSV for MLE-Bench competitions",
        tags=["mle", "submission"],
        examples=[]
    )

    agent_card = AgentCard(
        name="MLE Bench Agent",
        description="A purple agent that participates in MLE-Bench assessments by generating competition submission files.",
        url=args.card_url or f"http://{args.host}:{args.port}/",
        version='1.0.0',
        default_input_modes=['text'],
        default_output_modes=['text'],
        capabilities=AgentCapabilities(streaming=True),
        skills=[skill]
    )

    request_handler = DefaultRequestHandler(
        agent_executor=Executor(),
        task_store=InMemoryTaskStore(),
    )
    server = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
        # 2GB — green tars BOTH train.zip+test.zip AND the unpacked train/+test/
        # dirs from competition.public_dir, then base64-encodes the whole thing
        # inline in JSON-RPC. dogs-vs-cats public_dir is ~1.14 GB on disk →
        # ~1.5 GB on the wire after base64 (×4/3). 512MB was too tight for
        # any image-heavy competition. Default a2a-sdk is only 10MB.
        max_content_length=2 * 1024 * 1024 * 1024,
    )
    uvicorn.run(server.build(), host=args.host, port=args.port)


if __name__ == '__main__':
    main()
