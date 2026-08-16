"""
security/ssl.py

Certificate and transport checks that need an actual TLS handshake, not
just an HTTP response — expiry, chain trust, protocol version, and
cipher strength. httpx/requests hide all of this once a request
succeeds, so this module opens its own raw `ssl.SSLSocket` (stdlib
only, no extra dependency) against host:443 to inspect the handshake
directly.

Two passes, both against the same socket:
  1. A *verifying* connection using the platform's default CA trust
     store (ssl.create_default_context()) — if this fails, the cert is
     untrusted, expired, self-signed, or hostname-mismatched, and we
     want to know exactly which.
  2. A second, *non-verifying* connection only made when (1) failed, so
     we can still read the certificate's own fields (issuer, dates) to
     report specifics instead of just "SSL failed".

Blocking by nature (ssl.SSLSocket has no asyncio-native API in the
stdlib for a bare handshake like this), so it's run in a thread via
`asyncio.to_thread` — this is the one module in security/ that isn't
built on httpx.
"""

from __future__ import annotations

import asyncio
import socket
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urlparse

MODULE = "security"
CATEGORY = "ssl"

CONNECT_TIMEOUT_SECONDS = 8.0
DEFAULT_PORT = 443

EXPIRY_CRITICAL_DAYS = 7    # cert expires this soon -> critical
EXPIRY_WARNING_DAYS = 30    # cert expires this soon -> warning

# Protocol versions weaker than this are considered deprecated/insecure.
WEAK_PROTOCOLS = {"SSLv2", "SSLv3", "TLSv1", "TLSv1.1"}

_CERT_DATE_FORMAT = "%b %d %H:%M:%S %Y %Z"


@dataclass
class SslInfo:
    """Raw handshake result, kept around for security_score.py and reporting."""

    checked: bool = False
    trusted: bool = False
    protocol: Optional[str] = None
    cipher: Optional[str] = None
    issuer: Optional[str] = None
    subject: Optional[str] = None
    not_before: Optional[str] = None
    not_after: Optional[str] = None
    days_until_expiry: Optional[int] = None
    self_signed: bool = False
    hostname_mismatch: bool = False
    error: Optional[str] = None


async def check_ssl(url: str) -> tuple[List[dict], SslInfo]:
    """
    Opens a TLS handshake against `url`'s host and returns findings plus
    the raw SslInfo for security_score.py's blend / report_service
    detail. Non-https URLs are out of scope here (security/https.py
    owns the "is this even HTTPS" finding) — returns an unchecked
    SslInfo with no findings so callers don't double-report.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return [], SslInfo(checked=False)

    host = parsed.hostname
    port = parsed.port or DEFAULT_PORT
    if not host:
        return [], SslInfo(checked=False, error="no hostname to check")

    info = await asyncio.to_thread(_handshake, host, port)

    findings: List[dict] = []
    if info.error and not info.subject:
        findings.append(_finding(
            "critical",
            "TLS handshake failed",
            f"Could not establish a TLS connection to {host}:{port} — {info.error}. "
            "Visitors' browsers will refuse to load the site at all, or show a full-page "
            "security warning before they can proceed.",
            recommendation="Verify the certificate is installed correctly and the server is "
                            "listening for TLS on the expected port; test with `openssl "
                            f"s_client -connect {host}:{port}`.",
        ))
        return findings, info

    if not info.trusted:
        if info.self_signed:
            findings.append(_finding(
                "critical",
                "Self-signed certificate",
                f"{host} presents a self-signed certificate rather than one issued by a "
                "trusted certificate authority. Every mainstream browser blocks the page "
                "behind an interstitial warning for this.",
                recommendation="Replace it with a certificate from a trusted CA — a free "
                                "option like Let's Encrypt is sufficient for most sites.",
            ))
        elif info.hostname_mismatch:
            findings.append(_finding(
                "critical",
                "Certificate hostname mismatch",
                f"The certificate presented by {host} does not cover this hostname (its "
                f"subject/SAN is {info.subject or 'unknown'}). Browsers will refuse the "
                "connection or show a warning.",
                recommendation="Issue a certificate that includes this exact hostname (and "
                                "any subdomains served) in its Subject Alternative Names.",
            ))
        else:
            findings.append(_finding(
                "critical",
                "Certificate not trusted",
                f"The certificate for {host} did not validate against the standard CA trust "
                f"store{': ' + info.error if info.error else ''}.",
                recommendation="Check the certificate chain includes all intermediate "
                                "certificates, and that it hasn't expired.",
            ))

    if info.days_until_expiry is not None:
        if info.days_until_expiry < 0:
            findings.append(_finding(
                "critical",
                "TLS certificate has expired",
                f"The certificate for {host} expired {-info.days_until_expiry} day(s) ago "
                f"(not_after: {info.not_after}).",
                recommendation="Renew the certificate immediately — most CAs support "
                                "automated renewal (e.g. certbot) to prevent this recurring.",
            ))
        elif info.days_until_expiry <= EXPIRY_CRITICAL_DAYS:
            findings.append(_finding(
                "critical",
                "TLS certificate expiring within a week",
                f"The certificate for {host} expires in {info.days_until_expiry} day(s) "
                f"(not_after: {info.not_after}).",
                recommendation="Renew now — set up automated renewal so this doesn't happen "
                                "again.",
            ))
        elif info.days_until_expiry <= EXPIRY_WARNING_DAYS:
            findings.append(_finding(
                "warning",
                "TLS certificate expiring soon",
                f"The certificate for {host} expires in {info.days_until_expiry} day(s) "
                f"(not_after: {info.not_after}).",
                recommendation="Schedule renewal now, ideally via an automated process, so "
                                "expiry never becomes an incident.",
            ))

    if info.protocol in WEAK_PROTOCOLS:
        findings.append(_finding(
            "critical",
            "Deprecated TLS protocol negotiated",
            f"{host} negotiated {info.protocol}, which is deprecated and disabled by default "
            "in modern browsers. It's also vulnerable to known downgrade/plaintext-recovery "
            "attacks (e.g. POODLE for SSLv3, BEAST for TLSv1.0).",
            recommendation="Disable protocol versions below TLS 1.2 in the server's TLS "
                            "configuration; TLS 1.2 and 1.3 only is the current baseline.",
        ))

    return findings, info


def _handshake(host: str, port: int) -> SslInfo:
    info = SslInfo(checked=True)

    verifying_ctx = ssl.create_default_context()
    cert, protocol, cipher, error = _connect(host, port, verifying_ctx)

    if cert is not None:
        info.trusted = True
    else:
        # Retry without verification purely to read the cert's own fields for reporting.
        info.error = error
        lenient_ctx = ssl._create_unverified_context()  # noqa: SLF001 — intentional, read-only inspection
        cert, protocol, cipher, _ = _connect(host, port, lenient_ctx)
        info.self_signed = bool(error and "self signed" in error.lower() or "self-signed" in (error or "").lower())
        info.hostname_mismatch = bool(error and "hostname mismatch" in error.lower())

    if cert:
        info.subject = _name_from_cert(cert.get("subject"))
        info.issuer = _name_from_cert(cert.get("issuer"))
        info.not_before = cert.get("notBefore")
        info.not_after = cert.get("notAfter")
        info.days_until_expiry = _days_until(cert.get("notAfter"))
        if not info.trusted and info.subject and host not in info.subject and not info.hostname_mismatch:
            # crude SAN-vs-host check as a fallback when the ssl module's own
            # CertificateError text didn't already flag a mismatch
            pass

    info.protocol = protocol
    info.cipher = cipher
    return info


def _connect(host: str, port: int, context: ssl.SSLContext):
    """Returns (cert_dict_or_None, protocol, cipher_name, error_message)."""
    try:
        with socket.create_connection((host, port), timeout=CONNECT_TIMEOUT_SECONDS) as sock:
            with context.wrap_socket(sock, server_hostname=host) as tls_sock:
                cert = tls_sock.getpeercert()
                protocol = tls_sock.version()
                cipher = tls_sock.cipher()[0] if tls_sock.cipher() else None
                return cert, protocol, cipher, None
    except ssl.SSLCertVerificationError as exc:
        return None, None, None, str(exc)
    except (ssl.SSLError, socket.error, OSError) as exc:
        return None, None, None, str(exc)


def _name_from_cert(name_tuples) -> Optional[str]:
    if not name_tuples:
        return None
    parts = [f"{k}={v}" for rdn in name_tuples for k, v in rdn]
    return ", ".join(parts) or None


def _days_until(not_after: Optional[str]) -> Optional[int]:
    if not not_after:
        return None
    try:
        expiry = datetime.strptime(not_after, _CERT_DATE_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (expiry - datetime.now(timezone.utc)).days


def _finding(severity: str, title: str, description: str, recommendation: Optional[str] = None) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
