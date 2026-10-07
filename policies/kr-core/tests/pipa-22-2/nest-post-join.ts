import { Body, Controller, Post } from "@nestjs/common";
import { UsersService } from "./users.service";

@Controller("members")
export class MembersController {
  constructor(private readonly users: UsersService) {}

  @Post("join")
  async join(@Body() body: { email: string; password: string; name: string; birth: string }) {
    const user = await this.users.create({
      email: body.email,
      password: body.password,
      name: body.name,
      birth: new Date(body.birth),
    });
    return { id: user.id };
  }
}
