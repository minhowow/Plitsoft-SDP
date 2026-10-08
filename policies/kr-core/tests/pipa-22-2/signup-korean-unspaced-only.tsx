import { useState } from "react";

export default function Page() {
  const [email, setEmail] = useState("");
  const [birthDate, setBirthDate] = useState("");
  return (
    <form>
      <h1>회원가입</h1>
      <input value={email} onChange={(e) => setEmail(e.target.value)} />
      <input type="date" value={birthDate} onChange={(e) => setBirthDate(e.target.value)} />
      <button type="submit">확인</button>
    </form>
  );
}
