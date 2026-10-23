# WEB-W4-C01 self-audit

- RED: native_backend was missing. 3 failed in 0.16s. See red.txt.
- Local full starts the requested argv with subprocess and does not call wrap_command.
- The child pid is in the same Windows session as this process.
- Injecting a sandbox object raises SANDBOX_FORBIDDEN.
- permission=ask asks the real approval broker and does not start the process when the broker rejects.
- permission full_auto runs the real bash tool through LocalNativeBackend. confirm_all still asks the approval broker.
- The command string is the one the policy checked. workdir uses the session resolver. Timeout and kill stop the process tree. The wait does not block the event loop.
- gpt-6-luna max in session 01a140a7-2cc1-7f61-bdab-2af627f08e80 returned VERDICT: NO_REMAINING_PROBLEMS on 59a16694.
- Not claimed as 已落实. E2E-FULL-01 stays BLOCKED.
