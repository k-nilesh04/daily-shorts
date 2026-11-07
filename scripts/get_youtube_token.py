"""Run ONCE on your own computer to get a YouTube refresh token.

  pip install google-auth-oauthlib
  python scripts/get_youtube_token.py path/to/client_secret.json

Log in with the Google account that owns the YouTube channel.
Copy the printed values into GitHub -> Settings -> Secrets and variables -> Actions.
"""
import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

if len(sys.argv) != 2:
    sys.exit(__doc__)

flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

info = json.load(open(sys.argv[1]))
client = info.get("installed") or info.get("web")
print("\nAdd these as GitHub secrets:\n")
print("YT_CLIENT_ID     =", client["client_id"])
print("YT_CLIENT_SECRET =", client["client_secret"])
print("YT_REFRESH_TOKEN =", creds.refresh_token)
