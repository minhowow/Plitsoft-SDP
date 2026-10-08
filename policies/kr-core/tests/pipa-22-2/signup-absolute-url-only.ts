export function submit(email: string, birthDate: string) {
  return fetch("https://api.example.com/auth/signup", { method: "POST", body: JSON.stringify({ email, birthDate }) });
}
