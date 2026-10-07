import { Injectable } from "@nestjs/common";
import { Cron } from "@nestjs/schedule";
import { SmsService } from "../sms/sms.service";
import { MemberRepository } from "../member/member.repository";

@Injectable()
export class DealScheduler {
  constructor(private readonly smsService: SmsService, private readonly members: MemberRepository) {}

  @Cron("0 0 10 * * *", { timeZone: "Asia/Seoul" })
  async sendMorningDeal() {
    const targets = await this.members.findSmsAgreed();
    for (const m of targets) {
      await this.smsService.send(m.phone, `(광고) 가나다몰 02-123-4567\n오늘의 추천 상품 20% 할인\n무료거부 080-123-4567`);
    }
  }
}
