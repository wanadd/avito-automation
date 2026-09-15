"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { browserApiBase, csrfFromDocument } from "@/lib/client-api";

type Supplier = {
  id: string;
  code?: string;
  name?: string;
};

export function TelegramSourceMapForm({ sourceId, suppliers }: { sourceId: string; suppliers: Supplier[] }) {
  const [supplierId, setSupplierId] = useState(suppliers[0]?.id ?? "");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!supplierId || busy) {
      return;
    }
    setBusy(true);
    setMessage("Mapping...");
    try {
      const response = await fetch(`${browserApiBase()}/api/v1/telegram-prices/sources/${sourceId}/map`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfFromDocument()
        },
        body: JSON.stringify({ supplier_id: supplierId })
      });
      setMessage(response.ok ? "Mapped" : `Failed: ${response.status}`);
    } catch {
      setMessage("Network error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="inlineActions" onSubmit={submit}>
      <select aria-label="Supplier" value={supplierId} onChange={(event) => setSupplierId(event.target.value)} disabled={busy}>
        {suppliers.map((supplier) => (
          <option key={supplier.id} value={supplier.id}>
            {supplier.name ?? supplier.code ?? supplier.id}
          </option>
        ))}
      </select>
      <button className="button secondary" type="submit" disabled={busy || !supplierId}>Map</button>
      {message ? <span className="muted">{message}</span> : null}
    </form>
  );
}
