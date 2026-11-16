"""Password rules and Argon2id hashing (SPEC.md "Marketing and accounts", Passwords).

`password_problem` is the one place the rules live: every flow that sets a password (invite,
account page, reset, `make dev-user`) calls it before hashing. Hashing uses argon2-cffi's
defaults (Argon2id); `verify_password` also says when a stored hash should be upgraded.
"""

from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_LENGTH = 12
COMMON_PASSWORDS = Path(__file__).with_name("common_passwords.txt")  # see .NOTICE beside it

_hasher = PasswordHasher()


@lru_cache(maxsize=1)
def _common_passwords() -> frozenset[str]:
    lines = COMMON_PASSWORDS.read_text(encoding="utf-8").splitlines()
    return frozenset(line.strip().casefold() for line in lines if line.strip())


def password_problem(password: str) -> str | None:
    """Why `password` can't be used, as a message for the person choosing it, or None if it's
    fine. At least 12 characters (counted as characters, not bytes), no composition rules, and
    not on the bundled list of the 10,000 most common passwords (case-insensitive)."""
    if len(password) < MIN_LENGTH:
        return f"Use at least {MIN_LENGTH} characters."
    if password.casefold() in _common_passwords():
        return "That password is too common. Choose another."
    return None


def hash_password(password: str) -> str:
    return _hasher.hash(password)


class Verified(NamedTuple):
    ok: bool
    # Set when `ok` and the stored hash uses outdated parameters: store this one instead.
    new_hash: str | None


def verify_password(stored_hash: str, password: str) -> Verified:
    """Check `password` against `stored_hash`. A malformed hash fails closed."""
    try:
        _hasher.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return Verified(False, None)
    if _hasher.check_needs_rehash(stored_hash):
        return Verified(True, _hasher.hash(password))
    return Verified(True, None)


# Built at import, not on first use: otherwise the first unknown-email sign-in would cost two
# Argon2 runs and stand out.
_DUMMY_HASH = _hasher.hash("timing-equaliser, never a real password")


def burn_verify(password: str) -> None:
    """Do the same Argon2 work as a real verify, for a login with no usable hash (unknown
    email, or a passkey-only user), so response time doesn't reveal which emails exist."""
    verify_password(_DUMMY_HASH, password)
