import { Router } from "express";
import { db } from "./db";

export const router = Router();

router.post("/api/users", async (req, res) => {
  const { email, password, birthDate } = req.body;
  const user = await db.user.create({ data: { email, password, birthDate } });
  res.status(201).json({ id: user.id });
});
