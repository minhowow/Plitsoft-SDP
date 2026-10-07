import { Injectable } from "@nestjs/common";
import { AlimtalkService } from "../kakao/alimtalk.service";
import { CustomerRepository } from "../customer/customer.repository";

@Injectable()
export class RevisitService {
  constructor(private readonly alimtalk: AlimtalkService, private readonly customers: CustomerRepository) {}

  async remindDormantCustomers() {
    const dormant = await this.customers.findDormant(90);
    for (const c of dormant) {
      await this.alimtalk.dispatch(c.phone, "REVISIT_01", { name: c.name, coupon: "10%" });
    }
  }
}
