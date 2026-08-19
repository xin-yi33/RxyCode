VERDICT: PASS

Phase G-H19「画廊四类 artifact 渲染」及工具工作台挂载核对通过：

1. **真实元素渲染**
   - `PreviewGallery` 通过 `createElement` 渲染真实：
     - `img`：`hero`、`gallery`
     - `video`：`video`
     - `pre`：`json`
   - 非空 `div[data-kind]` 占位实现。
   - 测试使用 `renderToStaticMarkup(createElement(PreviewGallery, ...))`，由组件本身驱动渲染，并断言 `img/video/pre` 及四类 `data-kind`。

2. **尺寸与视频限制**
   - `hero` 的 `maxWidth` 为 `1280`，测试已断言 `max-width:1280px` 及 `artifactView(hero).maxWidth === 1280`。
   - `video` 时长大于 `8s` 时 `canRender` 返回 `false`。
   - artifact 大小大于 `25 * 1024 * 1024` 字节时 `canRender` 返回 `false`。
   - 测试覆盖 `9s` 视频及 `25MB + 1` 的边界场景。

3. **ChatArea 工具卡片挂载**
   - `ToolActivity` 已挂载：
     ```tsx
     <PreviewGallery artifacts={artifactsFromTool(...)} />
     ```
   - `artifactsFromTool` 从 `tool arguments.artifacts` 读取 artifact。
   - B14 未合入时使用空数组，不通过 mock 伪造 artifact。
   - `toolSourceLabel` 同时保留。

4. **Windows 路径**
   - `toFileUrl` 先将反斜杠规范化为 `/`。
   - Windows 盘符路径会转换为 `file:///D:/...`。
   - `toFileUrl('D:\\a\\b.png') === 'file:///D:/a/b.png'` 已通过。

5. **范围约束**
   - 未发现 schema 修改。
   - 未引入 PHASE-I 内容。
   - 审计范围仅覆盖 Phase G-H19 及其工具工作台挂载。