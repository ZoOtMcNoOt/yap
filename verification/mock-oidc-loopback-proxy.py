from __future__ import annotations

import argparse
import asyncio
import ipaddress
import socket


_BUFFER_BYTES = 64 * 1024
_CONNECT_TIMEOUT_SECONDS = 2
_CONNECTION_TIMEOUT_SECONDS = 10
_MAX_CONNECTIONS = 32


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen-port", required=True, type=int)
    parser.add_argument("--target-address", required=True)
    parser.add_argument("--target-port", required=True, type=int)
    arguments = parser.parse_args()
    for name in ("listen_port", "target_port"):
        port = getattr(arguments, name)
        if port < 1 or port > 65_535:
            parser.error(f"{name.replace('_', '-')} must be a valid TCP port")
    target = ipaddress.ip_address(arguments.target_address)
    if target.version != 4 or target.is_unspecified or target.is_multicast:
        parser.error("target-address must be one bounded IPv4 address")
    return arguments


async def _close(writer: asyncio.StreamWriter) -> None:
    writer.close()
    try:
        await asyncio.wait_for(writer.wait_closed(), timeout=1)
    except (TimeoutError, BrokenPipeError, ConnectionError):
        pass


async def _copy(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    try:
        while chunk := await reader.read(_BUFFER_BYTES):
            writer.write(chunk)
            await writer.drain()
        try:
            writer.write_eof()
        except (AttributeError, NotImplementedError, RuntimeError):
            pass
    except (BrokenPipeError, ConnectionError):
        pass


async def _serve(
    listen_port: int,
    target_address: str,
    target_port: int,
) -> None:
    connections = asyncio.Semaphore(_MAX_CONNECTIONS)

    async def forward(
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
    ) -> None:
        if connections.locked():
            await _close(client_writer)
            return
        async with connections:
            target_writer: asyncio.StreamWriter | None = None
            try:
                target_reader, target_writer = await asyncio.wait_for(
                    asyncio.open_connection(target_address, target_port),
                    timeout=_CONNECT_TIMEOUT_SECONDS,
                )
                await asyncio.wait_for(
                    asyncio.gather(
                        _copy(client_reader, target_writer),
                        _copy(target_reader, client_writer),
                    ),
                    timeout=_CONNECTION_TIMEOUT_SECONDS,
                )
            except (TimeoutError, ConnectionError, OSError):
                pass
            finally:
                if target_writer is not None:
                    await _close(target_writer)
                await _close(client_writer)

    server = await asyncio.start_server(
        forward,
        host="127.0.0.1",
        port=listen_port,
        family=socket.AF_INET,
        backlog=_MAX_CONNECTIONS,
        reuse_address=False,
    )
    sockets = server.sockets or ()
    if len(sockets) != 1 or sockets[0].getsockname()[:2] != (
        "127.0.0.1",
        listen_port,
    ):
        server.close()
        await server.wait_closed()
        raise RuntimeError("Mock OIDC proxy did not bind numeric IPv4 loopback.")
    print("MOCK_OIDC_LOOPBACK_PROXY=READY", flush=True)
    async with server:
        await server.serve_forever()


def main() -> None:
    arguments = _arguments()
    try:
        asyncio.run(
            _serve(
                arguments.listen_port,
                arguments.target_address,
                arguments.target_port,
            )
        )
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
