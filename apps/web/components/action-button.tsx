"use client";

import { useState } from "react";
import { browserApiBase, csrfFromDocument } from "@/lib/client-api";

export function ActionButton({ path, label, confirmText, body }: { path: string; label: string; confirmText?: string; body?: Record<string, unknown> }) {
  const [message, setMessage] = useState("");

  async function run() {
    if (confirmText && !window.confirm(confirmText)) {
      return;
    }
    setMessage("Working...");
    const response = await fetch(`${browserApiBase()}${path}`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfFromDocument()
      },
      body: JSON.stringify(body ?? { requested_by: "web-operator" })
    });
    setMessage(response.ok ? "Done" : `Failed: ${response.status}`);
  }

  return (
    <span>
      <button className="button secondary" type="button" onClick={run}>{label}</button>
      {message ? <span className="muted"> {message}</span> : null}
    </span>
  );
}
