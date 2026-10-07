import { Injectable } from "@nestjs/common";
import { SmsService } from "../sms/sms.service";
import { MemberRepository } from "../member/member.repository";

@Injectable()
export class SaleNoticeService {
  constructor(private readonly smsService: SmsService, private readonly members: MemberRepository) {}

  async sendWeekendSale(title: string) {
    const targets = await this.members.findSmsAgreed();
    for (const m of targets) {
      await this.smsService.send({ to: m.phone, text: `(광고) ${title}` });
    }
  }
}
