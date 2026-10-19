# WEB-W7-C06 self-audit / manual review

Audited commit: `<filled after the audited fix commit>`
Final verdict: `<filled by the Codex audit>` (session `01a140a7-2cc1-7f61-bdab-2af627f08e80`, `gpt-6.1-sol` high).

## Audit history

| round | verdict | findings fixed |
|---|---|---|
| r1 | (pending — submit after commit) | — |

## Verified by hand

- `git check-ignore` on both new docs returns "not ignored" (rc=1) after the two negation rules.
- Deleting the README Web section fails `test_w7_c06_contract`; renaming an evidence dir fails it; an uncited metric in the case study fails `test_w7_c06_negative` (RED observed: README had no Web section at all).
- Module test observed live: every unauthenticated verb refused (401/403) on a real `create_app` — not a mocked ASGI stub.
- README matrix claims were each checked against `ls`/`git` existence before writing the row — no row references a missing artifact.

## Known limitations (accepted, documented)

- The anonymous-visitor cloud-run leg does not exist as a product feature; test asserts the refusal surface. Browser leg BLOCKED (no Playwright).
- README matrix is English-consistent with the rest of the file; the product docs follow the repo's Chinese user-guide convention.
- Case study demo-video cell is a script only — recording is BLOCKED per frozen rule (no fake scenes).
