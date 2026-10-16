# WEB-W5-C03 self-audit

- RED: the workspaces package did not exist. 3 failed in 0.31s. See red.txt.
- Unit after the fix: 2 passed in 21.80s. Module: 1 passed in 7.62s. No skip.
- Audit w5c03-audit-1.json returned PROBLEMS: a caller bundle was not the requested GitHub repo, and TTL only stopped the container. The fix clones the allowlisted URL inside the git sandbox and `rm`s the tenant container when the ttl fires.
- `git clone` of https://github.com/octocat/Hello-World and `git checkout --detach 7fd1a60b01f91b314f59955a4e4d4e80d8edf11d` run in an alpine/git container as uid 65534, with no host mount and no Docker socket. The API host does not run git. The tree is tar-streamed into the tenant python sandbox, which stays network none and reads README.

- The revision file written by `git rev-parse` inside the git container is 7fd1a60b01f91b314f59955a4e4d4e80d8edf11d. Status was clean before the marker files. HEAD is detached, so this path does not commit onto a branch.
- A second import of the same revision reproduces README and the same snapshot sha256. Cleaning the first sandbox leaves the second runnable.
- A URL with an embedded token is stored and logged only in redacted form. The snapshot bytes, the log, and `docker inspect` do not contain the token. Tenant B cannot read the snapshot or clean the workspace. `file://`, metadata, and non-GitHub URLs are refused before a container is created.
- An 8 second ttl removes the tenant container. runsc is not installed. No independent UI E2E. core/ was not touched. Not claimed as 已落实.
- Nested ruling 332faaf63c6e8b2425b773a05cffcd981e53dd03 names the workspaces package marker.
- gpt-6-luna max re-audit has not run yet. Session stays 01a140a7-2cc1-7f61-bdab-2af627f08e80.
