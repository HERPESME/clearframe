"""Run the ClearFrame MCP server over stdio: python -m clearframe.mcp --out out"""

import argparse
import asyncio
from pathlib import Path

from clearframe.mcp.server import build_server


def main() -> int:
    parser = argparse.ArgumentParser(prog="clearframe-mcp")
    parser.add_argument("--out", type=Path, default=Path("out"), help="State/artifact directory")
    args = parser.parse_args()
    server = build_server(out_root=args.out)
    asyncio.run(server.run_stdio_async())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
