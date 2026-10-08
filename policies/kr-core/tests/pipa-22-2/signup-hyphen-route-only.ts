import { http } from "./http";

export function submit(email: string, birthDate: string) {
  return http.post("/auth/sign-up", { email, birthDate });
}
