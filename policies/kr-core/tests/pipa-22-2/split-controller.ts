import { Body, Controller, Post } from "@nestjs/common";
import { CreateUserDto } from "./dto/create-user.dto";
import { UsersService } from "./users.service";

@Controller("auth")
export class AuthController {
  constructor(private readonly users: UsersService) {}

  @Post("signup")
  signup(@Body() dto: CreateUserDto) {
    return this.users.create(dto);
  }
}
