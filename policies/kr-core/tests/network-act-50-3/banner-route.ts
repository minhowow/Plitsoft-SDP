import express from "express";

const router = express.Router();

router.get("/api/banners", async (_req, res) => {
  const banners = await db.banner.findMany({ where: { active: true } });
  res.send(banners.map((b) => ({ id: b.id, label: b.sponsored ? "[광고]" : "", title: b.title, image: b.imageUrl })));
});

export default router;
