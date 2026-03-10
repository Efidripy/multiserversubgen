"""Data models for the 3X-UI integration layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class XUIInbound:
    """Represents a 3X-UI inbound configuration."""

    id: int
    remark: str
    protocol: str
    port: int
    enable: bool
    settings: Dict[str, Any] = field(default_factory=dict)
    stream_settings: Dict[str, Any] = field(default_factory=dict)
    sniffing: Dict[str, Any] = field(default_factory=dict)
    node_id: Optional[int] = None
    node_name: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any], *, node_id: Optional[int] = None) -> "XUIInbound":
        return cls(
            id=data.get("id", 0),
            remark=data.get("remark", ""),
            protocol=data.get("protocol", ""),
            port=data.get("port", 0),
            enable=data.get("enable", True),
            settings=data.get("settings", {}),
            stream_settings=data.get("streamSettings", {}),
            sniffing=data.get("sniffing", {}),
            node_id=node_id,
        )


@dataclass
class XUIClient:
    """Represents a single VPN client within an inbound."""

    id: str
    email: str
    enable: bool = True
    up: int = 0
    down: int = 0
    expiry_time: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def total_traffic(self) -> int:
        return self.up + self.down

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "XUIClient":
        return cls(
            id=data.get("id", ""),
            email=data.get("email", ""),
            enable=data.get("enable", True),
            up=data.get("up", 0),
            down=data.get("down", 0),
            expiry_time=data.get("expiryTime", 0),
            extra={k: v for k, v in data.items()
                   if k not in ("id", "email", "enable", "up", "down", "expiryTime")},
        )


@dataclass
class NodeSnapshot:
    """A single point-in-time snapshot of a node's state."""

    node_id: int
    node_name: str
    available: bool
    xray_running: bool
    cpu: float = 0.0
    online_clients: int = 0
    traffic_total: float = 0.0
    poll_ms: float = 0.0
    inbounds: List[XUIInbound] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "name": self.node_name,
            "available": self.available,
            "xray_running": self.xray_running,
            "cpu": self.cpu,
            "online_clients": self.online_clients,
            "traffic_total": self.traffic_total,
            "poll_ms": self.poll_ms,
            "error": self.error,
        }
