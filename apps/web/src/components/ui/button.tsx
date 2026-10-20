import type { ButtonHTMLAttributes } from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "../../lib/cn"

const buttonVariants = cva(
  "inline-flex items-center justify-center rounded-md px-3 py-2 text-sm font-medium " +
    "focus-visible:outline-2 focus-visible:outline-offset-2",
  {
    variants: {
      variant: {
        default: "bg-foreground text-background",
        outline: "border border-border bg-card text-foreground",
      },
      size: {
        default: "",
        sm: "px-2 py-1 text-xs",
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
