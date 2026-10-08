const API_URL = process.env.API_URL;

export function submit(email: string, birthDate: string) {
  return fetch(`${API_URL}/auth/signup`, { method: "POST", body: JSON.stringify({ email, birthDate }) });
}
