"""Feature flag system for runtime feature control and A/B testing.

Usage::

    flags = FeatureFlags()
    flags.load_from_file("config/feature_flags.yaml")

    # Simple on/off
    if flags.is_enabled("new_polling_algorithm"):
        await new_strategy()

    # Per-user A/B flag
    if flags.is_enabled_for_user("beta_ui", user_id=42):
        return beta_response

    # Programmatic toggle (e.g. from admin API)
    flags.set_flag("new_polling_algorithm", enabled=True)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class FlagDefinition:
    """Internal representation of a single feature flag."""

    name: str
    enabled: bool = False
    rollout_percentage: int = 100
    enabled_users: Set[Any] = field(default_factory=set)
    metadata: Dict[str, Any] = field(default_factory=dict)


class FeatureFlags:
    """Runtime feature-flag manager.

    Flag values can be loaded from a YAML config file (requires PyYAML),
    set programmatically, or queried at any time.

    The *rollout_percentage* field (0-100) enables gradual / canary
    rollouts: the flag is considered enabled for a user if the hash of the
    user-id falls within the configured percentage.
    """

    def __init__(self) -> None:
        self._flags: Dict[str, FlagDefinition] = {}

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_from_file(self, path: str) -> None:
        """Load flag definitions from a YAML file.

        The file is expected to have the structure::

            flags:
              my_flag:
                enabled: true
                rollout_percentage: 50
                enabled_users: [1, 2, 3]

        Missing keys use their default values.  If PyYAML is not installed
        the method logs a warning and does nothing.

        Args:
            path: Path to the YAML file (relative or absolute).
        """
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError:
            logger.warning(
                "FeatureFlags: PyYAML not installed – cannot load flags from %s",
                path,
            )
            return

        if not os.path.exists(path):
            logger.warning("FeatureFlags: config file not found: %s", path)
            return

        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}

        for flag_name, attrs in (raw.get("flags") or {}).items():
            if attrs is None:
                attrs = {}
            self._flags[flag_name] = FlagDefinition(
                name=flag_name,
                enabled=bool(attrs.get("enabled", False)),
                rollout_percentage=int(attrs.get("rollout_percentage", 100)),
                enabled_users=set(attrs.get("enabled_users") or []),
                metadata={k: v for k, v in attrs.items()
                           if k not in ("enabled", "rollout_percentage", "enabled_users")},
            )
        logger.info("FeatureFlags: loaded %d flags from %s", len(self._flags), path)

    def load_from_dict(self, data: Dict[str, Any]) -> None:
        """Load flags from an already-parsed dict (same structure as YAML)."""
        for flag_name, attrs in (data.get("flags") or {}).items():
            if attrs is None:
                attrs = {}
            self._flags[flag_name] = FlagDefinition(
                name=flag_name,
                enabled=bool(attrs.get("enabled", False)),
                rollout_percentage=int(attrs.get("rollout_percentage", 100)),
                enabled_users=set(attrs.get("enabled_users") or []),
            )

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def is_enabled(self, flag_name: str) -> bool:
        """Return ``True`` if the flag is globally enabled.

        If the flag is not registered it is treated as disabled.
        """
        flag = self._flags.get(flag_name)
        if flag is None:
            return False
        return flag.enabled

    def is_enabled_for_user(self, flag_name: str, user_id: Any) -> bool:
        """Return ``True`` if the flag is enabled for a specific user.

        A flag is enabled for a user when:
        1. The flag is globally enabled **AND**
        2. Either the user is in ``enabled_users``, or their hash-bucket
           falls within ``rollout_percentage``.

        Args:
            flag_name: Name of the flag.
            user_id: Any hashable user identifier.
        """
        flag = self._flags.get(flag_name)
        if flag is None or not flag.enabled:
            return False
        if user_id in flag.enabled_users:
            return True
        if flag.rollout_percentage >= 100:
            return True
        if flag.rollout_percentage <= 0:
            return False
        # Stable hash-based bucket
        bucket = hash(f"{flag_name}:{user_id}") % 100
        return bucket < flag.rollout_percentage

    # ------------------------------------------------------------------
    # Management
    # ------------------------------------------------------------------

    def set_flag(self, flag_name: str, *, enabled: bool) -> None:
        """Enable or disable a flag by name.

        Creates the flag definition if it doesn't yet exist.
        """
        if flag_name not in self._flags:
            self._flags[flag_name] = FlagDefinition(name=flag_name)
        self._flags[flag_name].enabled = enabled
        logger.info("FeatureFlags: '%s' set to enabled=%s", flag_name, enabled)

    def register_flag(
        self,
        flag_name: str,
        *,
        enabled: bool = False,
        rollout_percentage: int = 100,
        enabled_users: Optional[List[Any]] = None,
    ) -> None:
        """Register a flag with an explicit default.

        Existing flags are **not** overwritten unless the flag has never
        been registered (allows config-file values to win).
        """
        if flag_name not in self._flags:
            self._flags[flag_name] = FlagDefinition(
                name=flag_name,
                enabled=enabled,
                rollout_percentage=rollout_percentage,
                enabled_users=set(enabled_users or []),
            )

    def all_flags(self) -> List[dict]:
        """Return a list of all flag definitions as plain dicts."""
        return [
            {
                "name": f.name,
                "enabled": f.enabled,
                "rollout_percentage": f.rollout_percentage,
                "enabled_users": sorted(f.enabled_users),
            }
            for f in self._flags.values()
        ]

    def __repr__(self) -> str:
        return f"<FeatureFlags flags={list(self._flags.keys())!r}>"
