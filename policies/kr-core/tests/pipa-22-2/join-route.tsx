import { useState } from "react";
import { api } from "./api";

export function MemberForm({ onDone }: { onDone: () => void }) {
  const [email, setEmail] = useState("");
  const [birthDate, setBirthDate] = useState("");

  async function submit() {
    await api.post("/members/join", { email, birthDate });
    onDone();
  }

  return (
    <form onSubmit={submit}>
      <input value={email} onChange={(e) => setEmail(e.target.value)} />
      <input type="date" value={birthDate} onChange={(e) => setBirthDate(e.target.value)} />
      <button>확인</button>
    </form>
  );
}
