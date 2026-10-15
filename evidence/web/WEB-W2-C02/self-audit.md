# WEB-W2-C02 self-audit

- create_app builds a new FastAPI app. Its route table does not include legacy /chat.
- serve(mode="local", host="0.0.0.0") calls api_server.reject_as_public_web_gateway and raises. The existing desktop remote opt-in in run_api_server is unchanged.
- Local login writes a User, Organization, and owner Membership. GET /api/v1/me reads those rows back.
- A second login drops the previous session cookie. The old cookie gets 401 UNAUTHORIZED.
- GitHub start stores a PKCE verifier and puts the S256 challenge on the authorize URL. The callback posts that verifier and the client secret to GitHub through the injected transport, then does not return or store the access token.
- Cloud login Set-Cookie is read from the ASGI response and includes HttpOnly, SameSite=lax, and Secure.
- POST /api/v1/projects without the CSRF header, or with a foreign Origin, returns 403 and leaves the project count at 0. A repo_config api_key is rejected and not stored.
- A second user receives 404 for the first user's project and session, and the names are not in the body. The body's tenant_id is ignored.
- openapi.json is the app.openapi() document. The Starlette httpx deprecation warning comes from the installed TestClient, not from this card.
- Nested whitelist is 8802d6b. The parent commit does not track the embedded plan repository.
- Codex first returned VERDICT: PROBLEMS. 29d6625f answers it: local login requires mode=local and the server secret, and it reuses the one local user; OAuth state is bound to the rxy_oauth cookie; GET /api/v1/projects/{id}/sessions lists only that tenant.
