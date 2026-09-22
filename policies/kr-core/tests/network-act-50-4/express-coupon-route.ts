import express from "express";
import { db } from "./db";

const app = express();

app.get("/api/events/fall-sale", async (req, res) => {
  const coupons = await db.coupon.findMany({ where: { campaign: "fall-sale" } });
  res.send({ title: "가을 세일 이벤트", coupons });
});

app.listen(3000);
