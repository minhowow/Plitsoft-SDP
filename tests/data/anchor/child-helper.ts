function assertAdult(birthDate: string) {
  const age = calcAge(birthDate);
  if (age < 14) throw new Error("만 14세 미만");
}

export async function signUp(input: SignUpInput) {
  assertAdult(input.birthDate);
  await db.member.create({ data: { name: input.name, birthDate: input.birthDate } });
}
