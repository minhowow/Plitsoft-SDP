// 프로필 화면. 가입과 상관없고, 아래 함수 하나가 문법 오류라 파일 일부가 파싱되지 않는다.
export function label({ nickname, birthday }) {
  return `${nickname} (${birthday})`;
}

export function broken(a: number) {
  const x = ;
  return a +* 2;
}
