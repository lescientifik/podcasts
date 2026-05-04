"""Mesure le coût d'un appel OpenRouter via l'endpoint `/api/v1/credits`.

Le cumul `data.total_usage` (en USD) augmente strictement à chaque appel facturé.
On en prend deux snapshots autour du bloc à mesurer (TTS ou cover), la différence
donne le coût effectivement débité par OpenRouter — pas une estimation.

Utilisation type :

    from _cost import get_total_usage, write_cost

    before = get_total_usage(api_key)
    # ... appels OpenRouter ...
    after = get_total_usage(api_key)
    write_cost(Path("cost_tts.json"), step="tts", before=before, after=after)

Repli silencieux : si l'endpoint est inaccessible (réseau, 5xx), on retourne
None et le caller écrit `usd_used: null` au lieu de planter le pipeline pour
une simple télémétrie.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

CREDITS_URL: str = "https://openrouter.ai/api/v1/credits"


def get_total_usage(api_key: str, timeout: float = 10.0) -> float | None:
    """Renvoie `data.total_usage` (USD cumulés sur la clé) ou None si l'API échoue."""
    request = urllib.request.Request(
        CREDITS_URL,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None
    try:
        return float(payload["data"]["total_usage"])
    except (KeyError, TypeError, ValueError):
        return None


def write_cost(
    path: Path,
    step: str,
    before: float | None,
    after: float | None,
) -> None:
    """Écrit `{step, usd_used, balance_before, balance_after}` en JSON.

    `usd_used` vaut None si l'un des deux snapshots a échoué, et est clampé à
    0 si le delta est négatif (cas pathologique : remboursement, ajustement).
    """
    if before is None or after is None:
        usd_used: float | None = None
    else:
        usd_used = max(0.0, after - before)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "step": step,
                "usd_used": usd_used,
                "balance_before": before,
                "balance_after": after,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
