import { useEffect } from "react"

const VIEWPORT_PROPERTIES = [
  "--rxy-viewport-height",
  "--rxy-viewport-width",
  "--rxy-viewport-offset-top",
  "--rxy-viewport-offset-left",
] as const

/** Align mobile overlays with the actually visible area as browser chrome/keyboard changes. */
export function useMobileViewport() {
  useEffect(() => {
    const viewport = window.visualViewport
    if (!viewport) return

    const root = document.documentElement
    const previous = VIEWPORT_PROPERTIES.map((property) => [
      property,
      root.style.getPropertyValue(property),
      root.style.getPropertyPriority(property),
    ] as const)
    let frame = 0
    let lastValues = ""

    const update = () => {
      frame = 0
      const values = [
        `${Math.max(1, Math.round(viewport.height))}px`,
        `${Math.max(1, Math.round(viewport.width))}px`,
        `${Math.max(0, Math.round(viewport.offsetTop))}px`,
        `${Math.max(0, Math.round(viewport.offsetLeft))}px`,
      ]
      const signature = values.join(" ")
      if (signature === lastValues) return
      lastValues = signature
      VIEWPORT_PROPERTIES.forEach((property, index) => {
        root.style.setProperty(property, values[index])
      })
    }

    const scheduleUpdate = () => {
      if (frame === 0) frame = window.requestAnimationFrame(update)
    }

    scheduleUpdate()
    viewport.addEventListener("resize", scheduleUpdate, { passive: true })
    viewport.addEventListener("scroll", scheduleUpdate, { passive: true })
    window.addEventListener("resize", scheduleUpdate, { passive: true })

    return () => {
      viewport.removeEventListener("resize", scheduleUpdate)
      viewport.removeEventListener("scroll", scheduleUpdate)
      window.removeEventListener("resize", scheduleUpdate)
      if (frame !== 0) window.cancelAnimationFrame(frame)
      previous.forEach(([property, value, priority]) => {
        if (value) root.style.setProperty(property, value, priority)
        else root.style.removeProperty(property)
      })
    }
  }, [])
}
