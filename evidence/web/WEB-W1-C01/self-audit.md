# WEB-W1-C01 self-audit

- Strangler only. rxycode_core.Session and reuse_or_create_session are the objects from RxyCode.RxyCode1_1_0.core.session. No second AgentV2.
- audit_class_identity compares id(), so two classes that compare equal through a metaclass are BLOCKED. The unit test builds that pair.
- pyproject.toml registers rxycode_core at packages/rxycode-core/src/rxycode_core. Version stays 1.4.3.
- core/session.py was not edited by this card.
- The module test archives HEAD, builds that tree, and installs the wheel. PYTHONPATH and PYTHONHOME are removed. The probe cwd is an empty temp directory. It asserts rxycode_core, legacy session, and appserver.server load from the venv and not from the checkout. system site packages stay on so a --no-deps wheel can import third-party libraries. The origin check is what rejects a checkout or editable install.
- tests/system/test_installed_package.py adds one smoke function. Existing assertions were not edited. system-smoke.txt records 1 passed in 9.15s.
- Cache regression after the fix commit: 30 passed, 2 skipped. The skips are the pre-existing "no tools registered in global test registry" lines. This card did not change cache code.
- Protocol/TS codegen: no protocol field changed. Not run. Not a protocol pass.
- Desktop UI E2E: the card assigns that to a later phase exit. Not run. Not a pass.
- git diff --check on the whole dirty parent tree reports pre-existing trailing whitespace outside this card.
