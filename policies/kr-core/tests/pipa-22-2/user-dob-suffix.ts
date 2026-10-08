router.post("/signup", async (req, res) => {
  const { email, userDob } = req.body;
  await Member.create({ email, user_dob: userDob });
  res.status(201).end();
});
