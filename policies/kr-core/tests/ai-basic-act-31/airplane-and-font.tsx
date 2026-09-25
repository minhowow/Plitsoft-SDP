// AI 와 아무 상관 없는 화면. 이름 신호가 헛짚기 쉬운 모양이다.
// (?i)\bai[a-z_]\w* 는 Airplane·aim 에, \bassistant\b 는
// 글꼴 이름 FONT_FAMILY.Assistant 와 메뉴 항목 "Word Assistant" 에 맞는다.
import { Airplane } from "./icons";

const FONT_FAMILY = { Assistant: "Assistant", Excalifont: "Excalifont" };
const menu = [{ name: "Word Assistant", url: "#" }];

export function TravelCard({ note }: { note: string }) {
  const aim = note.trim();
  return (
    <div style={{ fontFamily: FONT_FAMILY.Assistant }}>
      <Airplane />
      <p>{aim}</p>
      <ul>{menu.map((m) => <li key={m.name}>{m.name}</li>)}</ul>
    </div>
  );
}
