import { ImportWorkflow } from "@/components/import-workflow";

export default function TelegramImportPage() {
  return (
    <div className="stack">
      <div className="topbar">
        <h1>Telegram Import</h1>
        <span className="badge neutral">Preview then confirm</span>
      </div>
      <ImportWorkflow kind="telegram" />
    </div>
  );
}
