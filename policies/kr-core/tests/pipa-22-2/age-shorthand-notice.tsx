import { useState } from "react";

export function SignupPage() {
  const [email, setEmail] = useState("");
  const [age, setAge] = useState("");

  async function submit() {
    await fetch("/api/signup", { method: "POST", body: JSON.stringify({ email, age }) });
  }

  return (
    <form>
      <p>본 서비스는 만 14세 이상만 이용할 수 있습니다.</p>
      <input value={email} onChange={(e) => setEmail(e.target.value)} />
      <input type="number" value={age} onChange={(e) => setAge(e.target.value)} />
      <button type="button" onClick={submit}>가입하기</button>
    </form>
  );
}
