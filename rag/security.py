"""Defense in depth; pattern checks are deliberately not a security boundary."""

import hashlib
import hmac
import ipaddress
import json
import re

from .types import Principal

PII = [
    (re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"), "[EMAIL]"),
    (re.compile(r"(?<!\w)(?:\+\d{1,3}[ -]?)?(?:\d[ -]?){10,12}(?!\w)"), "[PHONE_OR_ID]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
]
INJECTION = re.compile(
    r"ignore\s+(?:all\s+)?(?:previous|prior|system)\s+instructions|"
    r"(?:reveal|print|exfiltrate)\s+(?:the\s+)?(?:system\s+prompt|secrets|credentials)|"
    r"<\|(?:system|im_start)\|>|\[INST\]",
    re.IGNORECASE,
)


def redact(text: str) -> str:
    for pattern, replacement in PII:
        text = pattern.sub(replacement, text)
    return text


def quarantine(text: str) -> bool:
    return bool(INJECTION.search(text))


def authenticate(token: str, config: str) -> Principal:
    """Opaque random service tokens mapped server-side, SHA-256 hashes only in config."""
    digest = hashlib.sha256(token.encode()).hexdigest()
    for item in json.loads(config):
        if hmac.compare_digest(digest, item["sha256"]):
            return Principal(item["tenant"], item["user"], tuple(item.get("groups", [])), item.get("admin", False))
    raise PermissionError("Invalid credentials")


def public_address(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return ip.is_global and not ip.is_multicast
