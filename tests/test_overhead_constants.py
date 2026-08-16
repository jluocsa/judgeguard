"""The baked-in overhead constants must match what the installed SDK ships.

If this fails after an SDK upgrade, run `estimate.measure_overhead()` and update
PROMPT_OVERHEAD_TOKENS. A silently stale constant understates cost.
"""

from __future__ import annotations

import pytest

from judgeguard.estimate import PROMPT_OVERHEAD_TOKENS


def test_constants_match_the_installed_templates():
    # Imported inside the test so collection does not pull the SDK into sys.modules,
    # which would mask the no-SDK-import invariant elsewhere in the suite.
    pytest.importorskip("azure.ai.evaluation", reason="needs the foundry extra")
    from judgeguard.estimate import measure_overhead

    measured = measure_overhead()
    assert measured, "no prompty templates found in the installed SDK"
    stale = {
        dimension: (value, PROMPT_OVERHEAD_TOKENS[dimension])
        for dimension, value in measured.items()
        if value != PROMPT_OVERHEAD_TOKENS[dimension]
    }
    assert not stale, f"overhead constants are stale (measured, constant): {stale}"