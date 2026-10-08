export async function submit(form) {
  const { email, birthDate } = form;
  return joinMember({ email, birthDate });
}
