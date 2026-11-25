"""Credential fetch client; response is memory-only and must never be logged."""
from api_client import APIClient

def fetch_credentials(api,account_id,agent_id,secret):
    body=APIClient(api,secret).credentials(agent_id,int(account_id))
    required=("login","password","server","ea_token")
    if any(not body.get(key) for key in required):
        raise ValueError("incomplete_account_credentials")
    return body
