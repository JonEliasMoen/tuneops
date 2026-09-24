"""Run every enabled playlist mapping without starting the Dash interface."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
import time

from main import CONFIG_PATH, LOGGER, configure_logging, run_all_syncs


def main() -> int:
    configure_logging()
    LOGGER.info("startup_sync.start config=%s", CONFIG_PATH)

    try:
        results = run_all_syncs(progress=lambda message: LOGGER.info("startup_sync.progress %s", message))
    except Exception:
        LOGGER.exception("startup_sync.failed")
        return 1

    if not results:
        LOGGER.info("startup_sync.complete no_enabled_mappings=true")
        return 0

    failures = 0
    for result in results:
        LOGGER.info("startup_sync.result %s", json.dumps(asdict(result), ensure_ascii=False))
        if result.error:
            failures += 1

    LOGGER.info("startup_sync.complete mappings=%d failures=%d", len(results), failures)
    return 1 if failures else 0


if __name__ == "__main__":
    time.sleep(60)
    sys.exit(main())
