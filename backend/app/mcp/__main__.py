"""可运行的独立 Streamable HTTP sidecar。"""
import argparse
from collections.abc import Sequence

from .config import MCPSettings, create_server, http_app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Organization capability MCP sidecar")
    parser.add_argument("--transport", choices=("streamable-http",), default="streamable-http")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        overrides = {}
        if args.host is not None:
            overrides["mcp_host"] = args.host
        if args.port is not None:
            overrides["mcp_port"] = args.port
        config = MCPSettings(**overrides)
        server = create_server(config)
    except ValueError:
        parser.error("MCP_RUNTIME_NOT_CONFIGURED: valid independent tokens and trusted principal configuration are required")
    import uvicorn
    uvicorn.run(http_app(server, host=config.mcp_host, port=config.mcp_port),
                host=config.mcp_host, port=config.mcp_port, access_log=False, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
