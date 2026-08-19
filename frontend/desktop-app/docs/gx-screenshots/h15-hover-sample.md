# H15 hover 取样对照

Codex 实机取样（卡内规格）：

| 主题 | 值 |
|---|---|
| 浅色 hover | `rgba(0,0,0,0.06)` |
| 深色 hover | `rgba(255,255,255,0.08)` |
| 折叠符号间距 | 4px |

落地：

- `src/lib/sessionCategories.ts` `HOVER_LIGHT` / `HOVER_DARK` / `CHEVRON_GAP_PX`
- `SessionList` `data-hover-light` / `data-hover-dark`
- `main.css` `.session-item:hover` / `.session-category-title:hover` 使用同一组值
