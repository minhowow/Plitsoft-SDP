import { db } from "./db";

export async function signup(req, res) {
  const years = Number(req.body.age);
  await db.members.insert({ email: req.body.email, years });
  res.status(201).end();
}
