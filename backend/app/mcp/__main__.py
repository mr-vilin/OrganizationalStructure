"""MCP sidecar 命令行边界；正式依赖接线完成前拒绝启动。"""

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Organization capability MCP sidecar (not yet configured)")
    parser.add_argument("--transport", choices=("streamable-http",), default="streamable-http")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    parser.error(
        "MCP_RUNTIME_NOT_CONFIGURED: internal HTTP client, policy, tracer, "
        "authentication and business tools must be wired before startup (Task 4)"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
