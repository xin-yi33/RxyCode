# WEB-W4-C02 self-audit

- RED: rxycode_runner.desktop was missing. 3 failed in 0.15s. See red.txt.
- A logical point on the second monitor is converted with that monitor's DPI before send.
- Lock screen, Wayland, and a task without click capability return CAPABILITY_UNAVAILABLE and do not send.
- macOS and Linux stay unavailable in describe_platform.
- capture_screen reads pixels from a real visible window. open_app returns a real Notepad hwnd and does not attach Chrome.
- Not claimed as 已落实. E2E-FULL-02 stays BLOCKED.
