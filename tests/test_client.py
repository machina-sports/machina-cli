from machina_cli.client import MachinaClient
from machina_cli.project_client import ProjectClient
from unittest.mock import patch

@patch("machina_cli.client.resolve_auth_token")
def test_machina_client_headers_no_content_type(mock_resolve):
    mock_resolve.return_value = ("X-Api-Token", "fake-token")
    client = MachinaClient(api_url="http://fake")
    headers = client._headers()
    assert "Content-Type" not in headers, "Content-Type should not be hardcoded in headers"
    assert headers["X-Api-Token"] == "fake-token"

@patch("machina_cli.project_client.get_config")
@patch("machina_cli.project_client._get_project_session")
@patch("machina_cli.project_client.resolve_auth_token")
def test_project_client_headers_no_content_type(mock_resolve, mock_session, mock_config):
    mock_config.return_value = "proj-123"
    mock_session.return_value = {
        "api_url": "http://fake-project",
        "token": "fake-proj-token",
        "direct_api_key": False
    }
    mock_resolve.return_value = ("X-Session-Token", "fake-session-token")
    
    client = ProjectClient(project_id="proj-123")
    headers = client._headers()
    assert "Content-Type" not in headers, "Content-Type should not be hardcoded in headers"
    assert headers["X-Project-Token"] == "fake-proj-token"
    assert headers["X-Session-Token"] == "fake-session-token"
