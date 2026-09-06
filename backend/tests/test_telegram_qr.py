from __future__ import annotations

import os
import sys

import pytest


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.telegram_qr import TelegramQrError, build_subscription_qr_png


def test_build_subscription_qr_png_is_local_png_for_https_url():
    png = build_subscription_qr_png("https://bot.example.test/api/v1/sub/opaque-token")

    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(png) < 1_000_000


@pytest.mark.parametrize("url", ["http://bot.example.test/token", "vless://opaque", "https://" + "a" * 2049])
def test_build_subscription_qr_png_rejects_unsafe_or_oversized_urls(url):
    with pytest.raises(TelegramQrError):
        build_subscription_qr_png(url)
