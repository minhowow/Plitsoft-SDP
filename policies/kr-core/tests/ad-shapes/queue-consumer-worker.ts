import { Worker } from "bullmq";
import { SolapiMessageService } from "solapi";

const messageService = new SolapiMessageService(process.env.SOLAPI_KEY!, process.env.SOLAPI_SECRET!);

export const worker = new Worker(
  "sms",
  async (job) => {
    const { to, text } = job.data as { to: string; text: string };
    await messageService.send({ to, from: process.env.SENDER!, text });
  },
  { connection: { host: process.env.REDIS_HOST } },
);
