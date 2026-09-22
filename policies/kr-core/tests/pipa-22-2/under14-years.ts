import { differenceInYears } from "date-fns";

router.post("/signup", async (req, res) => {
  const body = SignupSchema.parse(req.body);
  const years = differenceInYears(new Date(), body.birthDate);
  if (years < 14) {
    return res.status(403).json({ error: "UNDER_14" });
  }
  await prisma.user.create({ data: { email: body.email, birthDate: body.birthDate } });
  res.status(201).end();
});
