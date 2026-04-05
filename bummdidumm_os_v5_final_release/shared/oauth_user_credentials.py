import os
import google.auth
from google.oauth2.credentials import Credentials

def get_user_credentials():
    """
    Constructs Google OAuth User Credentials from environment variables.
    Requires: GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, GOOGLE_OAUTH_REFRESH_TOKEN.
    Falls back to Application Default Credentials if not fully provided.
    """
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
    refresh_token = os.environ.get("GOOGLE_OAUTH_REFRESH_TOKEN")

    if client_id and client_secret and refresh_token:
        # User OAuth is prioritized
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret
        )
        return creds
    else:
        # Fall back to ADC
        creds, _ = google.auth.default()
        return creds
