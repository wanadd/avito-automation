"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { browserApiBase } from "@/lib/client-api";

export function LoginForm() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isSubmitting) {
      return;
    }
    setIsSubmitting(true);
    setMessage("Signing in...");
    try {
      const response = await fetch(`${browserApiBase()}/api/v1/auth/login`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password })
      });
      if (response.status === 401 || response.status === 403) {
        setMessage("Invalid username or password");
        return;
      }
      if (!response.ok) {
        setMessage("Login service is unavailable. Try again.");
        return;
      }
      setMessage("Signed in");
      router.push("/");
      router.refresh();
    } catch {
      setMessage("Network error. Check your connection and try again.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <form className="form" onSubmit={submit}>
      <label>
        Username
        <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" disabled={isSubmitting} />
      </label>
      <label>
        Password
        <input value={password} onChange={(event) => setPassword(event.target.value)} type="password" autoComplete="current-password" disabled={isSubmitting} />
      </label>
      <button className="button" type="submit" disabled={isSubmitting}>
        {isSubmitting ? "Signing in..." : "Login"}
      </button>
      {message ? <p className="muted">{message}</p> : null}
    </form>
  );
}
