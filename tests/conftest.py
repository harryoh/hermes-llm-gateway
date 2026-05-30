from __future__ import annotations

import os
import tempfile

os.environ.setdefault("HERMES_ALLOW_INSECURE_DEV", "1")
os.environ.setdefault("GATEWAY_API_KEY", "")
os.environ.setdefault("HERMES_STATE_DIR", tempfile.mkdtemp(prefix="hermes-gw-test-state-"))
os.environ.setdefault("HERMES_WORK_DIR", tempfile.mkdtemp(prefix="hermes-gw-test-work-"))
