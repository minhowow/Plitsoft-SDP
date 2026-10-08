import { db } from "./db";

export async function signup(form: FormData) {
  const email = String(form.get("email"));
  const years = Number(form.get("age"));
  return db.members.insert({ email, years });
}
