# -*- coding: utf-8 -*-
"""HTTP CONNECT shim for routing Kiro traffic through Clash.

This listener accepts HTTP CONNECT requests from Clash and tunnels the raw TLS
stream to the local HTTPS reverse gateway. It lets users route Kiro domains via
Clash proxy rules instead of editing system /etc/hosts.
"""

import argparse
import asyncio
import signal
from dataclasses import dataclass
from typing import Sequence

from loguru import logger


@dataclass(frozen=True)
class ConnectProxyConfig:
    """Runtime configuration for the CONNECT shim.

    Args:
        listen_host: Host interface for the shim listener.
        listen_port: Port for Clash to connect to.
        target_host: Local gateway host to tunnel traffic to.
        target_port: Local gateway HTTPS port to tunnel traffic to.
        allowed_hosts: Domain allow-list accepted by this shim.
    """

    listen_host: str
    listen_port: int
    target_host: str
    target_port: int
    allowed_hosts: tuple[str, ...]


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Pipe bytes from one stream to another until EOF."""
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except (ConnectionError, RuntimeError):
            pass


async def _read_connect_header(reader: asyncio.StreamReader) -> bytes:
    """Read one HTTP CONNECT header block.

    Args:
        reader: Client stream reader.

    Returns:
        Raw HTTP header bytes.

    Raises:
        asyncio.IncompleteReadError: If the client closes before sending headers.
        ValueError: If the header is too large.
    """
    header = await reader.readuntil(b"\r\n\r\n")
    if len(header) > 16384:
        raise ValueError("CONNECT header is too large")
    return header


def _parse_connect_host(header: bytes) -> str:
    """Extract requested hostname from a CONNECT header."""
    first_line = header.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
    parts = first_line.split()
    if len(parts) < 3 or parts[0].upper() != "CONNECT":
        raise ValueError(f"Only CONNECT is supported, got: {first_line}")
    authority = parts[1]
    host = authority.rsplit(":", 1)[0] if ":" in authority else authority
    return host.lower().strip("[]")


def _is_allowed_host(host: str, allowed_hosts: Sequence[str]) -> bool:
    """Return whether the CONNECT host is allowed."""
    return host in allowed_hosts


async def handle_connect(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    config: ConnectProxyConfig,
) -> None:
    """Handle one CONNECT tunnel from Clash."""
    peer = writer.get_extra_info("peername")
    upstream_writer: asyncio.StreamWriter | None = None
    try:
        header = await _read_connect_header(reader)
        host = _parse_connect_host(header)
        if not _is_allowed_host(host, config.allowed_hosts):
            logger.warning(f"Reject CONNECT host={host!r} peer={peer}")
            writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
            return

        logger.info(
            f"CONNECT {host} from {peer} -> "
            f"{config.target_host}:{config.target_port}"
        )
        upstream_reader, upstream_writer = await asyncio.open_connection(
            config.target_host,
            config.target_port,
        )
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()

        await asyncio.gather(
            _pipe(reader, upstream_writer),
            _pipe(upstream_reader, writer),
        )
    except (asyncio.IncompleteReadError, ConnectionError) as exc:
        logger.debug(f"CONNECT closed peer={peer}: {exc}")
    except ValueError as exc:
        logger.warning(f"Bad CONNECT request peer={peer}: {exc}")
        try:
            writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
        except ConnectionError:
            pass
    except OSError as exc:
        logger.error(f"CONNECT tunnel failed peer={peer}: {exc}")
        try:
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
        except ConnectionError:
            pass
    finally:
        if upstream_writer is not None and not upstream_writer.is_closing():
            upstream_writer.close()
            try:
                await upstream_writer.wait_closed()
            except ConnectionError:
                pass
        if not writer.is_closing():
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass


async def run_server(config: ConnectProxyConfig) -> None:
    """Run the CONNECT shim until interrupted."""
    server = await asyncio.start_server(
        lambda reader, writer: handle_connect(reader, writer, config),
        config.listen_host,
        config.listen_port,
    )
    sockets = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
    logger.info(
        f"CONNECT proxy listening on {sockets}, "
        f"target={config.target_host}:{config.target_port}, "
        f"allowed={','.join(config.allowed_hosts)}"
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    async with server:
        await stop_event.wait()
        logger.info("CONNECT proxy stopping")


def parse_args() -> ConnectProxyConfig:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Kiro Clash HTTP CONNECT shim")
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=7898)
    parser.add_argument("--target-host", default="127.0.0.1")
    parser.add_argument("--target-port", type=int, default=443)
    parser.add_argument(
        "--allow-host",
        action="append",
        default=[
            "runtime.us-east-1.kiro.dev",
            "management.us-east-1.kiro.dev",
            "q.us-east-1.amazonaws.com",
        ],
        help="Allowed CONNECT hostname. Can be repeated.",
    )
    args = parser.parse_args()
    return ConnectProxyConfig(
        listen_host=args.listen_host,
        listen_port=args.listen_port,
        target_host=args.target_host,
        target_port=args.target_port,
        allowed_hosts=tuple(host.lower() for host in args.allow_host),
    )


def main() -> None:
    """CLI entrypoint."""
    asyncio.run(run_server(parse_args()))


if __name__ == "__main__":
    main()
