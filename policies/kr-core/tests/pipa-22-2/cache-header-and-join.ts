// 가입과 아무 상관 없는 코드. 두 적용 조건이 모두 헛짚기 쉬운 모양이다.
// `max-age` 의 age 와 배열의 .join() 은
// "생년월일을 받아 가입시키는 코드"의 신호가 아니다.
export function headers(locales: string[]) {
  return [
    {
      source: `/(${locales.join("|")})/:path*`,
      headers: [{ key: "Cache-Control", value: "public, max-age=31536000, immutable" }],
    },
  ];
}
