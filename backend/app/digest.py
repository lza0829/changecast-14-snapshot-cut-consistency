from __future__ import annotations

import hashlib
import json
from typing import Any


def payload_digest(payload: Any) -> str:
    """SHA-256 over a canonical JSON rendering of the payload.

    Canonical: sorted keys, no insignificant whitespace, UTF-8 preserved.
    Deleted rows carry a null payload; the digest of null is stable.
    """
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
