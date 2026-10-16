# WEB-W3-C04 self-audit

- RED: FileTree.tsx was missing. See red.txt.
- The contract edits a real git checkout, opens the workspace page, and compares the visible hunk line with `git diff` from that checkout. The added line is `+two`.
- DiffReview mounts Monaco DiffEditor with the server's before and after text. Hunk accept posts path, hunk id, decision, and base_revision.
- A second write to the file makes that revision stale. The server returns 409 CONFLICT and does not change the raced bytes. The page says 刷新.
- A path that resolves outside the project root returns 403 WORKSPACE_FORBIDDEN. The secret file is not read and its text is absent from the response and the page.
- The tree lists one directory level and loads a child only after it is opened. GitPanel lists porcelain changes. The header shows the project's target id.
- The Monaco package is loaded by @monaco-editor/react. The editor workers are not copied into dist, so the earlier bundle scan still does not contain an Electron import.
- Not claimed as 已落实. WEB-W1 CW03 and CW04 stay open. Device connect is not implemented.
