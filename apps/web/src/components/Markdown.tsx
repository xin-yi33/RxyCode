import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type AnimationEvent as ReactAnimationEvent,
} from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import type { Components } from "react-markdown"
import type { Pluggable, PluggableList } from "unified"

import { CopyButton } from "./CopyButton"
import {
  createStreamRevealPlugin,
  graphemeBoundaryAtOrAfter,
  mountRevealFrom,
} from "./streamReveal"

// 代码块：共享 CopyButton（UI-07 反馈契约）+ 横向可滚动。复制文本取自渲染后的
// <pre>，按钮仍由 group-hover / focus-within 显露，图标盒尺寸固定不跳。
function CodeBlock({ children }: { children?: React.ReactNode }) {
  const ref = useRef<HTMLPreElement>(null)
  return (
    <div className="group relative my-2">
      <span
        className={
          "absolute right-2 top-2 inline-flex opacity-0 transition-opacity " +
          "group-hover:opacity-100 focus-within:opacity-100"
        }
      >
        <CopyButton
          text={() => ref.current?.textContent ?? ""}
          ariaLabel="复制代码"
          size={14}
          className="rounded-md border border-border bg-card p-1.5 text-muted hover:bg-sidebar"
        />
      </span>
      <pre
        ref={ref}
        className="overflow-x-auto rounded-lg bg-sidebar p-3 font-mono text-xs leading-relaxed"
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

function readReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof document === "undefined") return false
  if (document.documentElement.classList.contains("reduced-motion")) return true
  return Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches)
}

/** System / settings reduced-motion signal, kept live while mounted. */
function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState<boolean>(readReducedMotion)
  useEffect(() => {
    const query =
      typeof window.matchMedia === "function"
        ? window.matchMedia("(prefers-reduced-motion: reduce)")
        : null
    const sync = () => setReduced(readReducedMotion())
    sync()
    query?.addEventListener?.("change", sync)
    const root = typeof document !== "undefined" ? document.documentElement : null
    const observer =
      root && typeof MutationObserver !== "undefined" ? new MutationObserver(sync) : null
    if (root && observer) {
      observer.observe(root, { attributes: true, attributeFilter: ["class"] })
    }
    return () => {
      query?.removeEventListener?.("change", sync)
      observer?.disconnect()
    }
  }, [])
  return reduced
}

// 动画兜底：万一 animationend 没触发（引擎差异/被取消），也把 span 收成纯文本，
// 避免 span/定时器长期堆积。正常路径是最后一个 glyph 的 animationend。
const REVEAL_FALLBACK_MS = 1_600

type RevealState = {
  text: string
  from: number
  animate: boolean
}

function useStreamReveal(text: string, streaming: boolean, animateAtMount: boolean) {
  const reduced = useReducedMotion()
  const animate = streaming && !reduced
  const hostRef = useRef<HTMLDivElement>(null)

  // 首次挂载：历史文本一律不逐字（from = 全文长度）；只有"到达时就是活的"
  // 新条目才把首批新增文本做 reveal。
  const [state, setState] = useState<RevealState>(() => ({
    text,
    from: animate && animateAtMount ? mountRevealFrom(text) : text.length,
    animate,
  }))

  // prop 变化时派生下一次 reveal 起点（React 允许同组件 render 期间调整 state）：
  // 只把"之前的文本"当纯文本，之后的增量进入 glyph 动画。
  if (text !== state.text || animate !== state.animate) {
    let from = state.from
    if (!animate) {
      from = text.length
    } else if (!state.animate) {
      from = text.length // 刚转为直播：不重播已显示的历史
    } else if (text.length > state.text.length && text.startsWith(state.text)) {
      from = state.text.length // 只动画这次追加的部分
    } else {
      from = text.length // 非追加式改写（快照替换等）：不逐字
    }
    setState({ text, from, animate })
  }

  const clampedFrom = animate ? Math.min(state.from, text.length) : text.length
  const revealFrom = animate
    ? graphemeBoundaryAtOrAfter(text, clampedFrom)
    : text.length

  const settle = useCallback(() => {
    setState((current) =>
      current.from >= current.text.length
        ? current
        : { ...current, from: current.text.length },
    )
  }, [])

  useEffect(() => {
    if (!state.animate || state.from >= state.text.length) return
    const timer = window.setTimeout(settle, REVEAL_FALLBACK_MS)
    return () => window.clearTimeout(timer)
  }, [state, settle])

  const onAnimationEnd = (event: ReactAnimationEvent<HTMLDivElement>) => {
    const target = event.target
    if (!(target instanceof HTMLElement)) return
    if (!target.classList.contains("rxy-stream-glyph")) return
    const host = hostRef.current
    if (!host) return
    for (const glyph of host.querySelectorAll<HTMLElement>(".rxy-stream-glyph")) {
      const animations =
        typeof glyph.getAnimations === "function" ? glyph.getAnimations() : []
      const stillRunning = animations.some(
        (animation) => animation.playState === "running",
      )
      if (stillRunning) return
    }
    settle()
  }

  return { hostRef, revealFrom, onAnimationEnd }
}

// 助手消息体的唯一 markdown 渲染入口：react-markdown 默认不渲染原始
// HTML（等价于注入面已消毒），链接再经 linkIsSafe 白名单 + noopener。
// streaming 时只把最新追加的增量文字包成 .rxy-stream-glyph 做 90ms stagger
// reveal；history / 代码块 / 链接 URL 不逐字，动画结束后恢复纯文本。
export function Markdown({
  text,
  streaming = false,
  animateAtMount = false,
}: {
  text: string
  streaming?: boolean
  animateAtMount?: boolean
}) {
  const { hostRef, revealFrom, onAnimationEnd } = useStreamReveal(
    text,
    streaming,
    animateAtMount,
  )
  const revealActive = revealFrom < text.length
  const pluggable = useMemo<PluggableList>(() => {
    if (!revealActive) return [remarkGfm]
    return [
      remarkGfm,
      createStreamRevealPlugin({ text, from: revealFrom }) as unknown as Pluggable,
    ]
  }, [revealActive, text, revealFrom])

  return (
    <div
      ref={hostRef}
      className="rxy-md text-sm leading-relaxed"
      onAnimationEnd={onAnimationEnd}
    >
      <ReactMarkdown remarkPlugins={pluggable} components={components}>
        {text}
      </ReactMarkdown>
    </div>
  )
}