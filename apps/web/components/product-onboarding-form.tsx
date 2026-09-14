"use client";

import { useState } from "react";
import { browserApiBase, csrfFromDocument } from "@/lib/client-api";

export function ProductOnboardingForm() {
  const [brand, setBrand] = useState("Samsung");
  const [name, setName] = useState("");
  const [modelCode, setModelCode] = useState("");
  const [storage, setStorage] = useState("256");
  const [condition, setCondition] = useState("NEW");
  const [alias, setAlias] = useState("");
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);

  async function submit() {
    setMessage("Creating...");
    const response = await fetch(`${browserApiBase()}/api/v1/onboarding/products`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfFromDocument()
      },
      body: JSON.stringify({
        product: { brand, canonical_name: name, category: "smartphone" },
        variant: {
          manufacturer_model_code: modelCode,
          storage_gb: Number(storage),
          condition: condition || null
        },
        aliases: alias ? [{ alias }] : [],
        actor: "web-operator"
      })
    });
    if (!response.ok) {
      setMessage(`Failed: ${response.status}`);
      return;
    }
    setResult((await response.json()) as Record<string, unknown>);
    setMessage("Created");
  }

  return (
    <div className="two">
      <section className="section">
        <h2>Product Master</h2>
        <div className="form">
          <input value={brand} onChange={(event) => setBrand(event.target.value)} placeholder="Brand" />
          <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Canonical name" />
          <input value={modelCode} onChange={(event) => setModelCode(event.target.value)} placeholder="Model code" />
          <input value={storage} onChange={(event) => setStorage(event.target.value)} placeholder="Storage GB" />
          <select value={condition} onChange={(event) => setCondition(event.target.value)}>
            <option value="">Unknown</option>
            <option value="NEW">NEW</option>
            <option value="USED">USED</option>
            <option value="REFURBISHED">REFURBISHED</option>
          </select>
          <input value={alias} onChange={(event) => setAlias(event.target.value)} placeholder="Alias or barcode" />
          <div className="inlineActions">
            <button className="button" type="button" onClick={submit}>Create</button>
            <span className="muted">{message}</span>
          </div>
        </div>
      </section>
      <section className="section">
        <h2>Result</h2>
        <pre className="code">{result ? JSON.stringify(result, null, 2) : "No result"}</pre>
      </section>
    </div>
  );
}
