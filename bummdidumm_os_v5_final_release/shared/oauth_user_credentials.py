import os
import google.auth
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

def get_user_credentials():
    """
    Constructs Google OAuth User Credentials from environment variables.
    Requires: GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, GOOGLE_OAUTH_REFRESH_TOKEN.
    Falls back to Application Default Credentials if not fully provided.

    Fail-fast: if OAuth env vars are present, an explicit token refresh is attempted
    immediately so that revoked/expired credentials surface here with a clear error
    rather than buried inside the first API call (Drive or Sheets).
    """
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
    refresh_token = os.environ.get("GOOGLE_OAUTH_REFRESH_TOKEN")

    if client_id and client_secret and refresh_token:
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret
        )
        try:
            creds.refresh(Request())
        except Exception as e:
            raise ValueError(
                f"OAuth token refresh failed — verify GOOGLE_OAUTH_CLIENT_ID, "
                f"GOOGLE_OAUTH_CLIENT_SECRET, and GOOGLE_OAUTH_REFRESH_TOKEN: {e}"
            ) from e
        return creds
    else:
        creds, _ = google.auth.default()
        return creds
