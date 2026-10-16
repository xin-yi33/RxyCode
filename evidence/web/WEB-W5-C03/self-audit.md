# WEB-W5-C03 self-audit

- RED: the workspaces package did not exist. 3 failed in 0.31s. See red.txt.
- Unit: 2 passed in 49.20s. Module: 1 passed in 27.12s. No skip.
- The sample is a real git repository. `git clone` and `git checkout --detach` run in an alpine/git container as uid 65534, network none, no host mount. The API host does not run git. The tree is streamed with tar into the tenant python sandbox, which runs `test_sample.py`.
- The tenant sandbox stays on the C02 network-none policy, so this run does not fetch GitHub. The objects travel as a git bundle of that sample. The stored URL is allowlisted `https://github.com/<owner>/<repo>`.
- The revision file written by `git rev-parse` inside the git container matches the fixture commit. Status was clean before the marker files. HEAD is detached, so this path does not commit onto a branch.
- A second import of the same revision reproduces `base.txt` and the same snapshot sha256. Cleaning the first sandbox leaves the second runnable.
- A URL with an embedded token is stored and logged only in redacted form. The snapshot bytes, the log, and `docker inspect` do not contain the token. Tenant B cannot read the snapshot or clean the workspace. `file://`, metadata, and non-GitHub URLs are refused before a container is created.
- An 8 second ttl stops the sandbox. runsc is not installed. No independent UI E2E. core/ was not touched. Not claimed as 已落实.
- Nested ruling 332faaf63c6e8b2425b773a05cffcd981e53dd03 names the workspaces package marker.
- gpt-6-luna max audit has not run yet. Session stays 01a140a7-2cc1-7f61-bdab-2af627f08e80.
