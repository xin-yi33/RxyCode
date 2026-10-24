// UI-ART：按扩展名给文件配类型图标 —— Windows 资源管理器式的"类别着色 +
// 类别字形"：docx 蓝、xlsx 绿、pptx 橙、pdf 红、图片紫、压缩包棕、代码青、
// 媒体粉、可执行深灰、未知文件灰。笔画跟随 currentColor，字形给辨识线索。
import type { SVGProps } from "react"

type IconProps = SVGProps<SVGSVGElement> & { size?: number }

type FileCategory =
  | "document"
  | "sheet"
  | "slides"
  | "pdf"
  | "image"
  | "archive"
  | "code"
  | "audio"
  | "video"
  | "app"
  | "generic"

const CATEGORY_COLOR: Record<FileCategory, string> = {
  document: "var(--rxy-ft-document, #2563eb)",
  sheet: "var(--rxy-ft-sheet, #15803d)",
  slides: "var(--rxy-ft-slides, #c2410c)",
  pdf: "var(--rxy-ft-pdf, #dc2626)",
  image: "var(--rxy-ft-image, #7c3aed)",
  archive: "var(--rxy-ft-archive, #a16207)",
  code: "var(--rxy-ft-code, #0d9488)",
  audio: "var(--rxy-ft-media, #db2777)",
  video: "var(--rxy-ft-media, #db2777)",
  app: "var(--rxy-ft-app, #52525b)",
  generic: "var(--rxy-ft-generic, #71717a)",
}

const EXT_CATEGORY: Record<string, FileCategory> = {
  // 文档
  txt: "document",
  md: "document",
  markdown: "document",
  doc: "document",
  docx: "document",
  odt: "document",
  rtf: "document",
  pages: "document",
  tex: "document",
  // 表格
  csv: "sheet",
  tsv: "sheet",
  xls: "sheet",
  xlsx: "sheet",
  ods: "sheet",
  numbers: "sheet",
  // 演示
  ppt: "slides",
  pptx: "slides",
  odp: "slides",
  key: "slides",
  pdf: "pdf",
  // 图片
  png: "image",
  jpg: "image",
  jpeg: "image",
  gif: "image",
  webp: "image",
  svg: "image",
  bmp: "image",
  ico: "image",
  tif: "image",
  tiff: "image",
  heic: "image",
  // 压缩包
  zip: "archive",
  tar: "archive",
  gz: "archive",
  tgz: "archive",
  bz2: "archive",
  xz: "archive",
  zst: "archive",
  "7z": "archive",
  rar: "archive",
  jar: "archive",
  // 代码 / 配置 / 数据
  py: "code",
  js: "code",
  jsx: "code",
  mjs: "code",
  cjs: "code",
  ts: "code",
  tsx: "code",
  mts: "code",
  cts: "code",
  json: "code",
  jsonl: "code",
  yaml: "code",
  yml: "code",
  toml: "code",
  ini: "code",
  cfg: "code",
  xml: "code",
  html: "code",
  htm: "code",
  css: "code",
  scss: "code",
  less: "code",
  sql: "code",
  sh: "code",
  bash: "code",
  zsh: "code",
  bat: "code",
  ps1: "code",
  go: "code",
  rs: "code",
  java: "code",
  kt: "code",
  c: "code",
  h: "code",
  cc: "code",
  cpp: "code",
  cxx: "code",
  hpp: "code",
  cs: "code",
  rb: "code",
  php: "code",
  swift: "code",
  lua: "code",
  r: "code",
  ipynb: "code",
  dockerfile: "code",
  makefile: "code",
  lock: "code",
  env: "code",
  // 音视频
  mp3: "audio",
  wav: "audio",
  m4a: "audio",
  flac: "audio",
  ogg: "audio",
  aac: "audio",
  mp4: "video",
  mkv: "video",
  mov: "video",
  avi: "video",
  webm: "video",
  m4v: "video",
  // 可执行 / 应用
  exe: "app",
  msi: "app",
  dmg: "app",
  app: "app",
  apk: "app",
  deb: "app",
  rpm: "app",
  pkg: "app",
}

export function fileCategory(name: string): FileCategory {
  const base = name.slice(name.lastIndexOf("/") + 1)
  // 无扩展名的常见代码/配置名按内容归类（Dockerfile、Makefile、.env）。
  const lower = base.toLowerCase()
  if (EXT_CATEGORY[lower]) return EXT_CATEGORY[lower]
  const dot = lower.lastIndexOf(".")
  if (dot <= 0 || dot === lower.length - 1) return "generic"
  return EXT_CATEGORY[lower.slice(dot + 1)] ?? "generic"
}

function Glyph({ category }: { category: FileCategory }) {
  switch (category) {
    case "sheet":
      return (
        <>
          <line x1="8" y1="9.5" x2="16" y2="9.5" />
          <line x1="8" y1="12.5" x2="16" y2="12.5" />
          <line x1="12" y1="9.5" x2="12" y2="17" />
        </>
      )
    case "slides":
      return (
        <>
          <rect x="7" y="10" width="10" height="6" rx="1" />
          <line x1="9.5" y1="12" x2="14.5" y2="12" />
          <line x1="9.5" y1="14" x2="14.5" y2="14" />
        </>
      )
    case "pdf":
      return (
        <>
          <path d="M8 16.5c1-3 2.5-5 4-6.5-1-1-1.5-2-1-3s2 .5 2 2c.8-1 2-1.5 3-1.5s.8 1.8-1 2.8c-1 .7-2.3 1-3.2 1.3-.5 1.7-1.2 3.4-3.8 4.4z" />
        </>
      )
    case "image":
      return (
        <>
          <circle cx="9.5" cy="10" r="1.2" />
          <path d="M7 16.5l3-3.5 2 2 2.5-3 2.5 4.5z" />
        </>
      )
    case "archive":
      return (
        <>
          <line x1="10" y1="9" x2="10" y2="10" />
          <line x1="12" y1="10" x2="12" y2="11" />
          <line x1="10" y1="11" x2="10" y2="12" />
          <line x1="12" y1="12" x2="12" y2="13" />
          <line x1="10" y1="13" x2="10" y2="14" />
          <rect x="9" y="15" width="4" height="2.5" rx="0.5" />
        </>
      )
    case "code":
      return (
        <>
          <polyline points="9 11 7 13 9 15" />
          <polyline points="15 11 17 13 15 15" />
        </>
      )
    case "audio":
      return (
        <>
          <path d="M9.5 15.5v-6l5-1.2v5.9" />
          <circle cx="8.3" cy="15.7" r="1.3" />
          <circle cx="13.3" cy="14.4" r="1.3" />
        </>
      )
    case "video":
      return (
        <>
          <rect x="7.5" y="10" width="9" height="7" rx="1" />
          <polygon points="10.5 12 14 13.5 10.5 15" fill="currentColor" stroke="none" />
        </>
      )
    case "app":
      return (
        <>
          <rect x="8" y="10" width="8" height="8" rx="1.5" />
          <line x1="11" y1="12.5" x2="13" y2="12.5" />
        </>
      )
    case "document":
      return (
        <>
          <line x1="8.5" y1="11" x2="15.5" y2="11" />
          <line x1="8.5" y1="13.5" x2="15.5" y2="13.5" />
          <line x1="8.5" y1="16" x2="12.5" y2="16" />
        </>
      )
    default:
      return null
  }
}

export function FileTypeIcon({ name, size = 16, ...props }: IconProps & { name: string }) {
  const category = fileCategory(name)
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      style={{ color: CATEGORY_COLOR[category] }}
      data-category={category}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      data-file-category={category}
      {...props}
    >
      {/* 文件页 + 折角（所有类型共用的外壳，Windows 默认图标造型）。 */}
      <path d="M6.5 3.5h7.5l3.5 3.5v13a1 1 0 0 1-1 1h-10a1 1 0 0 1-1-1v-15a1 1 0 0 1 1-1z" />
      <path d="M14 3.5V7h3.5" />
      <Glyph category={category} />
    </svg>
  )
}
