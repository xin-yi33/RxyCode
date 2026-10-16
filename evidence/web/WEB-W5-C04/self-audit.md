# WEB-W5-C04 self-audit

- RED: browser.py and the previews package were missing. 3 failed in 0.19s. See red.txt.
- Unit: 2 passed in 6.19s. Module: 1 passed in 2.56s. No skip.
- The contract starts a real HTTP server inside the tenant sandbox, which stays network none. expose_port records the owner, tenant, sandbox, and port. fetch reads only http://127.0.0.1 on that port from inside the sandbox and returns the page body. Bun renders BrowserPreview with that body; the nonce is visible. The unavailable render says target unavailable and hides the page.
- A metadata URL, another tenant, and an unregistered port are refused before a proxy read. After the attacks, the owner still receives the original page. A 1 second grant then expires.
- Closing the dev server makes the next fetch raise TargetUnavailable. The message contains unavailable and the sandbox id.
- open_profile creates an empty directory in the sandbox and does not copy OAUTH_TOKEN from the host environment. close_profile removes it.
- The response CSP is default-src 'none'. The iframe sandbox attribute is empty.
- E2E-CLOUD-02, a separate React dev server harness, was not run. runsc was not used. core/ was not touched. Not claimed as 已落实.
- Nested ruling 569538a010def5500e455596e9ba649262738519 names the previews package marker.
- gpt-6-luna max audit has not run yet. Session stays 01a140a7-2cc1-7f61-bdab-2af627f08e80.
