import { useRef, useState } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import type { Components } from "react-markdown"

import { IconCheck, IconCopy } from "../../components/icons"

// 代码块：复制按钮 + 横向可滚动。复制文本取自渲染后的 <pre>。
function CodeBlock({ children }: { children?: React.ReactNode }) {
  const ref = useRef<HTMLPreElement>(null)
  const [copied, setCopied] = useState(false)
  const copy = () => {
    const text = ref.current?.textContent ?? ""
    const done = () => {
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    }
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(() => undefined)
    } else {
      const area = document.createElement("textarea")
      area.value = text
      document.body.appendChild(area)
      area.select()
      try {
        document.execCommand("copy")
        done()
      } catch {
        // 剪贴板不可用 —— 静默失败
      }
      document.body.removeChild(area)
    }
  }
  return (
    <div className="group relative my-2">
      <button
        type="button"
        onClick={copy}
        aria-label={copied ? "已复制" : "复制代码"}
        className={
          "absolute right-2 top-2 rounded-md border border-border bg-card " +
          "p-1.5 text-muted opacity-0 transition-opacity hover:bg-sidebar " +
          "focus-visible:opacity-100 group-hover:opacity-100"
        }
      >
        {copied ? <IconCheck size={14} /> : <IconCopy size={14} />}
      </button>
      <pre
        ref={ref}
        className="overflow-x-auto rounded-lg bg-sidebar p-3 text-xs leading-relaxed"
      >
        {children}
      </pre>
    </div>
  )
}

function linkIsSafe(href: string | undefined): boolean {
  if (!href) return false
  return /^(https?:|mailto:)/i.test(href.trim())
}

const components: Components = {
  a({ href, children }) {
    // 非 http(s)/mailto: 链接渲染为纯文本 —— 不信任 javascript:/data: 等。
    if (!linkIsSafe(href)) return <>{children}</>
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-running-ink underline underline-offset-2"
      >
        {children}
      </a>
    )
  },
  pre({ children }) {
    return <CodeBlock>{children}</CodeBlock>
  },
  code({ className, children }) {
    // 行内样式对 <pre> 内的代码由 .rxy-md pre code 规则剥掉（globals.css）。
    const language = typeof className === "string" ? className : undefined
    return (
      <code
        className={
          "rounded bg-sidebar px-1 py-0.5 font-mono text-[0.85em] " + (language ?? "")
        }
      >
        {children}
      </code>
    )
  },
  table({ children }) {
    return (
      <div className="my-2 overflow-x-auto">
        <table className="w-full border-collapse text-left text-xs">{children}</table>
      </div>
    )
  },
  th({ children }) {
    return (
      <th className="border border-border bg-sidebar px-2 py-1 font-medium">
        {children}
      </th>
    )
  },
  td({ children }) {
    return <td className="border border-border px-2 py-1 align-top">{children}</td>
  },
  h1({ children }) {
    return <h1 className="mb-2 mt-4 text-lg font-semibold first:mt-0">{children}</h1>
  },
  h2({ children }) {
    return <h2 className="mb-2 mt-4 text-base font-semibold first:mt-0">{children}</h2>
  },
  h3({ children }) {
    return <h3 className="mb-1 mt-3 text-sm font-semibold first:mt-0">{children}</h3>
  },
  h4({ children }) {
    return <h4 className="mb-1 mt-3 text-sm font-medium first:mt-0">{children}</h4>
  },
  p({ children }) {
    return <p className="my-2 first:mt-0 last:mb-0">{children}</p>
  },
  ul({ children }) {
    return <ul className="my-2 list-disc space-y-1 pl-5">{children}</ul>
  },
  ol({ children }) {
    return <ol className="my-2 list-decimal space-y-1 pl-5">{children}</ol>
  },
  blockquote({ children }) {
    return (
      <blockquote className="my-2 border-l-2 border-border pl-3 text-muted">
        {children}
      </blockquote>
    )
  },
  hr() {
    return <hr className="my-3 border-border" />
  },
}

export function Markdown({ text }: { text: string }) {
  return (
    <div className="rxy-md text-sm leading-relaxed">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {text}
      </ReactMarkdown>
    </div>
  )
}
