import { useState } from "react";
import { api } from "./api";

export default function SignupPage() {
  const [email, setEmail] = useState("");
  const [ymd, setYmd] = useState("");

  async function submit() {
    await api.post("/signup", { email, ymd });
  }

  return (
    <form onSubmit={submit}>
      <label>이메일</label>
      <input value={email} onChange={(e) => setEmail(e.target.value)} />
      <label>생년월일</label>
      <input type="date" value={ymd} onChange={(e) => setYmd(e.target.value)} />
      <button type="submit">가입하기</button>
    </form>
  );
}
