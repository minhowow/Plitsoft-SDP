import { AiOutlineHome, AiOutlineUser, AiFillSetting } from "react-icons/ai";
import Link from "next/link";

export function BottomNav() {
  return (
    <nav className="bottom-nav">
      <Link href="/">
        <AiOutlineHome /> 홈
      </Link>
      <Link href="/me">
        <AiOutlineUser /> 내 정보
      </Link>
      <Link href="/settings">
        <AiFillSetting /> 설정
      </Link>
    </nav>
  );
}
