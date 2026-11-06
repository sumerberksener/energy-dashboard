"""Shared fixtures for the offline network tests."""
from __future__ import annotations

import ipaddress
import os
import socket

import pytest


@pytest.fixture(autouse=True)
def _loopback_never_proxied(monkeypatch):
    """Keep 127.0.0.1 traffic off any proxy configured on the developer machine."""
    for var in ("NO_PROXY", "no_proxy"):
        existing = os.environ.get(var, "")
        monkeypatch.setenv(var, ",".join(filter(None, [existing, "127.0.0.1,localhost"])))


@pytest.fixture
def offline(monkeypatch):
    """Refuse every non-loopback DNS lookup and connection, so a test that
    forgot to fake a source fails loudly instead of reaching the internet.
    Opt in with `pytestmark = pytest.mark.usefixtures("offline")`."""
    def is_loopback(host) -> bool:
        if host in (None, "", "localhost"):
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def check(address) -> None:
        if isinstance(address, tuple) and address and not is_loopback(address[0]):
            raise OSError(f"offline fixture: blocked connect to {address[0]}")

    def connect(self, address):
        check(address)
        return real_connect(self, address)

    def connect_ex(self, address):
        check(address)
        return real_connect_ex(self, address)

    def getaddrinfo(host, *args, **kwargs):
        if not is_loopback(host):
            raise socket.gaierror(-2, f"offline fixture: blocked DNS lookup for {host}")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
