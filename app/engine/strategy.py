from __future__ import annotations
from typing import Dict, Any, List


async def simple_signal(context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Placeholder strategy: no real signals yet.
    Returns an empty list. Wire your logic here later.
    Each signal example:
      {"symbol":"AAPL","side":"buy","qty":1,"type":"market"}
    """
    _ = context
    return []

