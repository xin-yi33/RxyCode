# WEB-W4-C03 self-audit

- RED: rxycode_runner.remote and rxycode_server.devices were missing. 3 failed in 0.25s. See red.txt.
- `rxycode connect` dials the cloud websocket. The Devices API then lists that device id, OS, and capability.
- The device token is not the browser session token, is stored as a hash, and is not written to the log message.
- WSS uses the default certificate context. Verification is not turned off. The locked run uses ws:// on 127.0.0.1.
- An expired pairing code, a wrong token, and protocol version 9.9.9 are refused. tool permission stays false.
- After the cloud socket drops, the runner reconnects with a new session id, the same scope, and a rotated token. The previous token is rejected.
- Outbound frames for one live socket go through one writer task.
- `rxycode web connect` remains the unimplemented W1 stub.
- Not claimed as 已落实. E2E-FULL-03 stays BLOCKED.
