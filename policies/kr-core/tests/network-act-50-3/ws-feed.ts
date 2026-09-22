import { WebSocketServer } from "ws";

const wss = new WebSocketServer({ port: 8080 });

wss.on("connection", (ws) => {
  const timer = setInterval(async () => {
    const posts = await loadFeed();
    ws.send(JSON.stringify(posts.map((p) => ({ ...p, badge: p.sponsored ? "(광고)" : null }))));
  }, 5000);
  ws.on("close", () => clearInterval(timer));
});
