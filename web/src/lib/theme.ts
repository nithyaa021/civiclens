export type Theme = "light" | "dark";

const THEME_KEY = "civiclens.theme";

export function initialTheme(): Theme {
  try {
    const stored = window.localStorage.getItem(THEME_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    // Fall through to the OS preference.
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
  const meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
  if (meta) meta.content = theme === "dark" ? "#0d1417" : "#f4f6f6";
  try {
    window.localStorage.setItem(THEME_KEY, theme);
  } catch {
    // Theme still applies for this session.
  }
}
