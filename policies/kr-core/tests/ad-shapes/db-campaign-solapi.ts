import { SolapiMessageService } from "solapi";
import { prisma } from "../db";

const messageService = new SolapiMessageService(process.env.SOLAPI_KEY!, process.env.SOLAPI_SECRET!);

export async function dispatchCampaign(campaignId: string) {
  const campaign = await prisma.campaign.findUniqueOrThrow({ where: { id: campaignId } });
  const members = await prisma.member.findMany({ where: { smsAgreed: true } });
  for (const m of members) {
    await messageService.send({ to: m.phone, from: process.env.SENDER!, text: campaign.body });
  }
  await prisma.campaign.update({ where: { id: campaignId }, data: { sentAt: new Date() } });
}
