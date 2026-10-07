import { http } from "./http";

export type EmailRegisterForm = {
  email: string;
  password: string;
  birthDate: string;
};

export function registerByEmail(form: EmailRegisterForm) {
  return http.post("register/email", form);
}
