# WEB-W3-C01 self-audit

- RED, before apps/web existed: three tests failed with `apps/web/package.json is missing`. See red.txt.
- `bun run build` typechecks and produces dist with a sourcemap. Playwright opens that build at /login. The test server answers `/api/v1/me` with 503. The page shows an alert and a 重试 button, the button can take focus, and clicking it requests `/api/v1/me` again.
- The bundle sourcemap includes `sessionVisualState.ts` from the desktop renderer. The JS bundle does not contain electron, contextBridge, ipcRenderer, child_process, node:fs, preload.js, or localStorage.
- React Router writes view-transition state to sessionStorage. The scan does not treat that as a model key. `localStorage` is absent.
- Pages render loading, error, empty, and disconnected. The locked contract drives the error and retry path.
- E2E-WEB-01, a new user reaching the project page through the live API, is not claimed.
- Not claimed as 已落实. WEB-W1 CW03 and CW04 stay open. Device connect is not implemented.
