import { Process, Processor } from "@nestjs/bull";
import { Job } from "bull";
import { SmsService } from "../sms/sms.service";

@Processor("marketing")
export class MarketingProcessor {
  constructor(private readonly smsService: SmsService) {}

  @Process("send")
  async handle(job: Job<{ phone: string; message: string }>) {
    await this.smsService.send(job.data.phone, job.data.message);
  }
}
