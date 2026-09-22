router.post("/signup", async (req, res) => {
  const body = SignupSchema.parse(req.body);
  await verifyGuardianConsent(body.birthDate, body.guardianToken);
  await prisma.user.create({ data: { email: body.email, birthDate: body.birthDate } });
  res.status(201).end();
});
