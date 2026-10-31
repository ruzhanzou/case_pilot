"""Run tests with optional telemetry disabled and outbound sockets loopback-only."""
import ipaddress
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "apps/agent/src")]

# Remove credentials by name only, before importing application settings/SDKs.
for key in tuple(os.environ):
    if key.endswith(("_API_KEY", "_API_TOKEN", "_ACCESS_TOKEN")):
        os.environ.pop(key, None)

for key, value in {
    "ORT_DISABLE_TELEMETRY": "1", "OTEL_SDK_DISABLED": "true",
    "OPENAI_AGENTS_DISABLE_TRACING": "1", "DO_NOT_TRACK": "1",
    "CASEPILOT_AGENT_PROVIDER": "mock", "CASEPILOT_AI_MODE": "mock",
}.items():
    os.environ[key] = value

original_getaddrinfo = socket.getaddrinfo
original_connect = socket.socket.connect
original_connect_ex = socket.socket.connect_ex


def require_loopback(host):
    if host == "localhost":
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise RuntimeError("Offline test attempted non-loopback egress")


def getaddrinfo(host, *args, **kwargs):
    require_loopback(host)
    return original_getaddrinfo(host, *args, **kwargs)


def connect(self, address):
    if isinstance(address, tuple):
        require_loopback(address[0])
    return original_connect(self, address)


def connect_ex(self, address):
    if isinstance(address, tuple):
        require_loopback(address[0])
    return original_connect_ex(self, address)


socket.getaddrinfo = getaddrinfo
socket.socket.connect = connect
socket.socket.connect_ex = connect_ex
from casepilot_agent.config import AgentSettings
from casepilot_api.config import Settings

Settings.model_config["env_file"] = None
AgentSettings.model_config["env_file"] = None
import logging

logging.getLogger("openai.agents").setLevel(logging.CRITICAL + 1)
import pytest

raise SystemExit(pytest.main(sys.argv[1:]))
