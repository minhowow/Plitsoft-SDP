import { useState } from "react";

export function SignupForm({ onDone }: { onDone: () => void }) {
  const [email, setEmail] = useState("");
  const [nickname, setNickname] = useState("");
  const [over14, setOver14] = useState(false);

  async function submit() {
    if (!over14) return;
    await fetch("/api/signup", { method: "POST", body: JSON.stringify({ email, nickname }) });
    onDone();
  }

  return (
    <form onSubmit={submit}>
      <input value={email} onChange={(e) => setEmail(e.target.value)} />
      <input value={nickname} onChange={(e) => setNickname(e.target.value)} />
      <label>
        <input type="checkbox" checked={over14} onChange={(e) => setOver14(e.target.checked)} />
        [필수] 만 14세 이상입니다
      </label>
      <button disabled={!over14}>가입하기</button>
    </form>
  );
}
