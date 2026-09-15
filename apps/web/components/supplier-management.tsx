"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { DataTable } from "@/components/data-table";
import { browserApiBase, csrfFromDocument } from "@/lib/client-api";

type SupplierRow = {
  id: string;
  name: string;
  code: string;
  offer_count?: number;
  in_stock_count?: number;
  errors?: number;
  updated_at?: string;
};

export function SupplierManagement({ initialRows, initialTotal }: { initialRows: SupplierRow[]; initialTotal: number }) {
  const [rows, setRows] = useState(initialRows);
  const [total, setTotal] = useState(initialTotal);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed || busy) {
      setMessage("Supplier name is required.");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(`${browserApiBase()}/api/v1/operator/suppliers`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfFromDocument()
        },
        body: JSON.stringify({ name: trimmed, is_active: isActive })
      });
      if (!response.ok) {
        setMessage(response.status === 409 ? "Supplier already exists." : "Supplier create failed.");
        return;
      }
      const created = await response.json() as SupplierRow;
      setRows([{ ...created, offer_count: 0, in_stock_count: 0, errors: 0 }, ...rows]);
      setTotal(total + 1);
      setName("");
      setIsActive(true);
      setShowForm(false);
      setMessage("Supplier created.");
    } catch {
      setMessage("Network error while creating supplier.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <div className="topbar">
        <h1>Suppliers</h1>
        <span className="muted">{total} suppliers</span>
      </div>
      <div className="inlineActions">
        <button className="button" type="button" onClick={() => setShowForm(true)}>Create supplier</button>
        {message ? <span className="muted">{message}</span> : null}
      </div>
      {showForm ? (
        <form className="section form" onSubmit={submit}>
          <h2>Create supplier</h2>
          <label>
            <span className="muted">Supplier name</span>
            <input value={name} onChange={(event) => setName(event.target.value)} disabled={busy} maxLength={255} autoFocus />
          </label>
          <label className="checkRow">
            <input type="checkbox" checked={isActive} onChange={(event) => setIsActive(event.target.checked)} disabled={busy} />
            <span>Active</span>
          </label>
          <div className="inlineActions">
            <button className="button" type="submit" disabled={busy}>{busy ? "Creating..." : "Create"}</button>
            <button className="button secondary" type="button" onClick={() => setShowForm(false)} disabled={busy}>Cancel</button>
          </div>
        </form>
      ) : null}
      <DataTable empty="No suppliers yet. Create the first supplier to map incoming supplier sources." rows={rows as unknown as Record<string, unknown>[]} columns={[
        { key: "name", label: "Supplier" },
        { key: "code", label: "Code" },
        { key: "offer_count", label: "Offers" },
        { key: "in_stock_count", label: "In stock" },
        { key: "errors", label: "Errors" },
        { key: "updated_at", label: "Updated", kind: "date" }
      ]} />
    </div>
  );
}
