// Light is the default for everyone (apps/creator-workspace/DESIGN.md "Theme"); the OS setting is not followed.
export const THEME_COOKIE = "pdm-theme";

export type Theme = "light" | "dark";

export function parseTheme(value: unknown): Theme {
  return value === "dark" ? "dark" : "light";
}
