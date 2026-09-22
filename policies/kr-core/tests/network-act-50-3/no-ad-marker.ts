export async function sendReceipt(order: Order) {
  await sms.send({ to: order.phone, text: `주문 ${order.id} 결제가 완료되었습니다` });
}
