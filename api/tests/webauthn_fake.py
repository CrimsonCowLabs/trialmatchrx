"""A software authenticator for the passkey tests: it answers the API's WebAuthn options with
the same JSON `@simplewebauthn/browser` posts (`startRegistration` / `startAuthentication`),
so no real authenticator or browser is involved. Each one signs with a fixed synthetic P-256
key from tests/fixtures/webauthn; the challenge is random per test, so the responses are built
here rather than stored."""

import base64
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cbor2
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

FIXTURES = Path(__file__).parent / "fixtures" / "webauthn"

UP, UV, AT = 0x01, 0x04, 0x40  # authenticator-data flags: user present, verified, attested


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _key(name: str) -> ec.EllipticCurvePrivateKey:
    key = serialization.load_pem_private_key((FIXTURES / f"{name}.pem").read_bytes(), None)
    assert isinstance(key, ec.EllipticCurvePrivateKey)
    return key


@dataclass
class FakeAuthenticator:
    """One passkey on one device. `origin` and `rp_id` are what the browser would report;
    tests change them to play a phishing page."""

    key_name: str = "authenticator_a"
    credential_id: bytes = b"fake-credential-a"
    origin: str = "http://localhost:3045"
    rp_id: str = "localhost"
    sign_count: int = 0
    user_handle: str | None = field(default=None)  # set by `register`, from the options

    @property
    def id(self) -> str:
        return b64url(self.credential_id)

    def _client_data(self, kind: str, options: dict[str, Any]) -> bytes:
        return json.dumps(
            {
                "type": kind,
                "challenge": options["challenge"],
                "origin": self.origin,
                "crossOrigin": False,
            }
        ).encode()

    def _rp_hash(self) -> bytes:
        return hashlib.sha256(self.rp_id.encode()).digest()

    def register(self, options: dict[str, Any], *, verified: bool = True) -> dict[str, Any]:
        """The response to `navigator.credentials.create()` for these creation options."""
        self.user_handle = options["user"]["id"]
        numbers = _key(self.key_name).public_key().public_numbers()
        cose_key = cbor2.dumps(
            {
                1: 2,  # kty: EC2
                3: -7,  # alg: ES256
                -1: 1,  # crv: P-256
                -2: numbers.x.to_bytes(32, "big"),
                -3: numbers.y.to_bytes(32, "big"),
            }
        )
        flags = UP | AT | (UV if verified else 0)
        auth_data = (
            self._rp_hash()
            + bytes([flags])
            + self.sign_count.to_bytes(4, "big")
            + bytes(16)  # aaguid
            + len(self.credential_id).to_bytes(2, "big")
            + self.credential_id
            + cose_key
        )
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {
            "id": self.id,
            "rawId": self.id,
            "type": "public-key",
            "response": {
                "clientDataJSON": b64url(self._client_data("webauthn.create", options)),
                "attestationObject": b64url(attestation),
                "transports": ["internal", "hybrid"],
            },
            "clientExtensionResults": {},
            "authenticatorAttachment": "platform",
        }

    def sign_in(self, options: dict[str, Any], *, verified: bool = True) -> dict[str, Any]:
        """The response to `navigator.credentials.get()` for these request options."""
        self.sign_count += 1
        flags = UP | (UV if verified else 0)
        auth_data = self._rp_hash() + bytes([flags]) + self.sign_count.to_bytes(4, "big")
        client_data = self._client_data("webauthn.get", options)
        signature = _key(self.key_name).sign(
            auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
        )
        return {
            "id": self.id,
            "rawId": self.id,
            "type": "public-key",
            "response": {
                "clientDataJSON": b64url(client_data),
                "authenticatorData": b64url(auth_data),
                "signature": b64url(signature),
                "userHandle": self.user_handle,
            },
            "clientExtensionResults": {},
            "authenticatorAttachment": "platform",
        }
