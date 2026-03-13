import hashlib
import hmac
import secrets


def generate_webhook_secret() -> str:
    return secrets.token_urlsafe(24)


def generate_webhook_path_token() -> str:
    return secrets.token_urlsafe(18)


def hash_webhook_secret(*, secret: str, pepper: str) -> str:
    return hmac.new(pepper.encode("utf-8"), secret.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_webhook_secret(*, candidate: str, hashed_secret: str, pepper: str) -> bool:
    candidate_hash = hash_webhook_secret(secret=candidate, pepper=pepper)
    return hmac.compare_digest(candidate_hash, hashed_secret)


def build_secret_hint(secret: str) -> str:
    suffix = secret[-6:] if len(secret) >= 6 else secret
    return f"...{suffix}"
