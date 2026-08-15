"""Run the ClearFrame MCP server.

stdio (default, for local MCP clients):
    python -m clearframe.mcp --out out

streamable HTTP (for Cloud Run / remote clients, endpoint /mcp):
    python -m clearframe.mcp --transport http --host 0.0.0.0 --port 8080 --out out
"""

import argparse
import asyncio
import os
from pathlib import Path

from clearframe.mcp.server import build_server


def main() -> int:
    parser = argparse.ArgumentParser(prog="clearframe-mcp")
    parser.add_argument("--out", type=Path, default=Path("out"), help="State/artifact directory")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("PORT", "8080")),
        help="HTTP port (defaults to $PORT for Cloud Run)",
    )
    args = parser.parse_args()
    server = build_server(out_root=args.out)

    if args.transport == "http":
        from mcp.server.transport_security import TransportSecuritySettings

        asyncio.run(
            server.run_streamable_http_async(
                host=args.host,
                port=args.port,
                stateless_http=True,  # scale-to-zero friendly: no session affinity
                transport_security=TransportSecuritySettings(
                    # Cloud Run terminates TLS and forwards on its own hostname;
                    # DNS-rebinding protection would reject it.
                    enable_dns_rebinding_protection=False,
                ),
            )
        )
    else:
        asyncio.run(server.run_stdio_async())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
