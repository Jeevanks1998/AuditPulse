"""
Shared test setup. The fixture websites used by the consent, analytics and
journey tests are served on 127.0.0.1, which the SSRF guard
(utils/net_guard.py) blocks in production — allow it for the test run only.
tests/test_net_guard.py switches it back off to test the guard itself.
"""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from config.settings import settings  # noqa: E402

settings.ALLOW_PRIVATE_NETWORK_TARGETS = True
