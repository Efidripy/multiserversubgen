from __future__ import annotations


def get_requests_verify_value(*, verify_tls: bool, ca_bundle_path: str):
    if not verify_tls:
        return False
    if ca_bundle_path:
        return ca_bundle_path
    return True
