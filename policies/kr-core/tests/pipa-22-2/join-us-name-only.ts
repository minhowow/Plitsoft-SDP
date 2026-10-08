export async function joinUs(form) {
  const { email, birthDate } = form;
  return db.members.insert({ email, birthDate });
}
