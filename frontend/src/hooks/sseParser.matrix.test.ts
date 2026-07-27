import { describe, expect, test } from 'vitest';
import { consumeJsonSseStream, SseDataParser } from './sseParser.js';

const encoder = new TextEncoder();

const EVENT_TYPES = [
  { type: 'token', text: 'hello' },
  { type: 'final', text: 'answer' },
  { type: 'reasoning', text: 'thinking...' },
  { type: 'tool_call', name: 'read', args: { path: 'x.ts' }, message_id: 't1' },
  { type: 'tool_result', result: 'ok', status: 'success', message_id: 't1' },
  { type: 'process', step: 'planning' },
  { type: 'status', memory_mb: 100 },
  { type: 'question_request', question_id: 'q1', question: 'Pick', options: [] },
  { type: 'approval_request', approval_id: 'a1', tool: 'write', risk: 'high' },
  { type: 'error', message: 'fail' },
  { type: 'done', status: 'succeeded' },
];

describe('SseDataParser event type matrix', () => {
  for (const event of EVENT_TYPES) {
    test(`parses ${event.type}`, () => {
      const parser = new SseDataParser();
      const json = JSON.stringify(event);
      const payloads = parser.push(encoder.encode(`data: ${json}\n\n`));
      expect(payloads.length).toBe(1);
      expect(JSON.parse(payloads[0])).toEqual(event);
    });
  }
});

describe('SseDataParser framing variants', () => {
  const framings = [
    { name: 'LF', bytes: 'data: hello\n\n' },
    { name: 'CRLF', bytes: 'data: hello\r\n\r\n' },
    { name: 'multi-data', bytes: 'data: line1\ndata: line2\n\n' },
    { name: 'comment', bytes: ': heartbeat\ndata: ok\n\n' },
    { name: 'space-after-colon', bytes: 'data: spaced\n\n' },
  ];

  const expectedPayload: Record<string, string> = {
    LF: 'hello',
    CRLF: 'hello',
    'multi-data': 'line1\nline2',
    comment: 'ok',
    'space-after-colon': 'spaced',
  };

  for (const { name, bytes } of framings) {
    test(name, () => {
      const parser = new SseDataParser();
      const payloads = parser.push(encoder.encode(bytes));
      expect(payloads).toEqual([expectedPayload[name]]);
    });
  }
});

describe('SseDataParser incremental delivery', () => {
  for (let chunkSize = 1; chunkSize <= 20; chunkSize += 3) {
    test(`chunkSize=${chunkSize}`, () => {
      const raw = 'data: {"type":"token","text":"x"}\n\n';
      const bytes = encoder.encode(raw);
      const parser = new SseDataParser();
      const all: string[] = [];
      for (let i = 0; i < bytes.length; i += chunkSize) {
        all.push(...parser.push(bytes.subarray(i, i + chunkSize)));
      }
      all.push(...parser.finish());
      expect(all.length).toBe(1);
      expect(JSON.parse(all[0]).type).toBe('token');
    });
  }
});

describe('SseDataParser UTF-8 boundaries', () => {
  const json = JSON.stringify({ type: 'token', text: '你好🙂' });
  const bytes = encoder.encode(`data: ${json}\n\n`);

  for (let boundary = 0; boundary <= bytes.length; boundary += 1) {
    test(`boundary=${boundary}`, () => {
      const parser = new SseDataParser();
      const events = [
        ...parser.push(bytes.subarray(0, boundary)),
        ...parser.push(bytes.subarray(boundary)),
        ...parser.finish(),
      ];
      expect(events).toEqual([json]);
    });
  }
});

describe('SseDataParser finish discards incomplete', () => {
  test('unterminated event', () => {
    const parser = new SseDataParser();
    expect(parser.push(encoder.encode('data: pending'))).toEqual([]);
    expect(parser.finish()).toEqual([]);
  });
});

const readerFrom = (chunks: string[]) => {
  const queue = chunks.map((chunk) => encoder.encode(chunk));
  return {
    read: async () => queue.length > 0
      ? { done: false, value: queue.shift()! }
      : { done: true as const },
  };
};

describe('consumeJsonSseStream event matrix', () => {
  for (const event of EVENT_TYPES.filter((e) => e.type !== 'done')) {
    test(`streams ${event.type}`, async () => {
      const collected: unknown[] = [];
      await consumeJsonSseStream(
        readerFrom([
          `data: ${JSON.stringify(event)}\n\n`,
          'data: {"type":"done"}\n\n',
        ]),
        (e) => collected.push(e),
        (e: { type: string }) => e.type === 'done',
      );
      expect(collected).toEqual([event]);
    });
  }
});

describe('consumeJsonSseStream error cases', () => {
  test('EOF before done', async () => {
    await expect(consumeJsonSseStream(
      readerFrom(['data: {"type":"token"}\n\n']),
      () => undefined,
      (e: { type: string }) => e.type === 'done',
    )).rejects.toThrow('ended before the done event');
  });

  test('malformed JSON', async () => {
    await expect(consumeJsonSseStream(
      readerFrom(['data: {bad}\n\n']),
      () => undefined,
      (e: { type: string }) => e.type === 'done',
    )).rejects.toThrow('Malformed JSON');
  });
});

describe('multiple events in one chunk', () => {
  const counts = [2, 3, 5, 10];
  for (const count of counts) {
    test(`${count} events`, () => {
      const parser = new SseDataParser();
      const payload = Array.from({ length: count }, (_, i) => `data: ev${i}\n\n`).join('');
      expect(parser.push(encoder.encode(payload)).length).toBe(count);
    });
  }
});
