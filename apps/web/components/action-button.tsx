"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { browserApiBase, csrfFromDocument } from "@/lib/client-api";

export function ActionButton({ path, label, confirmText, body }: { path: string; label: string; confirmText?: string; body?: Record<string, unknown> }) {
  const router = useRouter();
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function run() {
    if (busy) {
      return;
    }
    if (confirmText && !window.confirm(confirmText)) {
      return;
    }
    setBusy(true);
    setMessage("Working...");
    try {
      const response = await fetch(`${browserApiBase()}${path}`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfFromDocument()
        },
        body: JSON.stringify(body ?? { requested_by: "web-operator" })
      });
      if (response.ok) {
        setMessage("Done");
        router.refresh();
      } else {
        setMessage(`Failed: ${response.status}`);
      }
    } catch {
      setMessage("Network error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <span>
      <button className="button secondary" type="button" onClick={run} disabled={busy}>{label}</button>
      {message ? <span className="muted"> {message}</span> : null}
    </span>
  );
}
