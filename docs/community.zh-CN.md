# GitHub Discussions 社区指南

普通开发者不需要组织账号、付费套餐或 GitHub Pages。
**个人公开或私有仓库就可以开通 Discussions，把它当成项目论坛。**

RxyCode 的论坛：[https://github.com/xin-yi33/RxyCode/discussions](https://github.com/xin-yi33/RxyCode/discussions)

英文版：[community.md](./community.md)

## 1. 怎么获得自己的 Discussion

### 条件

| 条件 | 说明 |
|------|------|
| GitHub 账号 | 免费账号即可 |
| 一个仓库 | 个人仓库或组织仓库都可以 |
| 权限 | 仓库 **Owner**，或对该仓库有 **Admin / Write** |
| 套餐 | 公开、私有仓库都支持 Discussions |

没有仓库时，先建一个空仓库（例如 `my-project`）。论坛挂在仓库上，不需要单独买域名。

### 网页开通（最常见）

1. 打开仓库首页。
2. 点 **Settings**。
3. 滚到 **Features**。
4. 点 **Set up discussions**（或勾选 **Discussions**）。
5. 编辑欢迎帖模板，点 **Start discussion**。

完成后仓库导航会出现 **Discussions** 标签。可见性跟仓库一致：私有仓库只有协作者能进论坛。

### 命令行开通

需要 [GitHub CLI](https://cli.github.com/) 且已 `gh auth login`：

```bash
gh repo edit OWNER/REPO --enable-discussions
```

关掉：

```bash
gh repo edit OWNER/REPO --enable-discussions=false
```

### 发第一帖

1. 打开仓库的 **Discussions**。
2. **New discussion**。
3. 选分类（Q&A、Ideas、General…）。
4. 写标题和正文，**Start discussion**。

能查看仓库的登录用户都可以发帖（组织级 Discussions 以源仓库的可见性为准）。

### 个人仓库 vs 组织论坛

- **个人开发者**：在自己的仓库开通即可。这就是「自己的讨论论坛」。
- **组织**：可以在组织设置里开通组织级 Discussions，并指定一个源仓库。帖子显示在组织主页，数据仍存在那个仓库里。

## 2. 怎么把 Discussions 建成论坛

开通只是第一步。可维护的论坛需要分区、发帖表单、和 Issue 分流。

```
Issues          = 可跟踪的缺陷 / 已拍板的功能
Discussions     = 问答、想法、展示、公告、投票
.github/        = 表单与分流（随 git 走，不依赖网页点选）
```

### 2.1 用好默认分区

开通后 GitHub 会给出这些分类：

| 分类 | slug | 用途 |
|------|------|------|
| Announcements | `announcements` | 维护者公告，建议仅维护者发帖并置顶 |
| Q&A | `q-a` | 问答；可把回复标成 **Answer** |
| Ideas | `ideas` | 功能想法，先讨论再开 Issue |
| Show and tell | `show-and-tell` | 展示用本项目做出的东西 |
| General | `general` | 其他交流 |
| Polls | `polls` | 投票（不支持表单文件） |

在 Discussions 页分类列表旁点铅笔，可改名、改 emoji、增删分类。

### 2.2 用 git 固化发帖表单

在默认分支放 YAML，文件名必须等于分类 slug：

```
.github/DISCUSSION_TEMPLATE/
  q-a.yml
  ideas.yml
  show-and-tell.yml
  general.yml
  announcements.yml
```

Polls 没有表单文件。语法见
[Syntax for discussion category forms](https://docs.github.com/en/discussions/managing-discussions-for-your-community/syntax-for-discussion-category-forms)。

### 2.3 把「提问」从 Issues 引走

```
.github/ISSUE_TEMPLATE/config.yml
```

用 `contact_links` 指向 `discussions/new?category=q-a`。打开 Issue 时 GitHub 会先给出「去论坛提问」入口。

### 2.4 写清去哪里说话

在 `CONTRIBUTING.md`、`SUPPORT.md`、README 里写死：

- 用法问题 → Discussions / Q&A
- 想法 → Discussions / Ideas
- 可复现缺陷 → Issues
- 代码贡献 → Pull Request

### 2.5 冷启动

1. 发一篇 **Announcements** 欢迎帖并置顶。
2. 自己先在 Q&A 回答几条高频问题（安装、加模型、OpenTUI vs Desktop）。
3. 好回答点 **Mark as answer**。
4. 重复帖合并或关掉，并链到 Canonical 帖。

## 3. RxyCode 当前怎么建

本仓库已经开通 Discussions。本指南对应的仓库文件：

| 文件 | 作用 |
|------|------|
| `.github/DISCUSSION_TEMPLATE/*.yml` | 各分区发帖表单 |
| `.github/ISSUE_TEMPLATE/config.yml` | Issue 页链到论坛 |
| `.github/ISSUE_TEMPLATE/bug.yml` | 缺陷 Issue 表单 |
| `.github/ISSUE_TEMPLATE/feature.yml` | 已拍板功能的 Issue 表单 |
| [SUPPORT.md](../SUPPORT.md) | 去哪里获得帮助 |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | 贡献与发帖约定 |
| [CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md) | 论坛行为规范 |

维护者还需要在 GitHub 网页上做、git 做不到的两件事：

1. 用 Announcements 表单发欢迎帖并 **Pin discussion**。
2. 按需改分类描述或权限（例如 Announcements 仅维护者可发）。

官方总览：[GitHub Discussions quickstart](https://docs.github.com/en/discussions/quickstart)。
