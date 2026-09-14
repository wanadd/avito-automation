import { ImportWorkflow } from "@/components/import-workflow";

export default function OneCImportPage() {
  return (
    <div className="stack">
      <div className="topbar">
        <h1>1C Import</h1>
        <span className="badge neutral">Dry-run preview</span>
      </div>
      <ImportWorkflow kind="onec" />
    </div>
  );
}
