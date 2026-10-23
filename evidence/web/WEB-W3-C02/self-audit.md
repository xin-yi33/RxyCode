# WEB-W3-C02 self-audit

- RED: the contract timed out clicking 本地. The onboarding controls were not in the build. See red.txt.
- The contract logs in on 127.0.0.1, imports repo-c02, and reads the project id from the POST /api/v1/projects response. After reload the same data-project-id is still visible. The id is the server row, not a value minted in the page.
- A key field posts repo_config.secret. The real API returns 400. The page shows 保存失败 and does not render a project id. A bad GitHub callback shows 授权失败 and no project id.
- Local mode text says a GitHub account is not required. Creating a session uses POST /projects/{id}/sessions. The page shows that response id and 等待运行. No request goes to github.com.
- The typed SDK sends the CSRF header and the typed local secret. The secret is not written into the bundle or localStorage.
- W3-C01 login error/retry still passes.
- E2E-WEB-01 browser screenshots are not claimed.
- Not claimed as 已落实. WEB-W1 CW03 and CW04 stay open. Device connect is not implemented.
