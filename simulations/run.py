"""Run simulations on the test worker.

    uv run python simulations/run.py critical          # text, 3 samples each, must all pass
    uv run python simulations/run.py critical --samples 1
    uv run python simulations/run.py canary --live      # the deployed agent, same 3 scenarios

The local run uses the test worker settings: agent name `nexaconnect-ashley-test`, the Pinecone `test`
namespace. The simulated database is in memory, so no database is touched. Needs the LiveKit CLI
(`lk`) signed in to the project.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenarios", help="file name in simulations/, without .yaml (critical, main, canary)")
    parser.add_argument("--samples", type=int, default=3, help="runs per scenario")
    parser.add_argument("--pass-rate", type=float, default=1.0, help="share of samples that must pass")
    parser.add_argument("--live", action="store_true", help="run against the deployed agent instead of a local worker")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    env = {**os.environ, "AGENT_NAME": "nexaconnect-ashley-test", "PINECONE_NAMESPACE": "test"}

    command = [
        "lk", "agent", "simulate", "text",
        "--scenarios", str(ROOT / "simulations" / f"{args.scenarios}.yaml"),
        "--yes",
    ]
    if args.samples > 1:  # the CLI accepts --pass-rate only together with several samples
        command += ["--samples", str(args.samples), "--pass-rate", str(args.pass_rate)]
    if args.live:
        command += ["--agent-name", "nexaconnect-ashley"]
        env["PINECONE_NAMESPACE"] = os.environ.get("PINECONE_NAMESPACE", "production")
    else:
        command += ["--agent-name", "nexaconnect-ashley-test"]
    return subprocess.run(command, cwd=ROOT, env=env).returncode


if __name__ == "__main__":
    sys.exit(main())
