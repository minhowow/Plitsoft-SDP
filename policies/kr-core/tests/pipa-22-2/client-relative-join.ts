import ky from "ky";

const client = ky.create({ prefixUrl: "https://api.example.com/v1" });

type JoinBody = { email: string; password: string; birthday: string };

export const join = (body: JoinBody) => client.post("join", { json: body }).json<{ id: number }>();
