"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { useRouter } from "next/navigation";
import { browserApiBase, csrfFromDocument } from "@/lib/client-api";

type Supplier = {
  id: string;
  code?: string;
  name?: string;
};

export function TelegramSourceMapForm({
  sourceId,
  suppliers,
  suggestedName,
  pendingBatchIds = []
}: {
  sourceId: string;
  suppliers: Supplier[];
  suggestedName?: string | null;
  pendingBatchIds?: string[];
}) {
  const router = useRouter();
  const [localSuppliers, setLocalSuppliers] = useState(suppliers);
  const [supplierId, setSupplierId] = useState(suppliers[0]?.id ?? "");
  const [showCreate, setShowCreate] = useState(suppliers.length === 0);
  const [supplierName, setSupplierName] = useState(suggestedName ?? "");
  const [mapped, setMapped] = useState(false);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function createSupplier() {
    const trimmed = supplierName.trim();
    if (!trimmed || busy) {
      setMessage("Supplier name is required.");
      return;
    }
    setBusy(true);
    setMessage("Creating supplier...");
    try {
      const response = await fetch(`${browserApiBase()}/api/v1/operator/suppliers`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfFromDocument()
        },
        body: JSON.stringify({ name: trimmed, is_active: true })
      });
      if (!response.ok) {
        setMessage(response.status === 409 ? "Supplier already exists." : "Supplier create failed.");
        return;
      }
      const created = await response.json() as Supplier;
      setLocalSuppliers([...localSuppliers, created]);
      setSupplierId(created.id);
      setShowCreate(false);
      setMessage("Supplier created. Confirm mapping when ready.");
      router.refresh();
    } catch {
      setMessage("Network error while creating supplier.");
    } finally {
      setBusy(false);
    }
  }

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
      if (response.ok) {
        setMapped(true);
        setMessage("Mapped. Reprocess saved pending batch when ready.");
        router.refresh();
      } else {
        setMessage(`Mapping failed: ${response.status}`);
      }
    } catch {
      setMessage("Network error while mapping source.");
    } finally {
      setBusy(false);
    }
  }

  async function reprocess(batchId: string) {
    if (busy) {
      return;
    }
    setBusy(true);
    setMessage("Reprocessing...");
    try {
      const response = await fetch(`${browserApiBase()}/api/v1/telegram-prices/ingestions/${batchId}/reprocess`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfFromDocument()
        },
        body: JSON.stringify({})
      });
      if (response.ok) {
        setMessage("Reprocess completed. Updating counters...");
        router.refresh();
      } else {
        setMessage(`Reprocess failed: ${response.status}`);
      }
    } catch {
      setMessage("Network error while reprocessing batch.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="inlineActions" onSubmit={submit}>
      {localSuppliers.length > 0 ? (
        <select aria-label="Supplier" value={supplierId} onChange={(event) => setSupplierId(event.target.value)} disabled={busy}>
          {localSuppliers.map((supplier) => (
            <option key={supplier.id} value={supplier.id}>
              {supplier.name ?? supplier.code ?? supplier.id}
            </option>
          ))}
        </select>
      ) : <span className="muted">No suppliers yet</span>}
      <button className="button secondary" type="button" onClick={() => setShowCreate(!showCreate)} disabled={busy}>
        Create supplier
      </button>
      <button className="button secondary" type="submit" disabled={busy || !supplierId}>Map</button>
      {showCreate ? (
        <span className="inlineActions">
          <input aria-label="Supplier name" value={supplierName} onChange={(event) => setSupplierName(event.target.value)} disabled={busy} maxLength={255} />
          <button className="button secondary" type="button" onClick={createSupplier} disabled={busy}>Create</button>
          <button className="button secondary" type="button" onClick={() => setShowCreate(false)} disabled={busy}>Cancel</button>
        </span>
      ) : null}
      {mapped ? pendingBatchIds.map((batchId) => (
        <button key={batchId} className="button secondary" type="button" onClick={() => reprocess(batchId)} disabled={busy}>
          Reprocess
        </button>
      )) : null}
      {message ? <span className="muted">{message}</span> : null}
    </form>
  );
}
