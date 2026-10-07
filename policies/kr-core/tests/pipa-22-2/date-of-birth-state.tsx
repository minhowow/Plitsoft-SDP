import { useState } from "react";

export function SignupForm({ onDone }: { onDone: () => void }) {
  const [email, setEmail] = useState("");
  const [dateOfBirth, setDateOfBirth] = useState("");

  async function submit() {
    await fetch("/api/signup", { method: "POST", body: JSON.stringify({ email, dateOfBirth }) });
    onDone();
  }

  return (
    <form onSubmit={submit}>
      <input value={email} onChange={(e) => setEmail(e.target.value)} />
      <input type="date" value={dateOfBirth} onChange={(e) => setDateOfBirth(e.target.value)} />
      <button>가입하기</button>
    </form>
  );
}
