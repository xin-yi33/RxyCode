# game/ — demo workload (not the agent)

## Purpose

A sample terminal game (`game.main.Game`) used as a demo project. It is a
first-party Python package on disk, but it is **not** part of the coding-agent
loop, protocol, or plugin store.

## Public surface

- `game.main.Game`
- `run_game.py`

## Dependencies

None (must stay disconnected from `core/` and `appserver/`).

## How to test

`python -c "import game.main; print(game.main.Game)"`
