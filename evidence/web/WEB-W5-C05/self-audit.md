# WEB-W5-C05 self-audit

- RED: git_workflow was missing. 3 failed in 0.19s. See red.txt.
- Unit: 2 passed in 14.36s. Module: 1 passed in 7.27s. No skip.
- Later audit said the git process had no credential. clone and push now pass the token only as `http.extraHeader=Authorization: Bearer ...`. The smart HTTP server returns 401 without that header. The URL and the journal do not contain the token. A pull request on github.com is still BLOCKED.
- The sandbox is alpine/git as uid 65534. It clones and pushes through host.docker.internal. push of main raises before git push. main's sha stays the seed sha.
- GitHubClient speaks GET/POST /repos/{owner}/{repo}/pulls. The token is only the Bearer header. follow_redirects is false. The journal records the branch and sha and does not contain the token.
- confirm=False returns recovery_required and does not POST. A 403 from the API raises GitHubRefused with a fixed message. A second publish of the same head returns the existing number and does not POST again.
- PullRequestPanel renders the PR URL and the permission error. The rendered markup does not contain the token.
- E2E-CLOUD-03 against github.com is BLOCKED. This run had no dedicated test-repo token, so it did not open a pull request on github.com. The locked tests use a local server that implements the pulls endpoints. runsc was not used. core/ was not touched. Not claimed as 已落实.
- Nested ruling 323136dc228e811c9decec1edbd7640a13c9be93 names the integrations package marker.
- gpt-6-luna max audit has not run yet. Session stays 01a140a7-2cc1-7f61-bdab-2af627f08e80.
