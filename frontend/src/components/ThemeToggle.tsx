import { Moon, Sun } from "lucide-react";

type Props = {
  theme: "light" | "dark";
  setTheme: (theme: "light" | "dark") => void;
};

export default function ThemeToggle({ theme, setTheme }: Props) {
  const isDark = theme === "dark";

  return (
    <button
      className="button-secondary h-10 px-3"
      type="button"
      onClick={() => setTheme(isDark ? "light" : "dark")}
      title={isDark ? "Use light theme" : "Use dark theme"}
    >
      {isDark ? <Sun size={17} /> : <Moon size={17} />}
      <span className="hidden sm:inline">{isDark ? "Light" : "Dark"}</span>
    </button>
  );
}
