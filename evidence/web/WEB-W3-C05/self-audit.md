# WEB-W3-C05 self-audit

- RED: TerminalPane.tsx was missing. See red.txt.
- POST /api/v1/terminals starts python -i in a real ConPTY via pywinpty. The caller cannot aim it at another host or tenant.
- The websocket sends input and resize to that PTY. print output matches the interactive process, and exit() reports exit code 0.
- A foreign session cookie is rejected before the socket is accepted. The existing process stays the only live pid.
- Closing the socket does not kill the PTY. Reloading /terminal/:id shows the same scrollback in xterm.
- Local mode does not sandbox. Cloud mode assigns the OS sandbox job and refuses to start if that assignment fails.
- Not claimed as 已落实. WEB-W1 CW03 and CW04 stay open. Device connect is not implemented.
