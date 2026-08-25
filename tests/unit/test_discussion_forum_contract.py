from __future__ import annotations

from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DISCUSSION_DIR = PROJECT_ROOT / ".github" / "DISCUSSION_TEMPLATE"
ISSUE_DIR = PROJECT_ROOT / ".github" / "ISSUE_TEMPLATE"

# Default GitHub category slugs for this repository (polls have no form file).
FORM_SLUGS = (
    "announcements",
    "general",
    "ideas",
    "q-a",
    "show-and-tell",
)


def _load_yaml(path: Path) -> dict:
    loaded = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.SafeLoader)
    assert isinstance(loaded, dict), f"{path} must parse to a mapping"
    return loaded


def _non_markdown_fields(body: list) -> list:
    return [item for item in body if item.get("type") != "markdown"]


def test_discussion_category_forms_match_repo_slugs():
    files = sorted(p.name for p in DISCUSSION_DIR.glob("*.yml"))
    assert files == [f"{slug}.yml" for slug in FORM_SLUGS]


def test_discussion_category_forms_are_valid_github_forms():
    for slug in FORM_SLUGS:
        path = DISCUSSION_DIR / f"{slug}.yml"
        form = _load_yaml(path)
        body = form["body"]
        assert isinstance(body, list) and body
        assert _non_markdown_fields(body), f"{path} needs a non-markdown field"
        for item in body:
            assert "type" in item
            if item["type"] != "markdown":
                assert item.get("attributes", {}).get("label")


def test_issue_chooser_routes_questions_to_discussions():
    config = _load_yaml(ISSUE_DIR / "config.yml")
    links = config["contact_links"]
    urls = [link["url"] for link in links]
    assert any("/discussions/new?category=q-a" in url for url in urls)
    assert any("/discussions/new?category=ideas" in url for url in urls)
    assert any(url.endswith("/discussions") for url in urls)


def test_issue_forms_exist_for_bugs_and_features():
    for name in ("bug.yml", "feature.yml"):
        form = _load_yaml(ISSUE_DIR / name)
        assert form["body"]
        assert _non_markdown_fields(form["body"])


def test_community_guide_and_support_files_exist():
    for relative in (
        "docs/community.md",
        "docs/community.zh-CN.md",
        "SUPPORT.md",
        "CODE_OF_CONDUCT.md",
        "CONTRIBUTING.md",
    ):
        path = PROJECT_ROOT / relative
        text = path.read_text(encoding="utf-8")
        assert "github.com/xin-yi33/RxyCode/discussions" in text
        if relative.startswith("docs/community"):
            assert "gh repo edit" in text
            assert ".github/DISCUSSION_TEMPLATE" in text
