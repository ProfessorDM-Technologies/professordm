// One source for button styling (spec section 6). Works on <button>, <Link> and <a>.
// Navy is the action colour (spec decision D4); teal is reserved for success, never for actions.

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "md" | "sm";

const BASE =
  "inline-flex items-center justify-center gap-2 rounded-lg font-semibold motion-safe:transition-colors disabled:cursor-not-allowed disabled:opacity-60";

const VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-pdm-primary text-white hover:bg-pdm-primary-hover",
  secondary: "border border-pdm-border-strong bg-white text-pdm-ink hover:bg-pdm-canvas",
  ghost: "text-pdm-primary hover:bg-pdm-primary-tint",
  danger: "bg-pdm-danger-text text-white hover:opacity-90",
};

const SIZES: Record<ButtonSize, string> = {
  md: "min-h-11 px-4 text-sm",
  sm: "min-h-9 px-3 text-sm",
};

export function buttonClass(variant: ButtonVariant = "primary", size: ButtonSize = "md", extra?: string): string {
  return [BASE, VARIANTS[variant], SIZES[size], extra].filter(Boolean).join(" ");
}
