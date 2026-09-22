"use client";
import { useRouter } from "next/navigation";
import { sms } from "@/lib/sms";

export function BlastButton({ phones }: { phones: string[] }) {
  const router = useRouter();
  async function blast() {
    for (const to of phones) {
      await sms.send({ to, text: "(광고) 가나다몰 주말 특가 무료거부 080-123-4567" });
    }
    router.push("/admin/done");
  }
  return <button onClick={blast}>발송</button>;
}
