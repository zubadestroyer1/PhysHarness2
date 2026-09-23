"""Shared, bounded operator resource policy; standalone inside the trusted image."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

DEFAULT_PROFILE = {
    "protocol": "physharness-verifier-resources-v1",
    "memory_bytes": 8 * 1024**3,
    "cpus": 4,
    "comparator_timeout_seconds": 600,
    "comparator_output_limit_bytes": 256_000,
    "checker_slots": 1,
}
LIMITS = {
    "memory_bytes": (1024**3, 16 * 1024**3),
    "cpus": (1, 8),
    "comparator_timeout_seconds": (1, 1800),
    "comparator_output_limit_bytes": (4096, 2_000_000),
    "checker_slots": (1, 1),
}
HOST_GRACE_SECONDS = 30


def validate_profile(profile):
    if not isinstance(profile, dict) or set(profile) != set(DEFAULT_PROFILE):
        raise ValueError("A complete, versioned resource profile is required")
    if profile["protocol"] != DEFAULT_PROFILE["protocol"]:
        raise ValueError("Unsupported resource profile protocol")
    for name, (low, high) in LIMITS.items():
        if type(profile[name]) is not int or not low <= profile[name] <= high:
            raise ValueError(f"Resource {name} must be an integer from {low} to {high}")
    return dict(profile)


def parse_profile(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate resource profile key")
            result[key] = value
        return result

    if len(data) > 16_384:
        raise ValueError("Resource profile exceeds its size bound")
    return validate_profile(json.loads(data, object_pairs_hook=unique))


def profile_bytes(profile):
    return (
        json.dumps(validate_profile(profile), sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def profile_digest(profile):
    return hashlib.sha256(profile_bytes(profile)).hexdigest()


def policy_digest():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def host_timeout(profile):
    return validate_profile(profile)["comparator_timeout_seconds"] + HOST_GRACE_SECONDS


def host_output_limit(profile):
    # A JSON receipt may escape every captured byte; reserve space for fixed metadata.
    return 6 * validate_profile(profile)["comparator_output_limit_bytes"] + 131_072


def read_memory_events(path=Path("/sys/fs/cgroup/memory.events")):
    try:
        lines = path.read_text().splitlines()
        events = {}
        for line in lines:
            name, count = line.split()
            if name in events or not count.isdecimal():
                raise ValueError("Invalid cgroup memory event counter")
            events[name] = int(count)
        if "oom_kill" not in events:
            raise ValueError("cgroup v2 oom_kill counter is missing")
        return {"status": "observed", "events": events}
    except (OSError, ValueError) as error:
        return {"status": "unavailable", "error": str(error)[:500]}


def confirmed_oom(before, after):
    if not isinstance(before, dict) or not isinstance(after, dict):
        return False
    for key in ("oom_kill", "oom_group_kill"):
        if type(before.get(key)) is int and type(after.get(key)) is int:
            if after[key] > before[key] >= 0:
                return True
    return False
