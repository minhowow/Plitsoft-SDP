import { db } from "./db";

export const registerUser = async (form) => {
  const { email, birthDate } = form;
  return db.members.insert({ email, birthDate });
};
