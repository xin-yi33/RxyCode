import type { ButtonHTMLAttributes } from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "../../lib/cn"

// UI-01: the composer is a single surface, so its inner controls use the
// ghost variant (no border, transparent background, hover background only).
const buttonVariants = cva(
  "inline-flex items-center justify-center rounded-md px-3 py-2 text-sm rxy-weight-medium",
  {
    variants: {
      variant: {
        default:
          "bg-foreground text-background focus-visible:outline-2 focus-visible:outline-offset-2",
        outline:
          "border border-border bg-card text-foreground " +
          "focus-visible:outline-2 focus-visible:outline-offset-2",
        // Ghost controls put the focus ring inside the control via the shared
        // .rxy-ghost-control rule, so they never draw a second outer outline.
        ghost: "rxy-ghost-control text-muted-ink",
      },
      size: {
        default: "",
        sm: "px-2 py-1 text-xs",
        icon: "h-9 w-9 rounded-full p-0",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
)

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof buttonVariants>

export function Button({ className, variant, size, type = "button", ...props }: ButtonProps) {
  return (
    <button
      type={type}
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  )
}
