import { useAppStore } from "./stores/appStore";

export type UiLanguage = "zh" | "en";

export function useLanguage() {
  const language = useAppStore((state) => state.language);
  const setLanguage = useAppStore((state) => state.setLanguage);
  const text = (zh: string, en: string) => (language === "zh" ? zh : en);
  return { language, setLanguage, text };
}

export function LanguageToggle({ compact = false }: { compact?: boolean }) {
  const { language, setLanguage } = useLanguage();
  return (
    <button
      className={`language-toggle ${compact ? "compact" : ""}`}
      type="button"
      onClick={() => setLanguage(language === "zh" ? "en" : "zh")}
      title={language === "zh" ? "Switch to English" : "切换到中文"}
      aria-label={language === "zh" ? "Switch to English" : "切换到中文"}
    >
      <span className={language === "zh" ? "active" : ""}>中</span>
      <span className={language === "en" ? "active" : ""}>EN</span>
    </button>
  );
}
