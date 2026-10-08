import { z } from "zod";
import { db } from "./db";

const SignupBody = z.object({
  email: z.string().email(),
  age: z.number().int(),
});

export async function signup(input: unknown) {
  const body = SignupBody.parse(input);
  return db.members.insert(body);
}
