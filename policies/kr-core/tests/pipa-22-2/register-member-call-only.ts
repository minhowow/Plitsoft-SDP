import { api } from "./api";

export async function submit(form) {
  const { email, birthDate } = form;
  return api.registerMember({ email, birthDate });
}
