# Contributing to RxyCode

Thanks for your interest in contributing! RxyCode follows a development-plan-first workflow, so please review the guidelines below before opening a PR.

## How to contribute

- **Ask a usage question** — [Discussions Q&A](https://github.com/xin-yi33/RxyCode/discussions/new?category=q-a).
- **Share an idea** — [Discussions Ideas](https://github.com/xin-yi33/RxyCode/discussions/new?category=ideas). Do not open a tracking issue until the design is specific.
- **Report a reproducible bug** — [bug issue form](https://github.com/xin-yi33/RxyCode/issues/new?template=bug.yml).
- **Submit a pull request** — follow the checklist below.

The project forum is [GitHub Discussions](https://github.com/xin-yi33/RxyCode/discussions). To enable the same kind of forum on your own repository, see [docs/community.md](docs/community.md) ([中文](docs/community.zh-CN.md)). Conduct: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Development setup

```bash
git clone https://github.com/xin-yi33/RxyCode.git
cd RxyCode
python -m pip install -e .

# Frontend (OpenTUI, default)
cd frontend && npm install && npm run build
cd ../frontend/opentui-app && bun install
```

## Before opening a PR

1. **Lint**: `python -m ruff check .`
2. **Backend tests**: `python -m pytest tests -q --timeout=600`
3. **Frontend tests**: `cd frontend && npm test` · `cd frontend/opentui-app && bun test`
4. **Evals (if behavior changed)**: `python -m evals.cli run --backend agent --compare-baseline evals/baselines/latest-agent.json` — confirm no regression.

## Commit conventions

- Match the existing style, e.g. `feat(model): ...`, `fix(agent): ...`, `chore(release): ...`.
- One logical change per commit.
- **Never commit secrets or API keys** — `.env` is gitignored; keep it that way.
