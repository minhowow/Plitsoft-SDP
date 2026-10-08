import { db } from "./db";

export async function register(form) {
  const { email, birthDate } = form;
  return db.members.insert({ email, birthDate });
}
