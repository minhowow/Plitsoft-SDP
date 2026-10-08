import { Member } from "./models";

export async function handleSignUp(req, res) {
  const { email, password, birthDate } = req.body;
  const member = await Member.create({ email, password, birthDate });
  res.status(201).json({ id: member.id });
}
