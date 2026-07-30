import React, { useState, useCallback, useRef } from 'react';
import { Box, Text, useInput, useStdout } from 'ink';
import TextInput from 'ink-text-input';
import { C } from '../theme.js';

export type AddModelStep = 'provider_model_id' | 'api_key' | 'api_url' | 'nickname';

interface Props {
  step: AddModelStep;
  data: Record<string, string>;
  error?: string;
  onSubmit: (text: string) => void; // commit the current step's text
  onCancel: () => void;
}

interface StepMeta {
  title: string;
  placeholder: string;
  hint: string;
  field: 'providerModelId' | 'apiKey' | 'apiUrl' | 'nickname';
  label: string;
}

const STEPS: AddModelStep[] = ['provider_model_id', 'api_key', 'api_url', 'nickname'];

const META: Record<AddModelStep, StepMeta> = {
  provider_model_id: { title: '[1/4] Provider model ID', placeholder: 'e.g. deepseek-chat', hint: 'The exact model ID expected by the provider API', field: 'providerModelId', label: 'Provider ID' },
  api_key: { title: '[2/4] API Key', placeholder: 'sk-...', hint: '密钥本地仅回显掩码', field: 'apiKey', label: 'Key' },
  api_url: { title: '[3/4] API URL', placeholder: 'https://api.deepseek.com', hint: '携带密钥的连接必须使用 HTTPS', field: 'apiUrl', label: 'URL' },
  nickname: { title: '[4/4] 昵称（可选）', placeholder: '留空则等于模型名', hint: '回车跳过', field: 'nickname', label: '昵称' },
};

const mask = (s: AddModelStep, v: string): string => {
  if (s === 'api_key') return v.length > 8 ? v.slice(0, 4) + '...' + v.slice(-4) : '****';
  return v;
};

/**
 * Bottom-anchored wizard shown when the user runs `/addmodel` with no args.
 * Replaces the normal InputBox (so there is never a second box) and walks the
 * user through the 4 fields one at a time, exactly like opencode's add-model
 * popup — instead of dumping step prompts into the chat area.
 */
export default React.memo(function AddModelWizard({ step, data, error, onSubmit, onCancel }: Props) {
  const [input, setInput] = useState('');
  const { stdout } = useStdout();
  const termWidth = stdout?.columns ?? 80;
  const innerW = Math.max(10, termWidth - 4);
  const meta = META[step];

  const collected = STEPS.filter(s => s !== step && data[META[s].field]).map(s => ({
    step: s,
    value: data[META[s].field]!,
  }));

  const handleChange = useCallback((v: string) => setInput(v), []);
  const handleSubmit = useCallback((v: string) => { onSubmit(v); setInput(''); }, [onSubmit]);

  const onSubmitRef = useRef(onSubmit);
  onSubmitRef.current = onSubmit;
  const onCancelRef = useRef(onCancel);
  onCancelRef.current = onCancel;
  useInput((_ch, key) => {
    if (key.escape) { onCancelRef.current(); }
  });

  return (
    <Box flexDirection="column">
      <Box flexDirection="column" borderStyle="round" borderColor={C.primary} paddingX={1}>
        <Box>
          <Text color={C.primary} bold>{'  '}添加模型</Text>
          <Box flexGrow={1} />
          <Text color={C.overlay2}>esc 取消</Text>
        </Box>
        <Box><Text color={C.borderDim}>{' '.repeat(innerW)}</Text></Box>
        {collected.map(c => (
          <Box key={c.step}>
            <Text color={C.green}>{'  '}\u2713 {META[c.step].label}: {mask(c.step, c.value)}</Text>
          </Box>
        ))}
        {error ? (
          <Box><Text color={C.accent}>{'  '}\u26A0 {error}</Text></Box>
        ) : null}
        <Box marginY={1}>
          <Text color={C.yellow} bold>{'  '}{meta.title}</Text>
        </Box>
        <Box>
          <Text color={C.primary}>{'> '}</Text>
          <Box flexGrow={1}>
            <TextInput
              value={input}
              onChange={handleChange}
              onSubmit={handleSubmit}
              placeholder={meta.placeholder}
              mask={step === 'api_key' ? '*' : undefined}
            />
          </Box>
        </Box>
        <Box><Text color={C.overlay2}>{'  '}{meta.hint}</Text></Box>
      </Box>
    </Box>
  );
});
