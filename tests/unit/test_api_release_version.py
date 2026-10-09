"""HTTP API product-version metadata contract."""

from RxyCode.RxyCode1_1_0 import __version__, api_server


def test_fastapi_and_openapi_use_product_version_single_source():
    """FastAPI metadata must not drift from the package product version."""
    assert api_server.app.version == __version__
    assert api_server.app.openapi()["info"]["version"] == __version__
