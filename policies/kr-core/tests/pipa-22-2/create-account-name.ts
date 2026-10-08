import { db } from "./db";

export async function createAccount(form) {
  const { email, birthDate } = form;
  return db.members.insert({ email, birthDate });
}
