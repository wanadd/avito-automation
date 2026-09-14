"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { browserApiBase } from "@/lib/client-api";

export function LoginForm() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage("Signing in...");
    const response = await fetch(`${browserApiBase()}/api/v1/auth/login`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password })
    });
    if (!response.ok) {
      setMessage("Invalid username or password");
      return;
    }
    setMessage("Signed in");
    router.push("/");
    router.refresh();
  }

  return (
    <form className="form" onSubmit={submit}>
      <label>
        Username
        <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" />
      </label>
      <label>
        Password
        <input value={password} onChange={(event) => setPassword(event.target.value)} type="password" autoComplete="current-password" />
      </label>
      <button className="button" type="submit">
        Login
      </button>
      {message ? <p className="muted">{message}</p> : null}
    </form>
  );
}
