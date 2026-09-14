"use client";

import { useState } from "react";
import { browserApiBase, csrfFromDocument } from "@/lib/client-api";
import { importSummary } from "@/lib/imports";

type Batch = {
  id: string;
  status: string;
  preview: Record<string, unknown>;
  result: Record<string, unknown>;
};

export function ImportWorkflow({ kind }: { kind: "telegram" | "onec" }) {
  const [sourceId, setSourceId] = useState("");
  const [mode, setMode] = useState("FULL");
  const [filename, setFilename] = useState(kind === "onec" ? "one_c_export.json" : "");
  const [content, setContent] = useState("");
  const [batch, setBatch] = useState<Batch | null>(null);
  const [message, setMessage] = useState("");

  async function post(path: string, body: Record<string, unknown>) {
    const response = await fetch(`${browserApiBase()}${path}`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfFromDocument()
      },
      body: JSON.stringify(body)
    });
    if (!response.ok) {
      throw new Error(`${response.status}`);
    }
    return (await response.json()) as Batch;
  }

  async function preview() {
    setMessage("Previewing...");
    try {
      const next =
        kind === "telegram"
          ? await post("/api/v1/onboarding/telegram/preview", {
              source_id: sourceId,
              raw_text: content,
              snapshot_type: mode,
              actor: "web-operator"
            })
          : await post("/api/v1/onboarding/1c/preview", {
              filename,
              content,
              mode,
              actor: "web-operator"
            });
      setBatch(next);
      setMessage("Preview ready");
    } catch (error) {
      setMessage(`Preview failed: ${(error as Error).message}`);
    }
  }

  async function confirm() {
    if (!batch) {
      return;
    }
    setMessage("Confirming...");
    try {
      const path = kind === "telegram" ? `/api/v1/onboarding/telegram/${batch.id}/confirm` : `/api/v1/onboarding/1c/${batch.id}/confirm`;
      const next = await post(path, { actor: "web-operator" });
      setBatch(next);
      setMessage("Confirmed");
    } catch (error) {
      setMessage(`Confirm failed: ${(error as Error).message}`);
    }
  }

  return (
    <div className="two">
      <section className="section">
        <h2>{kind === "telegram" ? "Telegram Price" : "1C Export"}</h2>
        <div className="form">
          {kind === "telegram" ? (
            <input value={sourceId} onChange={(event) => setSourceId(event.target.value)} placeholder="Source ID" />
          ) : (
            <input value={filename} onChange={(event) => setFilename(event.target.value)} placeholder="Filename" />
          )}
          <select value={mode} onChange={(event) => setMode(event.target.value)}>
            <option value="FULL">FULL</option>
            <option value="PARTIAL">PARTIAL</option>
          </select>
          <textarea value={content} onChange={(event) => setContent(event.target.value)} placeholder={kind === "telegram" ? "Paste Telegram price text" : "Paste JSON or CSV export"} />
          <div className="inlineActions">
            <button className="button" type="button" onClick={preview}>Preview</button>
            <button className="button secondary" type="button" onClick={confirm} disabled={!batch}>Confirm</button>
            <span className="muted">{message}</span>
          </div>
        </div>
      </section>
      <section className="section">
        <h2>Preview</h2>
        <p className="muted">{importSummary(batch?.preview)}</p>
        <pre className="code">{batch ? JSON.stringify(batch, null, 2) : "No batch"}</pre>
      </section>
    </div>
  );
}
