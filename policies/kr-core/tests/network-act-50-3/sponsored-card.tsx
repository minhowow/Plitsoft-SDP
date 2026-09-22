"use client";
import { useRouter } from "next/navigation";

export function SponsoredCard({ item }: { item: { id: string; title: string; image: string } }) {
  const router = useRouter();
  return (
    <div className="card" onClick={() => router.push(`/products/${item.id}`)}>
      <span className="badge">(광고)</span>
      <img src={item.image} alt={item.title} />
      <p>{item.title}</p>
    </div>
  );
}
