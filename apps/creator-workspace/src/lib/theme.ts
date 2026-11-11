// Light / dark / system theme (docs/plans/creator-ui-v2-spec.md, requirement 1).
// The resolved theme lives on <html data-theme>, so CSS token blocks switch without any dark: utilities.

export type ThemePref = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "pdm-theme";

export function parseThemePref(raw: string | null | undefined): ThemePref {
  return raw === "light" || raw === "dark" || raw === "system" ? raw : "system";
}

export function resolveTheme(pref: ThemePref, systemDark: boolean): ResolvedTheme {
  if (pref === "system") return systemDark ? "dark" : "light";
  return pref;
}

/** Inline <head> script: sets data-theme before first paint so the page never flashes the wrong theme. */
export const themeBootScript = `(function(){try{var p=localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)});if(p!=="light"&&p!=="dark")p=window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light";document.documentElement.setAttribute("data-theme",p);}catch(e){document.documentElement.setAttribute("data-theme","light");}})();`;
