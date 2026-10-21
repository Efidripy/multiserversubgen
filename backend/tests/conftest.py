import os

# Production defaults to REQUIRE_PERSISTENT_SECRETS=true; tests run without provisioned secrets.
os.environ.setdefault("REQUIRE_PERSISTENT_SECRETS", "false")
