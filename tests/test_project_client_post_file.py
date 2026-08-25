"""The multipart upload must never carry the JSON Content-Type.

`_headers()` hardcodes `Content-Type: application/json` for the JSON
endpoints. Passed alongside `files=`, that header overrides the
`multipart/form-data; boundary=...` httpx generates, Flask never parses
`request.files`, and every `machina template push` died as "No file
uploaded" — against every pod, since the command shipped. This pins the
fix: auth headers travel, the content type is httpx's to set.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import httpx

from machina_cli.project_client import ProjectClient


def _client_with_fixed_session() -> ProjectClient:
    session = {"token": "jwt-token", "api_url": "https://pod.example.test"}
    with (
        patch("machina_cli.project_client._get_project_session", return_value=session),
        patch("machina_cli.project_client.resolve_auth_token", return_value=(None, None)),
    ):
        return ProjectClient("project-1")


def test_post_file_sends_multipart_without_json_content_type(tmp_path: Path):
    upload = tmp_path / "template.zip"
    upload.write_bytes(b"PK\x03\x04fake-zip")
    captured: dict = {}

    def fake_send(request: httpx.Request) -> httpx.Response:
        captured["content_type"] = request.headers.get("content-type", "")
        captured["auth"] = {
            name: request.headers.get(name)
            for name in ("x-project-token", "x-api-token", "x-session-token")
            if request.headers.get(name)
        }
        captured["body"] = request.read()
        return httpx.Response(200, json={"status": "success"})

    client = _client_with_fixed_session()
    transport = httpx.MockTransport(fake_send)
    real_init = httpx.Client.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        real_init(self, *args, **kwargs)

    with (
        patch.object(httpx.Client, "__init__", patched_init),
        patch("machina_cli.project_client.resolve_auth_token", return_value=(None, None)),
    ):
        result = client.post_file("templates/upload", str(upload))

    assert result == {"status": "success"}
    # The whole bug: this used to be application/json, which erased the
    # multipart boundary and left request.files empty on the server.
    assert captured["content_type"].startswith("multipart/form-data; boundary=")
    # The auth headers must survive the Content-Type removal.
    assert captured["auth"], "no auth header reached the pod"
    # And the file must actually be inside the multipart body.
    assert b'name="file"' in captured["body"]
    assert b"fake-zip" in captured["body"]
