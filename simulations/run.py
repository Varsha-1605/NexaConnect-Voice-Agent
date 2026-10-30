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
