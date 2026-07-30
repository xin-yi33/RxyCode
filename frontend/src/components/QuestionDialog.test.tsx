import React from 'react';
import { render } from 'ink-testing-library';
import { describe, expect, it, vi } from 'vitest';
import QuestionDialog from './QuestionDialog.js';

const settle = () => new Promise((resolve) => setTimeout(resolve, 40));

describe('QuestionDialog', () => {
  it('submits the selected option value instead of an approval decision', async () => {
    const onResponse = vi.fn();
    const { stdin, lastFrame } = render(
      <QuestionDialog
        question={{
          questionId: 'q1',
          header: 'Runtime',
          question: 'Choose a target',
          options: [
            { label: 'Development', value: 'dev' },
            { label: 'Production', value: 'prod' },
          ],
        }}
        onResponse={onResponse}
      />,
    );
    expect(lastFrame()).toContain('Choose a target');
    await settle();
    stdin.write('\x1b[B');
    await settle();
    stdin.write('\r');
    await settle();
    expect(onResponse).toHaveBeenCalledWith({ answer: 'prod' });
    expect(onResponse).not.toHaveBeenCalledWith({ answer: 'approved' });
  });

  it('submits free text unchanged', async () => {
    const onResponse = vi.fn();
    const { stdin } = render(
      <QuestionDialog
        question={{
          questionId: 'q2',
          header: '',
          question: 'Name this release',
          options: [],
        }}
        onResponse={onResponse}
      />,
    );
    await settle();
    stdin.write('summer release');
    await settle();
    stdin.write('\r');
    await settle();
    expect(onResponse).toHaveBeenCalledWith({ answer: 'summer release' });
  });

  it('sends an explicit cancellation on escape', async () => {
    const onResponse = vi.fn();
    const { stdin } = render(
      <QuestionDialog
        question={{
          questionId: 'q3',
          header: '',
          question: 'Continue?',
          options: [{ label: 'Yes', value: 'yes' }],
        }}
        onResponse={onResponse}
      />,
    );
    await settle();
    stdin.write('\x1b');
    await settle();
    expect(onResponse).toHaveBeenCalledWith({ cancelled: true });
  });
});
