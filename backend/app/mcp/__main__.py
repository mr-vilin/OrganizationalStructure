"""可运行的独立 Streamable HTTP sidecar。"""
import argparse
from collections.abc import Sequence

from .config import create_server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Organization capability MCP sidecar")
    parser.add_argument("--transport", choices=("streamable-http",), default="streamable-http")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        server = create_server()
    except ValueError:
        parser.error("MCP_RUNTIME_NOT_CONFIGURED: valid independent tokens and trusted principal configuration are required")
    import uvicorn
    uvicorn.run(server.streamable_http_app(host=args.host), host=args.host, port=args.port,
                access_log=False, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
