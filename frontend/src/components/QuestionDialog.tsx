import React, { useCallback, useRef, useState } from 'react';
import { Box, Text, useInput } from 'ink';
import TextInput from 'ink-text-input';
import { C } from '../theme.js';
import type { QuestionInfo, QuestionReply } from '../hooks/useApi.js';

interface QuestionDialogProps {
  question: QuestionInfo;
  onResponse: (reply: QuestionReply) => void;
}

export default React.memo(function QuestionDialog({
  question,
  onResponse,
}: QuestionDialogProps) {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [answer, setAnswer] = useState('');
  const onResponseRef = useRef(onResponse);
  onResponseRef.current = onResponse;
  const hasOptions = question.options.length > 0;

  useInput((input, key) => {
    if (key.escape) {
      onResponseRef.current({ cancelled: true });
      return;
    }
    if (!hasOptions) return;
    if (key.upArrow) {
      setSelectedIndex((index) => Math.max(0, index - 1));
      return;
    }
    if (key.downArrow) {
      setSelectedIndex((index) => Math.min(question.options.length - 1, index + 1));
      return;
    }
    if (key.return) {
      onResponseRef.current({ answer: question.options[selectedIndex].value });
      return;
    }
    const number = Number.parseInt(input, 10);
    if (Number.isInteger(number) && number >= 1 && number <= question.options.length) {
      onResponseRef.current({ answer: question.options[number - 1].value });
    }
  });

  const submitText = useCallback((value: string) => {
    onResponseRef.current({ answer: value });
  }, []);

  return (
    <Box flexDirection="column" borderStyle="round" borderColor={C.sky} paddingX={1} flexShrink={0}>
      <Box>
        <Text color={C.sky} bold>{'  '}{question.header || 'Question'}</Text>
        <Box flexGrow={1} />
        <Text color={C.overlay2}>esc cancel</Text>
      </Box>
      <Box><Text color={C.text}>{'  '}{question.question}</Text></Box>
      {hasOptions ? question.options.map((option, index) => {
        const selected = index === selectedIndex;
        return (
          <Box key={`${option.value}-${index}`}>
            <Text color={selected ? C.sky : C.subtext} bold={selected}>
              {selected ? ' > ' : '   '}{index + 1}. {option.label}
            </Text>
          </Box>
        );
      }) : (
        <Box>
          <Text color={C.sky}>{'> '}</Text>
          <TextInput
            value={answer}
            onChange={setAnswer}
            onSubmit={submitText}
            placeholder="Type your answer"
          />
        </Box>
      )}
      <Box>
        <Text color={C.overlay2}>
          {'  '}{hasOptions ? 'up/down select, enter confirm' : 'enter confirm'}
        </Text>
      </Box>
    </Box>
  );
});
