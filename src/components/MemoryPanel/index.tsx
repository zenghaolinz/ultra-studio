import { useLanguage } from "../../i18n";

export default function MemoryPanel() {
  const { text } = useLanguage();
  return (
    <div style={{ padding: "16px 20px", textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>
      {text("记忆由 AI 自主管理 · 对话中 AI 会自动检索和保存记忆", "Memory is managed by AI · The assistant automatically retrieves and saves memory during chats")}
    </div>
  );
}
