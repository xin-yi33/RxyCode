const { createServer } = require('node:net');

const server = createServer((socket) => {
  socket.once('data', () => {
    throw new Error('Injected PTY lifecycle failure');
  });
});

server.listen(0, '127.0.0.1', () => {
  const address = server.address();
  process.stdout.write(`RXYCODE_CRASH_PORT=${address.port}\n`);
});
