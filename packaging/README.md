# Packaging (PhaseG-B13)

Runtime layout is produced per platform (`windows` / `macos` / `linux`).
Version bind is `protocol_version` + `appserver_version` + `schema_digest`.
Update stages next to `current/`; failure must not delete the previous tree.
Signing/notarization is an entry point only (`ReleaseService.sign_entry`).
