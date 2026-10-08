export const breeds = ["doberman", "poodle"];

export function onRoom(socket, player) {
  if (player.rebirthCount < 1) return;
  socket.on("join", (id) => console.log(id));
}
