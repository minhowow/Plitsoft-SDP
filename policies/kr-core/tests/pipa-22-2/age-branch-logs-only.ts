router.post("/signup", async (req, res) => {
  const body = SignupSchema.parse(req.body);
  const age = getAge(body.birthDate);
  if (age < 14) {
    analytics.track("under14_signup", { age });
  }
  await prisma.user.create({ data: { email: body.email, birthDate: body.birthDate } });
  res.status(201).end();
});
