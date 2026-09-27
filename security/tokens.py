"""
security/tokens.py
---------------------
Signed, time-limited session tokens (itsdangerous). The token carries
only the user id; every permission check happens server-side against
the database on each request (see app/auth.py: current_user()),
never trusted from the token payload alone.
"""

from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

from config import settings

_signer = TimestampSigner(settings.SESSION_SECRET)
_MAX_AGE = settings.SESSION_TTL_HOURS * 3600


def create_session_token(user_id: str) -> str:
    return _signer.sign(user_id.encode()).decode()


def verify_session_token(token: str):
    try:
        return _signer.unsign(token, max_age=_MAX_AGE).decode()
    except (BadSignature, SignatureExpired):
        return None
