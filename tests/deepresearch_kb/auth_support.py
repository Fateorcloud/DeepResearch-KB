from fastapi.testclient import TestClient

from deepresearch_kb.services.auth import AuthService, hash_password


TEST_PASSWORD = "stage2-test-password"
TEST_PASSWORD_HASH = hash_password(TEST_PASSWORD)
TEST_SESSION_SECRET = "stage2-test-session-secret-with-at-least-32-bytes"


def configured_auth(database, **kwargs):
    return AuthService(
        database, username="admin", password_hash=TEST_PASSWORD_HASH,
        session_secret=TEST_SESSION_SECRET, **kwargs)


def bearer_client(app, auth):
    issued = auth.issue_cli_token("test client")
    return TestClient(
        app, base_url="https://testserver",
        headers={"Authorization": f"Bearer {issued.token}"})
