"""app/auth/passwords.py: the password rules (SPEC.md "Marketing and accounts": 12+ characters,
no composition rules, not on the bundled 10k common list) and Argon2id hashing."""

from argon2 import PasswordHasher

from app.auth.passwords import (
    hash_password,
    password_problem,
    verify_password,
)


def test_a_long_uncommon_password_passes() -> None:
    assert password_problem("correct horse battery") is None


def test_eleven_characters_is_too_short_and_twelve_is_enough() -> None:
    assert password_problem("abcdefghij1") == "Use at least 12 characters."
    assert password_problem("qzvjwkplmxnb") is None


def test_no_composition_rules() -> None:
    assert password_problem("aaaaaaaaaaaaaaaaaaaaqq") is None  # all lowercase letters
    assert password_problem("392817465093") is None  # digits only


def test_a_common_password_is_rejected_whatever_its_case() -> None:
    # "unbelievable" and "masterbating" are on SecLists' 10k-most-common list.
    message = "That password is too common. Choose another."
    assert password_problem("unbelievable") == message
    assert password_problem("UnBelievable") == message


def test_length_counts_characters_not_bytes() -> None:
    assert password_problem("ééééééééééé") == "Use at least 12 characters."  # 11 chars, 22 bytes


def test_hash_is_argon2id_and_verifies_only_the_right_password() -> None:
    hashed = hash_password("correct horse battery")
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "correct horse battery").ok
    assert not verify_password(hashed, "correct horse batterz").ok


def test_verify_asks_for_a_rehash_when_the_parameters_are_outdated() -> None:
    weak = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash("correct horse battery")
    result = verify_password(weak, "correct horse battery")
    assert result.ok
    assert result.new_hash is not None
    assert verify_password(result.new_hash, "correct horse battery") == (True, None)


def test_a_current_hash_needs_no_rehash() -> None:
    result = verify_password(hash_password("correct horse battery"), "correct horse battery")
    assert result == (True, None)


def test_a_malformed_hash_fails_closed() -> None:
    assert not verify_password("not-a-hash", "correct horse battery").ok
