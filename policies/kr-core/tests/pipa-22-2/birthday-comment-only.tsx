import { useState } from "react";

// 기획 변경: birthday 입력은 가입에서 빼고 마이페이지로 옮겼다
export default function SignUp() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const submit = async () => {
    await fetch("/api/signup", { method: "POST", body: JSON.stringify({ email, password }) });
  };

  return (
    <form>
      <input value={email} onChange={(e) => setEmail(e.target.value)} />
      <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
      <button type="button" onClick={submit}>가입하기</button>
    </form>
  );
}
