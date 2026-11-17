import { Button as ButtonPrimitive } from "@base-ui/react/button";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

// Focus uses the global outline from globals.css (DESIGN.md › Accessibility); never override it here.
// Hover color: 120ms ease. Press: scale(0.97), 100ms --ease-out (DESIGN.md › Motion).
const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 rounded-lg border border-transparent font-medium whitespace-nowrap select-none transition-[color,background-color,border-color,scale] duration-[120ms,120ms,120ms,100ms] ease-[ease,ease,ease,var(--ease-out)] active:not-aria-[haspopup]:scale-[0.97] disabled:pointer-events-none disabled:opacity-50 aria-invalid:border-destructive [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-brand-strong dark:hover:bg-brand-button/85",
        outline: "border-border-strong bg-surface text-foreground hover:bg-muted",
        ghost: "text-foreground hover:bg-muted aria-expanded:bg-muted",
        destructive: "bg-destructive text-white hover:bg-destructive/90",
      },
      size: {
        // Touch screens get 44px targets (DESIGN.md › Accessibility).
        sm: "h-8 px-3 text-meta pointer-coarse:h-11",
        default: "h-10 px-4 text-ui",
        lg: "h-11 px-4 text-ui",
        icon: "size-8",
        "icon-lg": "size-11",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

function Button({
  className,
  variant = "default",
  size = "default",
  ...props
}: ButtonPrimitive.Props & VariantProps<typeof buttonVariants>) {
  return (
    <ButtonPrimitive
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  );
}

export { Button, buttonVariants };
