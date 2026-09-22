router.post("/signup", async (req, res) => {
  const body = SignupSchema.parse(req.body);
  const domainAge = await lookupDomainAgeDays(body.email);
  if (domainAge < 14) {
    return res.status(400).json({ error: "DISPOSABLE_EMAIL" });
  }
  await prisma.user.create({ data: { email: body.email, birthDate: body.birthDate } });
  res.status(201).end();
});
