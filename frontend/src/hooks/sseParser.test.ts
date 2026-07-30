import { describe, expect, test } from 'vitest';
import { consumeJsonSseStream, SseDataParser } from './sseParser.js';

const encoder = new TextEncoder();

describe('SseDataParser', () => {
  test('preserves one event across every possible UTF-8 byte boundary', () => {
    const json = JSON.stringify({ type: 'token', text: '你好, 🙂' });
    const bytes = encoder.encode(`data: ${json}\n\n`);

    for (let boundary = 0; boundary <= bytes.length; boundary += 1) {
      const parser = new SseDataParser();
      const events = [
        ...parser.push(bytes.subarray(0, boundary)),
        ...parser.push(bytes.subarray(boundary)),
        ...parser.finish(),
      ];
      expect(events, `boundary ${boundary}`).toEqual([json]);
    }
  });

  test('accepts CRLF framing and joins multiple data lines', () => {
    const parser = new SseDataParser();
    const bytes = encoder.encode('data: first\r\ndata: second\r\n\r\n');

    expect(parser.push(bytes.subarray(0, 13))).toEqual([]);
    expect(parser.push(bytes.subarray(13))).toEqual(['first\nsecond']);
    expect(parser.finish()).toEqual([]);
  });

  test('emits multiple events delivered in one chunk', () => {
    const parser = new SseDataParser();
    expect(parser.push(encoder.encode('data: one\n\ndata: two\n\n'))).toEqual(['one', 'two']);
  });

  test('preserves the independent question request contract', () => {
    const parser = new SseDataParser();
    const event = {
      type: 'question_request',
      question_id: 'q-123',
      question: 'Choose a target',
      header: 'Runtime',
      options: [{ label: 'Production', value: 'prod' }],
      input_type: 'choice',
    };
    const payloads = parser.push(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
    expect(payloads.map((payload) => JSON.parse(payload))).toEqual([event]);
  });

  test('ignores comments and discards an unterminated final event', () => {
    const parser = new SseDataParser();
    expect(parser.push(encoder.encode(': heartbeat\ndata: pending'))).toEqual([]);
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

describe('consumeJsonSseStream', () => {
  test('streams JSON events until an explicit done event', async () => {
    const events: Array<{ type: string; text?: string }> = [];
    await consumeJsonSseStream(
      readerFrom([
        'data: {"type":"token","text":"a"}\n\ndata: {"type":"fi',
        'nal","text":"answer"}\n\ndata: {"type":"done"}\n\n',
      ]),
      (event) => events.push(event),
      (event) => event.type === 'done',
    );
    expect(events).toEqual([
      { type: 'token', text: 'a' },
      { type: 'final', text: 'answer' },
    ]);
  });

  test('rejects EOF before the done event', async () => {
    await expect(consumeJsonSseStream(
      readerFrom(['data: {"type":"final","text":"partial"}\n\n']),
      () => undefined,
      (event: { type: string }) => event.type === 'done',
    )).rejects.toThrow('ended before the done event');
  });

  test('rejects malformed JSON instead of silently skipping it', async () => {
    await expect(consumeJsonSseStream(
      readerFrom(['data: {not-json}\n\n']),
      () => undefined,
      (event: { type: string }) => event.type === 'done',
    )).rejects.toThrow('Malformed JSON');
  });
});
