# WEB-W1-C01 self-audit

- Strangler only. rxycode_core.Session and reuse_or_create_session are the objects from RxyCode.RxyCode1_1_0.core.session. No second AgentV2.
- pyproject.toml registers rxycode_core at packages/rxycode-core/src/rxycode_core. Version stays 1.4.3.
- core/session.py was not edited by this card.
- Unit tests call the installed import path and audit_class_identity. Module test builds a wheel with pip, installs it into a temp venv, imports appserver.server, and checks Session identity, then runs rxycode.exe --help.
- tests/system/test_installed_package.py adds one smoke function. Existing assertions in that file were not edited.
- Cache regression: 30 passed, 2 skipped. The skips are the pre-existing "no tools registered in global test registry" in test_stable_prefix.py. This card did not touch cache code.
- Protocol/TS codegen: no protocol field changed. Not run. Recorded as not applicable for this card, not as a protocol pass.
- Desktop UI E2E: the card assigns that to a later phase exit. Not run. Not a pass.
- git diff --check on the whole dirty parent tree reports pre-existing trailing whitespace outside this card. New LF files are packages/rxycode-core and tests/web/w1. pyproject.toml and test_installed_package.py were already CRLF; only the card hunks were added.
