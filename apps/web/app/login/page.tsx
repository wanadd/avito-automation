import { LoginForm } from "@/components/login-form";

export default function LoginPage() {
  return (
    <div className="stack">
      <div className="topbar">
        <h1>Operator Login</h1>
      </div>
      <section className="section">
        <LoginForm />
      </section>
    </div>
  );
}
