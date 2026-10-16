# WEB-W4-C01 self-audit

- RED: native_backend was missing. 3 failed in 0.16s. See red.txt.
- Local full starts the requested argv with subprocess and does not call wrap_command.
- The child pid is in the same Windows session as this process.
- Injecting a sandbox object raises SANDBOX_FORBIDDEN.
- permission=ask asks the real approval broker and does not start the process when the broker rejects.
- permission=full runs the same command without another ask.
- Not claimed as 已落实. E2E-FULL-01 stays BLOCKED.
