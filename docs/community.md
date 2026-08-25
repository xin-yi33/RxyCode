# GitHub Discussions community guide

You do not need an organization, a paid plan, or GitHub Pages.
**Any developer can turn a personal public or private repository into a discussion forum.**

RxyCode forum: [https://github.com/xin-yi33/RxyCode/discussions](https://github.com/xin-yi33/RxyCode/discussions)

中文版：[community.zh-CN.md](./community.zh-CN.md)

## 1. Get your own Discussions

### Requirements

| Need | Detail |
|------|--------|
| GitHub account | Free accounts are enough |
| A repository | Personal or organization |
| Permission | **Owner**, or **Admin / Write** on that repo |
| Plan | Discussions work on public and private repos |

Create an empty repository first if you do not have one. The forum lives on the repo; you do not buy a separate domain.

### Enable in the UI

1. Open the repository.
2. Click **Settings**.
3. Scroll to **Features**.
4. Click **Set up discussions** (or enable **Discussions**).
5. Edit the welcome post and click **Start discussion**.

A **Discussions** tab appears in the repo nav. Visibility follows the repository: private repos keep the forum private.

### Enable with GitHub CLI

```bash
gh repo edit OWNER/REPO --enable-discussions
```

Disable with `--enable-discussions=false`.

### Start a thread

Open **Discussions** → **New discussion** → pick a category → submit.
Anyone who can view the repository can post.

### Personal repo vs organization forum

- **Individual developer:** enable Discussions on your own repo. That is your forum.
- **Organization:** enable org-level Discussions and point them at a source repository. Threads appear on the org profile; data still lives in that repo.

## 2. Turn Discussions into a forum

Enabling the tab is not enough. A usable forum needs categories, post forms, and a split from Issues.

```
Issues          = actionable bugs / agreed features
Discussions     = Q&A, ideas, show-and-tell, announcements, polls
.github/        = forms and routing that travel with git
```

### 2.1 Default categories

| Category | slug | Use |
|----------|------|-----|
| Announcements | `announcements` | Maintainer posts; pin them |
| Q&A | `q-a` | Questions; mark an **Answer** |
| Ideas | `ideas` | Design talk before an issue |
| Show and tell | `show-and-tell` | Things people built |
| General | `general` | Everything else |
| Polls | `polls` | Votes (no category form file) |

Edit categories from the pencil icon next to the category list.

### 2.2 Commit category forms

On the default branch:

```
.github/DISCUSSION_TEMPLATE/
  q-a.yml
  ideas.yml
  show-and-tell.yml
  general.yml
  announcements.yml
```

The filename must match the category slug. Polls have no form file. See
[Syntax for discussion category forms](https://docs.github.com/en/discussions/managing-discussions-for-your-community/syntax-for-discussion-category-forms).

### 2.3 Route questions away from Issues

In `.github/ISSUE_TEMPLATE/config.yml`, add `contact_links` to
`discussions/new?category=q-a`. GitHub shows those links when someone opens an issue.

### 2.4 Say where to talk

Document the split in `CONTRIBUTING.md`, `SUPPORT.md`, and the README:

- How-to → Discussions / Q&A
- Ideas → Discussions / Ideas
- Reproducible bugs → Issues
- Code → Pull requests

### 2.5 Cold start

1. Publish and pin an **Announcements** welcome post.
2. Seed a few Q&A answers (install, add-model, OpenTUI vs Desktop).
3. Mark accepted answers.
4. Close duplicates with a link to the canonical thread.

## 3. How RxyCode is set up

This repository already has Discussions enabled. The git-managed pieces are:

| Path | Role |
|------|------|
| `.github/DISCUSSION_TEMPLATE/*.yml` | Per-category post forms |
| `.github/ISSUE_TEMPLATE/config.yml` | Issue chooser links to the forum |
| `.github/ISSUE_TEMPLATE/bug.yml` | Bug issue form |
| `.github/ISSUE_TEMPLATE/feature.yml` | Feature issue form |
| [SUPPORT.md](../SUPPORT.md) | Where to get help |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | Contribution and posting rules |
| [CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md) | Forum conduct |

Maintainers still need two GitHub UI steps that git cannot do:

1. Publish the welcome Announcement and **Pin discussion**.
2. Optionally restrict who can post in Announcements.

Official overview: [GitHub Discussions quickstart](https://docs.github.com/en/discussions/quickstart).
