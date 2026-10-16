# WEB-W5-C04 self-audit

- RED: browser.py and the previews package were missing. 3 failed in 0.19s. See red.txt.
- Audit w5c04-audit-1.json returned PROBLEMS: identity was a caller header, the iframe used srcDoc and an empty sandbox, and create_app did not mount the route. The fix uses the session cookie, forwards the asset path, allows scripts in the iframe, and mounts the router.
- Unit after the fix: 2 passed, 5 warnings in 6.57s. Module: 1 passed, 3 warnings in 2.85s. No skip.
- The contract starts Node inside a network-none sandbox. React's renderToStaticMarkup writes the page, and /app.js is a real script. The session cookie, not x-owner-id, is the identity. A request with only forged headers is 401. create_app mounts the preview router. BrowserPreview points the iframe src at that route with sandbox=allow-scripts and no srcDoc.
- A metadata URL, another tenant, and an unregistered port are refused before a proxy read. After the attacks, the owner still receives the original page. A 1 second grant then expires.
- Closing the React server makes the next preview GET return 503. The body contains unavailable and the sandbox id.
- open_profile creates an empty directory in the sandbox and does not copy OAUTH_TOKEN from the host environment. close_profile removes it.
- The response CSP allows framing by 'self' and same-origin scripts. The iframe sandbox is allow-scripts.
- E2E-CLOUD-02, a separate React dev server harness, was not run. runsc was not used. core/ was not touched. Not claimed as 已落实.
- Nested ruling 569538a010def5500e455596e9ba649262738519 names the previews package marker.
- gpt-6-luna max re-audit has not run yet. Session stays 01a140a7-2cc1-7f61-bdab-2af627f08e80.
