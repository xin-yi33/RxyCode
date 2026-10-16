# WEB-W4-C07 self-audit

- RED: release_status and support_matrix were missing. 3 failed in 0.31s. See red.txt.
- A new venv pip-installs packages/rxycode-runner. The rxycode-connect entry opens the outbound device socket and the gateway records the device session.
- Windows support_matrix reports desktop input, ConPTY, and local full as available. Darwin without Accessibility and Linux Wayland report desktop input unsupported.
- release_status marks only platforms that were actually run as supported. macos and linux stay unverified when only windows is listed.
- A runner install without the RxyCode tree still keeps the socket after hello. Tool binding is skipped when that import is missing. The full tree still publishes approvals.
- Not claimed as 已落实. macOS and Linux were not run on this host.
