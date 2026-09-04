"""Deliberately awkward wrapper — simulates 2009 provisioning protocol.

Real 2009 system might be SOAP, TL1, telnet CLI, or CSV over FTP.
We simulate "bytes in, bytes out, session header required, pipe-delimited" so the adapter has something to hide.

This file is INTERNAL — not the seam. Tests should hit adapter, per ADR 0002.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .db import get_connection, run, DB_PATH


class LegacyProtocolError(RuntimeError):
    pass


class LegacyProtocolWrapper:
    """Awkward protocol:

    - Must call `open_session(b"SESSION:<tech_id>")` first, returns session token bytes.
    - Every command is bytes: b"GET_WIFI|<SUBS_ID>|<SESSION_TOKEN>"
    - Response is bytes: b"OK|SSID|PSK" or b"ERR|reason"
    - No JSON, no REST, pipe-delimited, session token validated each call.
    """

    def __init__(self, db_path: Path | None = None):
        self.db_path: Path = db_path or DB_PATH
        self._session_token: bytes | None = None
        self._tech_id: str | None = None

    def open_session(self, raw: bytes) -> bytes:
        # raw expected b"SESSION:<tech_id>"
        if not raw.startswith(b"SESSION:"):
            raise LegacyProtocolError(b"ERR|bad session header".decode())
        tech_id = raw.split(b":", 1)[1].decode().strip()
        if not tech_id:
            raise LegacyProtocolError("ERR|empty tech_id")
        self._tech_id = tech_id
        # token is trivial — real system would be some handshake
        self._session_token = f"TOK-{tech_id}".encode()
        return self._session_token

    def _require_session(self, token: bytes) -> None:
        if self._session_token is None or token != self._session_token:
            raise LegacyProtocolError("ERR|invalid or missing session token")

    def execute(self, raw: bytes) -> bytes:
        """Execute raw command bytes, return raw response bytes."""
        try:
            text = raw.decode()
        except UnicodeDecodeError as e:
            return b"ERR|decode failed"

        parts = text.split("|")
        if len(parts) < 1:
            return b"ERR|empty command"
        cmd = parts[0]

        if cmd == "GET_WIFI":
            if len(parts) != 3:
                return b"ERR|GET_WIFI requires SUBS_ID|TOKEN"
            subs_id, token = parts[1], parts[2].encode()
            self._require_session(token)
            return self._get_wifi(subs_id)
        elif cmd == "GET_LINE":
            if len(parts) != 3:
                return b"ERR|GET_LINE requires SUBS_ID|TOKEN"
            subs_id, token = parts[1], parts[2].encode()
            self._require_session(token)
            return self._get_line(subs_id)
        elif cmd == "GET_PROFILE":
            if len(parts) != 3:
                return b"ERR|GET_PROFILE requires SUBS_ID|TOKEN"
            subs_id, token = parts[1], parts[2].encode()
            self._require_session(token)
            return self._get_profile(subs_id)
        elif cmd == "RESET_ONT":
            if len(parts) != 3:
                return b"ERR|RESET_ONT requires SUBS_ID|TOKEN"
            subs_id, token = parts[1], parts[2].encode()
            self._require_session(token)
            return self._reset_ont(subs_id)
        elif cmd == "GET_OLT_SUBS":
            if len(parts) != 3:
                return b"ERR|GET_OLT_SUBS requires OLT_ID|TOKEN"
            olt_id, token = parts[1], parts[2].encode()
            self._require_session(token)
            return self._get_olt_subs(olt_id)
        else:
            return b"ERR|unknown cmd"

    def _get_wifi(self, subs_id: str) -> bytes:
        conn = get_connection(self.db_path)
        try:
            cur = run(conn, "SELECT WIFI_SSID, WIFI_PSK FROM SUBS_TBL WHERE SUBS_ID=?", (subs_id,))
            row = cur.fetchone()
            if not row:
                return b"ERR|subscriber not found"
            ssid, psk = row["WIFI_SSID"], row["WIFI_PSK"]
            return f"OK|{ssid}|{psk}".encode()
        finally:
            conn.close()

    def _get_line(self, subs_id: str) -> bytes:
        conn = get_connection(self.db_path)
        try:
            cur = run(conn, "SELECT LINE_STAT, OLT_ID, ONT_SN FROM SUBS_TBL WHERE SUBS_ID=?", (subs_id,))
            row = cur.fetchone()
            if not row:
                return b"ERR|subscriber not found"
            return f"OK|{row['LINE_STAT']}|{row['OLT_ID']}|{row['ONT_SN']}".encode()
        finally:
            conn.close()

    def _get_profile(self, subs_id: str) -> bytes:
        conn = get_connection(self.db_path)
        try:
            cur = run(conn, "SELECT SUBS_ID, SITE_CD, ONT_SN, WIFI_SSID, LINE_STAT, OLT_ID FROM SUBS_TBL WHERE SUBS_ID=?",
                (subs_id,),
            )
            row = cur.fetchone()
            if not row:
                return b"ERR|subscriber not found"
            # OK|SUBS_ID|SITE_CD|ONT_SN|WIFI_SSID|LINE_STAT|OLT_ID (no PSK on purpose)
            return f"OK|{row['SUBS_ID']}|{row['SITE_CD']}|{row['ONT_SN']}|{row['WIFI_SSID']}|{row['LINE_STAT']}|{row['OLT_ID']}".encode()
        finally:
            conn.close()

    def _reset_ont(self, subs_id: str) -> bytes:
        conn = get_connection(self.db_path)
        try:
            cur = run(conn, "SELECT ONT_SN, OLT_ID, LINE_STAT FROM SUBS_TBL WHERE SUBS_ID=?", (subs_id,))
            row = cur.fetchone()
            if not row:
                return b"ERR|subscriber not found"
            ont_sn = row["ONT_SN"]
            # Simulate 2009 TL1 INIT-ONT: flap DOWN then UP. We set UP to show effect.
            run(conn, "UPDATE SUBS_TBL SET LINE_STAT='UP' WHERE SUBS_ID=?", (subs_id,))
            conn.commit()
            return f"OK|{ont_sn}|RESET_INITIATED".encode()
        finally:
            conn.close()

    def _get_olt_subs(self, olt_id: str) -> bytes:
        conn = get_connection(self.db_path)
        try:
            cur = run(conn, "SELECT SUBS_ID, LINE_STAT FROM SUBS_TBL WHERE OLT_ID=?", (olt_id,))
            rows = cur.fetchall()
            if not rows:
                return b"ERR|olt not found"
            # OK|count|SUBS1:STAT1,SUBS2:STAT2
            payload = ",".join(f"{r['SUBS_ID']}:{r['LINE_STAT']}" for r in rows)
            return f"OK|{len(rows)}|{payload}".encode()
        finally:
            conn.close()
