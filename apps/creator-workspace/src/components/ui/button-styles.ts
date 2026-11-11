// One source for button styling (spec section 6). Works on <button>, <Link> and <a>.
// Navy is the action colour (spec decision D4); teal is reserved for success, never for actions.

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "md" | "sm";

const BASE =
  "inline-flex items-center justify-center gap-2 rounded-lg font-semibold motion-safe:transition-[color,background-color,border-color,scale] motion-safe:duration-150 motion-safe:active:scale-[.98] disabled:cursor-not-allowed disabled:opacity-60 disabled:active:scale-100";

const VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-pdm-primary text-pdm-on-primary hover:bg-pdm-primary-hover",
  secondary: "border border-pdm-border-strong bg-pdm-card text-pdm-ink hover:bg-pdm-canvas",
  ghost: "text-pdm-primary hover:bg-pdm-primary-tint",
  danger: "bg-pdm-danger-text text-pdm-on-primary hover:opacity-90",
};

const SIZES: Record<ButtonSize, string> = {
  md: "min-h-11 px-4 text-sm",
  sm: "min-h-9 px-3 text-sm",
};

export function buttonClass(variant: ButtonVariant = "primary", size: ButtonSize = "md", extra?: string): string {
  return [BASE, VARIANTS[variant], SIZES[size], extra].filter(Boolean).join(" ");
}
