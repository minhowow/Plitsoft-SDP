router.post("/signup", async (req, res) => {
  const { email, dobYear, dobMonth, dobDay } = req.body;
  await Member.create({ email, dobYear, dobMonth, dobDay });
  res.status(201).end();
});
