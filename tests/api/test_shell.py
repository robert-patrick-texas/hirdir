"""What wraps every request: headers, the URL prefix, and never a cookie."""

from fastapi.testclient import TestClient

from hirdir import app as app_module
from hirdir.app import create_app
from hirdir.config import Config

API = "/api/v1"


def test_no_response_sets_a_cookie_and_every_one_is_hardened(
    client: TestClient, admin: dict, viewer: dict
) -> None:
    document = client.get(f"{API}/openapi.json", headers=admin).json()["paths"]
    paths = sorted(path for path, item in document.items() if "get" in item and "{" not in path)
    assert f"{API}/users" in paths
    for path in [*paths, "/", "/some/page", f"{API}/no-such-route"]:
        for headers in ({}, admin, viewer):
            response = client.get(path, headers=headers)
            assert "set-cookie" not in response.headers, path
            assert response.headers["x-content-type-options"] == "nosniff", path
            assert "frame-ancestors 'none'" in response.headers["content-security-policy"], path
            assert response.headers["x-request-id"], path
    assert client.get(f"{API}/auth/me", headers=admin).headers["cache-control"] == "no-store"


def test_unknown_api_route_is_a_problem_not_a_page(client: TestClient) -> None:
    response = client.get(f"{API}/no-such-route")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"


def test_prefix_from_a_trusted_proxy_is_honoured(client: TestClient, admin: dict) -> None:
    forwarded = {"X-Forwarded-Prefix": "/inventory", "X-Forwarded-For": "198.51.100.7"}
    assert client.get(f"{API}/health/live", headers=forwarded).status_code == 200
    document = client.get(f"{API}/openapi.json", headers={**admin, **forwarded}).json()
    assert document["servers"] == [{"url": "/inventory"}]
    assert f"{API}/users" in document["paths"]
    # A proxy that passes the prefix through, instead of stripping it, works as well.
    assert client.get(f"/inventory{API}/health/live", headers=forwarded).status_code == 200


def test_prefix_from_anyone_else_is_ignored(config: Config) -> None:
    untrusted = Config(state_dir=config.state_dir, trusted_proxies=("192.0.2.99",))
    with TestClient(create_app(untrusted)) as other:
        response = other.get("/x/api/v1/health/live", headers={"X-Forwarded-Prefix": "/x"})
        # The prefix is not stripped, so this is not the health route: it falls through
        # to the page, as any path outside the API does.
        assert "status" not in response.text


def test_bad_prefix_is_ignored(client: TestClient) -> None:
    for prefix in ('/a"><script>', "no-slash", "/a/../b"):
        response = client.get(f"{API}/health/live", headers={"X-Forwarded-Prefix": prefix})
        assert response.status_code == 200


def test_web_ui_gets_the_prefix_in_its_base_tag(config: Config, tmp_path, monkeypatch) -> None:
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text('<html><head><base href="/" /></head></html>')
    (static / "assets" / "app.js").write_text("console.log(1)")
    monkeypatch.setattr(app_module, "STATIC", static)
    with TestClient(create_app(config)) as ui:
        assert '<base href="/" />' in ui.get("/").text
        deep = ui.get("/admin/users", headers={"X-Forwarded-Prefix": "/hirdir"})
        assert '<base href="/hirdir/" />' in deep.text
        assert deep.headers["cache-control"] == "no-store"
        assert ui.get("/assets/app.js").text == "console.log(1)"
        assert (
            ui.get("/assets/app.js", headers={"X-Forwarded-Prefix": "/hirdir"}).status_code == 200
        )
        assert ui.get("/../config.py").status_code in (200, 404)
        assert "console" not in ui.get("/%2e%2e/app.py").text


def test_without_a_built_ui_the_root_says_so(config: Config, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "STATIC", tmp_path / "no-ui-here")
    with TestClient(create_app(config)) as bare:
        assert "web UI has not been built" in bare.get("/").text


def test_built_files_are_kept_by_the_browser_and_pages_are_not(
    config: Config, tmp_path, monkeypatch
) -> None:
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text('<html><head><base href="/" /></head></html>')
    (static / "assets" / "app-abc123.js").write_text("console.log(1);" * 500)
    monkeypatch.setattr(app_module, "STATIC", static)
    with TestClient(create_app(config)) as ui:
        for headers in ({}, {"X-Forwarded-Prefix": "/hirdir"}):
            built = ui.get("/assets/app-abc123.js", headers=headers)
            assert built.headers["cache-control"] == "public, max-age=31536000, immutable"
            assert built.headers["content-encoding"] == "gzip"
            assert built.text.startswith("console.log(1);")
        assert ui.get("/items", headers={}).headers["cache-control"] == "no-store"
        missing = ui.get("/assets/no-such-file.js")
        assert "immutable" not in missing.headers.get("cache-control", "")


def test_a_large_answer_is_compressed_and_a_small_one_is_left_alone(
    client: TestClient, admin: dict
) -> None:
    large = client.get(f"{API}/openapi.json", headers=admin)
    assert large.headers["content-encoding"] == "gzip"
    assert large.headers["cache-control"] == "no-store"
    assert "paths" in large.json()
    assert "content-encoding" not in client.get(f"{API}/health/live").headers
    plain = client.get(f"{API}/openapi.json", headers={**admin, "Accept-Encoding": "identity"})
    assert "content-encoding" not in plain.headers
