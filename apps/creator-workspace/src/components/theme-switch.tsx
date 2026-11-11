"use client";

import { useEffect, useState } from "react";
import { THEME_STORAGE_KEY, parseThemePref, resolveTheme, type ThemePref } from "@/lib/theme";

const OPTIONS: { value: ThemePref; label: string }[] = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "system", label: "System" },
];

function readPref(): ThemePref {
  try {
    return parseThemePref(localStorage.getItem(THEME_STORAGE_KEY));
  } catch {
    return "system";
  }
}

function apply(pref: ThemePref) {
  const systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.setAttribute("data-theme", resolveTheme(pref, systemDark));
}

/** Light / Dark / System as a native radio group (spec v2, requirement 1). Remembered per browser. */
export function ThemeSwitch() {
  // Starts as "system" on the server and first client render; the stored choice loads after mount (no hydration mismatch).
  const [pref, setPref] = useState<ThemePref>("system");

  useEffect(() => {
    // Sync from localStorage once mounted; reading it during render would mismatch the server HTML.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPref(readPref());
  }, []);

  // While on "system", follow the device when it switches between light and dark.
  useEffect(() => {
    if (pref !== "system") return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => apply("system");
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [pref]);

  function choose(next: ThemePref) {
    setPref(next);
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // Storage blocked (private mode): the choice still applies for this page view.
    }
    apply(next);
  }

  return (
    <fieldset className="space-y-1.5">
      <legend className="text-xs font-semibold text-pdm-muted">Theme</legend>
      <div className="grid grid-cols-3 gap-1 rounded-full bg-pdm-canvas p-1 ring-1 ring-pdm-border">
        {OPTIONS.map((option) => (
          <label
            key={option.value}
            className="flex min-h-9 cursor-pointer items-center justify-center rounded-full text-xs font-semibold text-pdm-muted motion-safe:transition-colors has-[:checked]:bg-pdm-card has-[:checked]:text-pdm-primary has-[:checked]:shadow-sm has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-pdm-primary"
          >
            <input
              type="radio"
              name="theme"
              value={option.value}
              checked={pref === option.value}
              onChange={() => choose(option.value)}
              className="sr-only"
            />
            {option.label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}
