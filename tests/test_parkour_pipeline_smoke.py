"""
Parkour-game end-to-end pipeline smoke test.

This proves the FIX for the user's complaint ("写一个跑酷小游戏一直报错，
写蜘蛛卡牌游戏却可以") at the level that matters:

  prompt "帮我用 Python 写一个跑酷小游戏"
      -> (1) routing now classifies it as COMPLEX (tool-capable), NOT simple
      -> (2) the agent's complex path would call the real write tool, then run
      -> this test drives the REAL `tools.write.write_file` to emit a runnable
         `game.py`, then executes it with the same interpreter the agent uses,
         asserting it writes + runs cleanly.

The actual code-generation is the LLM's job (needs a configured model); here
we supply a known-good runnable parkour game so the write+run half of the
pipeline is verified deterministically without an external model.
"""
import subprocess
import sys
import textwrap

from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
from RxyCode.RxyCode1_1_0.tools.write import write_file


# A small but genuinely runnable headless parkour game (pure stdlib, no display
# needed). It simulates a runner that auto-jumps over obstacles, collects coins,
# tracks health/score, and ends with a summary. Exit code 0 on success.
GAME_SRC = textwrap.dedent(
    """\
    import random
    import sys


    def main():
        player_x = 0
        y = 0
        vy = 0
        gravity = -1
        score = 0
        coins = 0
        health = 3
        ticks = 0
        max_ticks = 600
        obstacles = []
        next_obstacle = 20

        while ticks < max_ticks:
            ticks += 1
            if ticks == next_obstacle:
                obstacles.append({"x": 40, "cleared": False})
                next_obstacle = ticks + random.randint(15, 30)

            vy += gravity
            y += vy
            if y < 0:
                y = 0
                vy = 0

            # auto-jump when an obstacle is close and we're on the ground
            for o in obstacles:
                if not o["cleared"] and 1 <= o["x"] - player_x <= 5 and y == 0:
                    vy = 4

            for o in obstacles:
                o["x"] -= 1

            for o in obstacles:
                if not o["cleared"] and o["x"] == player_x and y < 2:
                    health -= 1
                    o["cleared"] = True
                    if health <= 0:
                        break

            if ticks % 25 == 0:
                coins += 1
            score += 1
            if health <= 0:
                break

        print("跑酷小游戏结束")
        print(f"得分={score} 金币={coins} 生命={health}")
        print("Game Over" if health <= 0 else "通关")
        sys.exit(0)


    if __name__ == "__main__":
        main()
    """
)


def test_parkour_prompt_routes_to_complex_pipeline():
    """The previously-broken path: must NOT be a simple (no-tool) query."""
    agent = object.__new__(AgentV2)  # _is_simple_query is self-contained
    assert agent._is_simple_query("帮我用 Python 写一个跑酷小游戏") is False


def test_parkour_write_and_run_pipeline(tmp_path):
    """Real write tool -> runnable game.py -> executes with exit 0."""
    target = tmp_path / "game.py"

    write_result = write_file(str(target), GAME_SRC)
    assert "[wrote" in write_result, write_result
    assert "syntax check: OK" in write_result, write_result
    assert target.exists(), "write tool did not create the file"

    proc = subprocess.run(
        [sys.executable, str(target)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "跑酷小游戏结束" in proc.stdout
    assert "得分=" in proc.stdout
    assert ("Game Over" in proc.stdout) or ("通关" in proc.stdout)
