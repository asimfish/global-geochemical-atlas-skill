#!/usr/bin/env python3
"""Minimal fail-closed HTTP CONNECT proxy for the evaluation network."""

from __future__ import annotations

import ipaddress
import os
import select
import socket
import socketserver
import sys
from urllib.parse import urlsplit


MAX_HEADER = 64 * 1024
TIMEOUT = 30


def normalized_rules(value: str) -> tuple[str, ...]:
    rules = []
    for raw in value.split(","):
        rule = raw.strip().casefold().rstrip(".")
        if rule and rule not in rules:
            rules.append(rule)
    return tuple(rules)


def host_allowed(host: str, rules: tuple[str, ...]) -> bool:
    value = host.casefold().rstrip(".")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        pass
    else:
        return False
    for rule in rules:
        suffix = rule[1:] if rule.startswith(".") else rule
        if value == suffix or (rule.startswith(".") and value.endswith(f".{suffix}")):
            return True
    return False


def public_addresses(host: str, port: int) -> list[tuple[int, int, int, str, tuple[object, ...]]]:
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    safe = []
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if ip.is_global:
            safe.append(address)
    return safe


def connect_public(host: str, port: int) -> socket.socket:
    last_error: OSError | None = None
    for family, socktype, proto, _, sockaddr in public_addresses(host, port):
        outbound = socket.socket(family, socktype, proto)
        outbound.settimeout(TIMEOUT)
        try:
            outbound.connect(sockaddr)
            return outbound
        except OSError as exc:
            last_error = exc
            outbound.close()
    raise OSError(f"no public address reachable for {host}:{port}: {last_error}")


class ProxyHandler(socketserver.StreamRequestHandler):
    rules: tuple[str, ...] = ()

    def read_headers(self) -> tuple[str, list[bytes]]:
        first = self.rfile.readline(MAX_HEADER + 1)
        if not first or len(first) > MAX_HEADER:
            raise ValueError("invalid request line")
        lines = []
        total = len(first)
        while True:
            line = self.rfile.readline(MAX_HEADER + 1)
            total += len(line)
            if total > MAX_HEADER:
                raise ValueError("request headers too large")
            if line in {b"\r\n", b"\n", b""}:
                break
            lines.append(line)
        return first.decode("iso-8859-1").rstrip("\r\n"), lines

    def handle(self) -> None:
        try:
            request_line, headers = self.read_headers()
            method, target, version = request_line.split(" ", 2)
            if method.upper() == "CONNECT":
                self.handle_connect(target)
            elif method.upper() in {"GET", "HEAD"}:
                self.handle_http(method.upper(), target, version, headers)
            else:
                self.send_error(405, "method not allowed")
        except (OSError, ValueError) as exc:
            self.send_error(502, str(exc))

    def send_error(self, code: int, message: str) -> None:
        try:
            body = f"{code} {message}\n".encode("utf-8", errors="replace")
            self.wfile.write(
                f"HTTP/1.1 {code} Proxy Error\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
                + body
            )
        except OSError:
            pass

    def checked_target(self, host: str, port: int) -> None:
        if port not in {80, 443}:
            raise ValueError("only ports 80 and 443 are allowed")
        if not host_allowed(host, self.rules):
            raise ValueError(f"hostname is not allowlisted: {host}")

    def handle_connect(self, target: str) -> None:
        if ":" not in target:
            raise ValueError("CONNECT target must include a port")
        host, port_text = target.rsplit(":", 1)
        port = int(port_text)
        self.checked_target(host, port)
        with connect_public(host, port) as outbound:
            self.wfile.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            self.wfile.flush()
            self.relay(self.connection, outbound)

    def handle_http(self, method: str, target: str, version: str, headers: list[bytes]) -> None:
        parsed = urlsplit(target)
        if parsed.scheme != "http" or not parsed.hostname:
            raise ValueError("plain HTTP proxy requests require an absolute http:// URL")
        port = parsed.port or 80
        self.checked_target(parsed.hostname, port)
        path = parsed.path or "/"
        if parsed.query:
            path += f"?{parsed.query}"
        filtered = [line for line in headers if not line.lower().startswith((b"proxy-connection:", b"connection:"))]
        with connect_public(parsed.hostname, port) as outbound:
            outbound.sendall(f"{method} {path} {version}\r\n".encode("iso-8859-1"))
            for line in filtered:
                outbound.sendall(line)
            outbound.sendall(b"Connection: close\r\n\r\n")
            while data := outbound.recv(64 * 1024):
                self.connection.sendall(data)

    @staticmethod
    def relay(left: socket.socket, right: socket.socket) -> None:
        sockets = [left, right]
        while True:
            readable, _, _ = select.select(sockets, [], [], TIMEOUT)
            if not readable:
                return
            for source in readable:
                data = source.recv(64 * 1024)
                if not data:
                    return
                (right if source is left else left).sendall(data)


class ThreadingProxy(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> int:
    rules = normalized_rules(os.environ.get("EVAL_ALLOWED_HOSTS", ""))
    if not rules:
        print("EVAL_ALLOWED_HOSTS is empty", file=sys.stderr)
        return 73
    ProxyHandler.rules = rules
    port = int(os.environ.get("EVAL_PROXY_PORT", "8080"))
    with ThreadingProxy(("0.0.0.0", port), ProxyHandler) as server:
        print(f"allowlist proxy listening on {port} for {len(rules)} rules", flush=True)
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
