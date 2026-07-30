/** Incremental parser for the `data` fields in an SSE byte stream. */
export class SseDataParser {
  private readonly decoder = new TextDecoder();
  private buffer = '';
  private dataLines: string[] = [];

  push(chunk: Uint8Array): string[] {
    return this.consume(this.decoder.decode(chunk, { stream: true }), false);
  }

  finish(): string[] {
    const events = this.consume(this.decoder.decode(), true);
    // The SSE specification discards an event that is not terminated by a
    // blank line when the stream ends.
    this.buffer = '';
    this.dataLines = [];
    return events;
  }

  private consume(text: string, endOfStream: boolean): string[] {
    this.buffer += text;
    const events: string[] = [];

    while (this.buffer.length > 0) {
      const newlineIndex = this.buffer.search(/[\r\n]/);
      if (newlineIndex < 0) break;

      const newline = this.buffer[newlineIndex];
      if (newline === '\r' && newlineIndex === this.buffer.length - 1 && !endOfStream) {
        break;
      }

      const delimiterLength = newline === '\r' && this.buffer[newlineIndex + 1] === '\n' ? 2 : 1;
      const line = this.buffer.slice(0, newlineIndex);
      this.buffer = this.buffer.slice(newlineIndex + delimiterLength);
      this.processLine(line, events);
    }

    if (endOfStream && this.buffer.length > 0) {
      this.processLine(this.buffer, events);
      this.buffer = '';
    }

    return events;
  }

  private processLine(line: string, events: string[]): void {
    if (line === '') {
      if (this.dataLines.length > 0) events.push(this.dataLines.join('\n'));
      this.dataLines = [];
      return;
    }

    if (line.startsWith(':')) return;
    const colonIndex = line.indexOf(':');
    const field = colonIndex < 0 ? line : line.slice(0, colonIndex);
    if (field !== 'data') return;

    let value = colonIndex < 0 ? '' : line.slice(colonIndex + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    this.dataLines.push(value);
  }
}

interface ByteStreamReader {
  read(): Promise<{ done: boolean; value?: Uint8Array }>;
}

export async function consumeJsonSseStream<T>(
  reader: ByteStreamReader,
  onEvent: (event: T) => void,
  isDone: (event: T) => boolean,
): Promise<void> {
  const parser = new SseDataParser();

  while (true) {
    const { done, value } = await reader.read();
    const payloads = value ? parser.push(value) : [];
    if (done) payloads.push(...parser.finish());

    for (const payload of payloads) {
      let event: T;
      try {
        event = JSON.parse(payload) as T;
      } catch (error) {
        throw new Error('Malformed JSON in SSE data event', { cause: error });
      }
      if (isDone(event)) return;
      onEvent(event);
    }

    if (done) throw new Error('SSE stream ended before the done event');
  }
}
