"""Default cloud egress. Metadata, private ranges, and the Docker socket stay blocked."""

from __future__ import annotations

import ipaddress

METADATA_IP = "169.254.169.254"
SOCKET_PATH = "/var/run/docker.sock"


class EgressBlocked(PermissionError):
    def __init__(self, target: str) -> None:
        self.target = target
        super().__init__(f"egress blocked: {target}")


def destination_blocked(target: str) -> bool:
    if "docker.sock" in target or target == SOCKET_PATH:
        return True
    if target == METADATA_IP:
        return True
    try:
        address = ipaddress.ip_address(target)
    except ValueError:
        return False
    return bool(address.is_private or address.is_link_local or address.is_loopback)


def guard(policy: object) -> None:
    """Refuse a policy that would open metadata, private ranges, or the socket."""
    network_mode = getattr(policy, "network_mode", "")
    block_metadata = getattr(policy, "block_metadata", False)
    block_private = getattr(policy, "block_private", False)
    if network_mode != "none" or not block_metadata or not block_private:
        raise EgressBlocked("network")
    if not destination_blocked(METADATA_IP) or not destination_blocked(SOCKET_PATH):
        raise EgressBlocked(METADATA_IP)
