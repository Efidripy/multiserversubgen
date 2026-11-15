#!/usr/bin/python3
"""Small root-owned PAM verifier used by the systemd socket unit."""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import json
import os
import socket
import sys
from typing import Callable, Optional

MAX_REQUEST = 4096
READ_TIMEOUT = 5.0


def validate_username(username: object) -> bool:
    return (
        isinstance(username, str)
        and 1 <= len(username) <= 256
        and "\x00" not in username
        and "\n" not in username
        and "\r" not in username
    )


def authenticate_request(
    payload: bytes,
    *,
    peer_uid: int,
    expected_uid: int,
    pam_authenticate: Callable[[str, str], bool],
) -> bytes:
    """Validate one wire request and return the deliberately tiny response."""
    ok = False
    if peer_uid == expected_uid and len(payload) <= MAX_REQUEST:
        try:
            text = payload.decode("utf-8")
            if text.count("\n") == 1 and text.endswith("\n"):
                request = json.loads(text[:-1])
                username = request.get("user") if isinstance(request, dict) else None
                password = request.get("password") if isinstance(request, dict) else None
                if (
                    isinstance(request, dict)
                    and set(request) == {"user", "password"}
                    and validate_username(username)
                    and isinstance(password, str)
                ):
                    ok = bool(pam_authenticate(username, password))
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError, TypeError, ValueError):
            ok = False
    return (b'{"ok":true}\n' if ok else b'{"ok":false}\n')


class PamAuthenticator:
    """ctypes wrapper around libpam; no Python PAM package is imported."""

    def __init__(self, service: str = "login") -> None:
        self.service = service
        self._lib = ctypes.CDLL(ctypes.util.find_library("pam") or "libpam.so.0")

    def __call__(self, username: str, password: str) -> bool:
        class PamMessage(ctypes.Structure):
            _fields_ = [("msg_style", ctypes.c_int), ("msg", ctypes.c_char_p)]

        class PamResponse(ctypes.Structure):
            # resp is a raw pointer: libpam free()s it, so it must come from libc malloc.
            _fields_ = [("resp", ctypes.c_void_p), ("resp_retcode", ctypes.c_int)]

        libc = ctypes.CDLL(None)
        libc.calloc.argtypes = [ctypes.c_size_t, ctypes.c_size_t]
        libc.calloc.restype = ctypes.c_void_p
        libc.strdup.argtypes = [ctypes.c_char_p]
        libc.strdup.restype = ctypes.c_void_p

        conversation_type = ctypes.CFUNCTYPE(
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.POINTER(PamMessage)),
            ctypes.POINTER(ctypes.POINTER(PamResponse)),
            ctypes.c_void_p,
        )
        password_bytes = password.encode("utf-8")

        @conversation_type
        def conversation(num_msg, msg, response, _data):
            if num_msg <= 0:
                return 19  # PAM_CONV_ERR
            buffer = libc.calloc(num_msg, ctypes.sizeof(PamResponse))
            if not buffer:
                return 19
            responses = ctypes.cast(buffer, ctypes.POINTER(PamResponse))
            for index in range(num_msg):
                if msg[index].contents.msg_style in (1, 2):  # PROMPT_ECHO_OFF / ON
                    responses[index].resp = libc.strdup(password_bytes)
            response[0] = responses
            return 0

        class PamConv(ctypes.Structure):
            _fields_ = [("conv", conversation_type), ("data", ctypes.c_void_p)]

        pam_start = self._lib.pam_start
        pam_start.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.POINTER(PamConv), ctypes.POINTER(ctypes.c_void_p)]
        pam_start.restype = ctypes.c_int
        pam_auth = self._lib.pam_authenticate
        pam_auth.argtypes = [ctypes.c_void_p, ctypes.c_int]
        pam_auth.restype = ctypes.c_int
        pam_end = self._lib.pam_end
        pam_end.argtypes = [ctypes.c_void_p, ctypes.c_int]
        pam_end.restype = ctypes.c_int

        handle = ctypes.c_void_p()
        conversation_struct = PamConv(conversation, None)
        status = pam_start(self.service.encode(), username.encode(), ctypes.byref(conversation_struct), ctypes.byref(handle))
        if status != 0:
            return False
        try:
            auth_status = pam_auth(handle, 0)
            return auth_status == 0
        finally:
            pam_end(handle, locals().get("auth_status", status))


def serve_connection(conn: socket.socket, expected_uid: int, pam_auth: Callable[[str, str], bool]) -> None:
    conn.settimeout(READ_TIMEOUT)
    peer = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
    peer_uid = int.from_bytes(peer[4:8], byteorder=sys.byteorder, signed=False)
    data = b""
    try:
        while len(data) <= MAX_REQUEST:
            chunk = conn.recv(min(1024, MAX_REQUEST + 1 - len(data)))
            if not chunk:
                break
            data += chunk
            if b"\n" in data:
                break
    except socket.timeout:
        data = b""
    conn.sendall(authenticate_request(data, peer_uid=peer_uid, expected_uid=expected_uid, pam_authenticate=pam_auth))


def self_check(path: str) -> int:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(READ_TIMEOUT)
        client.connect(path)
        client.sendall(b'{"user":"__sub_manager_probe__","password":"invalid"}\n')
        return 0 if json.loads(client.recv(64).decode("utf-8")).get("ok") is False else 1


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--uid", type=int)
    parser.add_argument("--pam-service", default="login")
    parser.add_argument("--self-check")
    args = parser.parse_args(argv)
    if args.self_check:
        return self_check(args.self_check)
    if args.uid is None or args.uid < 0:
        return 2
    pam_auth = PamAuthenticator(args.pam_service)
    with socket.socket(fileno=os.dup(0)) as conn:
        serve_connection(conn, args.uid, pam_auth)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
