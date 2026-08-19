你是 RxyCode Phase G 前端独立审计员（gpt-5.6-luna）。不要改代码。
只审 PhaseG-H19「画廊四类 artifact 渲染」并挂到工具工作台。不要以看不到仓库判 FAIL。未改 schema。零 PHASE-I。

必须核对：
1. PreviewGallery 是否渲染真实 <img>/<video>/<pre>，而不是空 <div data-kind>。
2. hero maxWidth 1280、video 时长>8s 不渲染、>25MB 不渲染。
3. 测试是否 renderToStaticMarkup(PreviewGallery) 驱动组件本身。
4. ChatArea 工具卡片是否挂载 PreviewGallery（artifactsFromTool 读 tool arguments.artifacts；B14 未合入则空数组，不 mock）。
5. 路径 toFileUrl 处理 Windows 盘符。

源码：
- previewArtifacts.ts artifactView: hero/gallery→img, video→video, json→pre+summary.json 字段
- previewGallery.ts PreviewGallery createElement img/video/pre data-kind
- ChatArea ToolActivity 内 <PreviewGallery artifacts={artifactsFromTool(...)} /> 与 toolSourceLabel
- PreviewGallery.test.ts 断言 html 含 img/video/pre 与 data-kind 四类

测试源码（完整）：
html = renderToStaticMarkup(createElement(PreviewGallery, { artifacts: [hero D:\\...png, gallery, video 4s, json summary] }))
assert img, video, pre, data-kind 四类, max-width:1280px, headline done
canRender(video duration 9)=false
canRender(hero bytes 25MB+1)=false
toFileUrl('D:\\a\\b.png')==='file:///D:/a/b.png'
artifactView(hero).maxWidth===1280

canRender: bytes>25*1024*1024 false; video durationSec>8 false
toFileUrl 完整实现（先规范化反斜杠）：
function normalizePreviewPath(path) { return path.replace(/\\/g, '/') }
function toFileUrl(path) {
  const normalized = normalizePreviewPath(path)
  if (normalized.startsWith('file:')) return normalized
  if (/^[A-Za-z]:\//.test(normalized)) return `file:///${normalized}`
  if (normalized.startsWith('/')) return `file://${normalized}`
  return `file://${normalized}`
}
实测：toFileUrl('D:\\a\\b.png') === 'file:///D:/a/b.png' 已通过。

第一行 VERDICT: PASS 或 VERDICT: FAIL。
