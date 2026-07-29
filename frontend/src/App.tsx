import React, { useEffect, useCallback, useState, useRef, useMemo } from 'react';
import { Box, Text, useApp, useInput, useStdout } from 'ink';
import ChatPanel from './components/ChatPanel.js';
import InputBox from './components/InputBox.js';
import AddModelWizard, { type AddModelStep } from './components/AddModelWizard.js';
import StatusBar from './components/StatusBar.js';
import ProgressBanner from './components/ProgressBanner.js';
import Modal, { type ModalItem } from './components/Modal.js';
import ApprovalDialog from './components/ApprovalDialog.js';
import QuestionDialog from './components/QuestionDialog.js';
import { useApi } from './hooks/useApi.js';
import { useMode } from './hooks/useMode.js';
import type { Mode } from './types.js';
import { MODE_COLORS } from './types.js';
import { C } from './theme.js';
import { MouseProvider, mouseManager } from './mouse.js';
import { logInfo, logDebug } from './log.js';
import { paletteHeight } from './layout.js';
import { safeCommandLabel } from './apiClient.js';
import { isChatLoadedResponse, mapLoadedChatMessages } from './chatHistory.js';
import { decideModelSetup } from './modelSetup.js';
import { probeModels } from './fetchModelsProbe.js';

type ModalType = null | 'session' | 'model' | 'memory' | 'skill' | 'mcp' | 'queue' | 'schedule';

const Header = React.memo(({ mode, model, expandThinking, isStreaming }: { mode: Mode; model: string; expandThinking: boolean; isStreaming: boolean }) => {
  const modeColor = MODE_COLORS[mode];
  return (
    <Box paddingX={1} flexShrink={0}>
        <Text color="#FFB6C1" bold>{"  "}RxyCode v1.2.2</Text>
      <Text color="#555"> {" \u00B7 "} </Text>
      <Text color={modeColor} bold>{mode}</Text>
      <Text color="#555"> {" \u00B7 "} </Text>
      <Text color="#FF69B4">{model}</Text>
      {isStreaming && expandThinking && <Text color="#FFD700"> {" \u00B7 \u601D\u8003\u4E2D"} </Text>}
    </Box>
  );
});

export default function App({ terminateProcess }: { terminateProcess?: () => void } = {}) {
  const { exit } = useApp();
  const { stdout } = useStdout();

  const { mode, setMode, cycleMode } = useMode();
  const { messages, status, isStreaming, sendMessage, sendCommand, addModel, fetchStatus, cancelRequest, addMessage, setMessages, pendingApproval, respondApproval, pendingQuestion, respondQuestion } = useApi();
  const [showCommandPalette, setShowCommandPalette] = useState(false);

  const exitApplication = useCallback(() => {
    terminateProcess?.();
    exit();
  }, [exit, terminateProcess]);
  // 问题5/6 修复: thinking is OFF by default, matching the backend gate
  // (StreamTUI._expand_thinking defaults to False, so reasoning events are not
  // even sent over SSE until the user opts in). Ctrl+T / /thinking toggles the
  // local panel AND the backend gate together, keeping both sides in sync —
  // gemini-cli likewise keeps full thoughts opt-in rather than streaming them
  // into the transcript.
  const [expandThinking, setExpandThinking] = useState(false);
  const thinkingTogglePendingRef = useRef(false);
  const [addmodelState, setAddmodelState] = useState<{ step: AddModelStep; data: Record<string, string> } | null>(null);
  const [addmodelError, setAddmodelError] = useState('');
  const [needsModelSetup, setNeedsModelSetup] = useState(false);
  const autoOpenedModelSetupRef = useRef(false);
  const [streamStartedAt, setStreamStartedAt] = useState<number | null>(null);
  const [clearKey, setClearKey] = useState(0);

  // 弹窗系统
  const [activeModal, setActiveModal] = useState<ModalType>(null);
  const [modalItems, setModalItems] = useState<ModalItem[]>([]);
  const [modalIdx, setModalIdx] = useState(0);

  const terminalHeight = stdout?.rows ?? 40;
  // Reserve room for the bottom-anchored input/palette so the layout never
  // overflows (overflow breaks the mouse coordinate math). The command palette
  // is the tallest possible bottom element, so size ChatPanel against it.
  const ph = paletteHeight(terminalHeight);
  const inputReserve = showCommandPalette ? ph : 3;
  const chatHeight = useMemo(
    () => Math.max(6, terminalHeight - inputReserve - 2),
    [terminalHeight, inputReserve],
  );
  useEffect(() => {
    logInfo('App mounted', { cols: stdout?.columns, rows: stdout?.rows });
    fetchStatus();
    const iv = setInterval(fetchStatus, 30000);
    return () => { clearInterval(iv); };
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      for (let i = 0; i < 10 && !cancelled; i++) {
        const probe = await probeModels();
        if (cancelled) return;
        if (!probe.ok) {
          await new Promise((r) => setTimeout(r, 200));
          continue;
        }
        const decision = decideModelSetup({
          fetchOk: true,
          modelCount: probe.models.length,
          alreadyAutoOpened: autoOpenedModelSetupRef.current,
        });
        setNeedsModelSetup(decision.needsSetup);
        if (decision.shouldAutoOpen) {
          autoOpenedModelSetupRef.current = true;
          setAddmodelState({ step: 'provider_model_id', data: {} });
          setAddmodelError('');
        }
        return;
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (isStreaming && streamStartedAt === null) { setStreamStartedAt(Date.now()); }
    else if (!isStreaming && streamStartedAt !== null) { setStreamStartedAt(null); }
  }, [isStreaming, streamStartedAt]);

  // 弹窗对应的 accent 颜色
  const modalAccent: Record<NonNullable<ModalType>, string> = {
    session: C.mauve,
    model: C.primary,
    memory: C.green,
    skill: C.yellow,
    mcp: C.teal,
    queue: C.sky,
    schedule: C.accent,
  };

  const modalTitle: Record<NonNullable<ModalType>, string> = {
    session: 'Session',
    model: 'Select Model',
    memory: 'Memory',
    skill: 'Skills',
    mcp: 'MCP Servers',
    queue: 'Task Queue',
    schedule: 'Schedule',
  };

  // 打开弹窗的通用方法
  const openModal = useCallback(async (type: NonNullable<ModalType>, cmd: string) => {
    const result = await sendCommand(cmd);
    if (!result) { addMessage({ role: 'system', content: 'Failed to fetch data.' }); return; }

    // 根据返回数据类型构建 items
    let items: ModalItem[] = [];
    if (type === 'session') {
      const chats = (result as any).chats || [];
      items = chats.map((c: any) => ({ id: c.name, label: c.name, desc: c.time ? String(c.time) : (c.preview || '') }));
    } else if (type === 'model') {
      const models = (result as any).models || [];
      const activeModel = status?.model || '';
      items = models.map((m: any) => ({
        id: m.id || m.name,
        label: m.name || m.id,
        desc: (m.id || m.name) === activeModel ? '(current)' : '',
      }));
    } else if (type === 'memory') {
      const memories = (result as any).memories || [];
      items = memories.map((m: any) => ({ id: String(m.id), label: `[${m.id}]`, desc: m.text }));
    } else if (type === 'skill') {
      const skills = (result as any).skills || [];
      items = skills.map((s: any) => ({ id: s.name || s.id, label: s.name || s.id, desc: s.description || '' }));
    } else if (type === 'mcp') {
      const mcps = (result as any).servers || (result as any).mcps || [];
      items = mcps.map((m: any) => ({ id: m.name, label: m.name, desc: m.command || '' }));
    } else if (type === 'queue') {
      const tasks = (result as any).tasks || [];
      items = tasks.map((t: any) => ({ id: t.id, label: `[${t.id}]`, desc: t.prompt }));
    } else if (type === 'schedule') {
      const tasks = (result as any).tasks || [];
      items = tasks.map((t: any) => ({ id: t.id, label: `[${t.id}]`, desc: t.prompt }));
    }

    if (items.length === 0) {
      addMessage({ role: 'system', content: 'No items found.' });
      return;
    }
    setModalItems(items);
    setModalIdx(0);
    setActiveModal(type);
  }, [sendCommand, addMessage, status?.model]);

  const handleSubmit = useCallback(async (text: string) => {
    logDebug('User submit', { len: text.length, is_command: text.startsWith('/') });
    await sendMessage(text, mode);
  }, [sendMessage, mode]);

  const toggleThinking = useCallback(async () => {
    if (thinkingTogglePendingRef.current) return;
    thinkingTogglePendingRef.current = true;
    try {
      const result = await sendCommand('/thinking');
      if (result && typeof result.expanded === 'boolean') {
        setExpandThinking(result.expanded);
      }
    } finally {
      thinkingTogglePendingRef.current = false;
    }
  }, [sendCommand]);

  useInput((input, key) => {
    const code = input ? input.charCodeAt(0) : -1;
    if (key.ctrl && (input.toLowerCase() === 't' || code === 20)) {
      void toggleThinking();
    }
  });

  const replaceLoadedChat = useCallback((result: unknown): boolean => {
    if (!isChatLoadedResponse(result)) return false;
    setMessages(mapLoadedChatMessages(result.messages));
    // ChatPanel uses Ink Static internally; remount it so a replacement history
    // cannot retain committed rows from the previously displayed conversation.
    setClearKey(k => k + 1);
    return true;
  }, [setMessages]);

  // `/addmodel` 向导逐步收集字段，最后通过 typed onboarding API 提交。
  // 与旧逻辑不同，这里不再把步骤提示塞进聊天区，而是完全由 AddModelWizard 弹窗承载。
  const handleWizardSubmit = useCallback(async (text: string) => {
    if (!addmodelState) return;
    const step = addmodelState.step;
    const data = { ...addmodelState.data };
    setAddmodelError('');
    if (step === 'provider_model_id') {
      data.providerModelId = text.trim();
      setAddmodelState({ step: 'api_key', data });
      return;
    }
    if (step === 'api_key') {
      data.apiKey = text.trim();
      setAddmodelState({ step: 'api_url', data });
      return;
    }
    if (step === 'api_url') {
      const url = text.trim().replace(/\/+$/, '');
      if (!/^https:\/\//i.test(url)) {
        setAddmodelError('API URL 必须使用 https://，请重新输入');
        return;
      }
      data.apiUrl = url;
      setAddmodelState({ step: 'nickname', data });
      return;
    }
    // nickname（最后一步）
    const nickname = text.trim() || data.providerModelId;
    setAddmodelState(null);
    setAddmodelError('');
    addMessage({ role: 'system', content: '\u2714 Adding model ' + nickname + '...' });
    const result = await addModel({
      providerModelId: data.providerModelId,
      apiKey: data.apiKey,
      baseUrl: data.apiUrl,
      nickname,
    });
    if (result?.message) { addMessage({ role: 'system', content: result.message }); }
    if (result && result.action !== 'error') {
      const probe = await probeModels();
      if (probe.ok) setNeedsModelSetup(probe.models.length === 0);
    }
  }, [addmodelState, setAddmodelState, setAddmodelError, addModel, addMessage]);

  const handleCommand = useCallback(async (cmd: string) => {
    const trimmed = cmd.trim();
    logDebug('Command executed', { command: safeCommandLabel(trimmed) });
    if (addmodelState && trimmed.toLowerCase() === '/cancel') { setAddmodelState(null); addMessage({ role: 'system', content: 'Add model cancelled.' }); return; }
    if (trimmed === '/exit') { exitApplication(); return; }
    if (trimmed === '/clear') {
      const result = await sendCommand(trimmed);
      if (!result) return;
      setMessages([]);
      setClearKey(k => k + 1);
      addMessage({ role: 'system', content: result.message || '\u4E0A\u4E0B\u6587\u5DF2\u6E05\u9664' });
      return;
    }
    if (trimmed === '/load-chat') {
      openModal('session', trimmed);
      return;
    }
    if (trimmed.startsWith('/load-chat ')) {
      const result = await sendCommand(trimmed);
      if (!replaceLoadedChat(result) && result?.message) {
        addMessage({ role: 'system', content: result.message });
      }
      return;
    }
    if (trimmed.startsWith('/addmodel')) {
      // 无参：打开可视化向导弹窗（替代旧版把步骤提示塞进聊天区的行为）
      if (trimmed.trim() === '/addmodel') { setAddmodelState({ step: 'provider_model_id', data: {} }); setAddmodelError(''); return; }
      // 带参：直接执行一站式添加
      addMessage({ role: 'system', content: 'Run /addmodel without arguments and use the secure wizard.' });
      return;
    }
    if (trimmed === '/thinking') { await toggleThinking(); return; }
    // 命令面板 action 直达弹窗（__action:<type>）：session / model / memory /
    // skill / mcp / queue / schedule。命令面板选中带 action 的命令时会发送
    // `__action:<type>`，必须在这里映射到对应弹窗，否则从面板打开这些命令
    // 不会弹窗（例如 /session 的 action 是 'session'，旧逻辑只认 '/session'）。
    if (trimmed.startsWith('__action:')) {
      const type = trimmed.slice('__action:'.length);
      const actionCmd: Record<string, string> = {
        model: '/models', session: '/session', memory: '/memory list',
        skill: '/list-skills', mcp: '/list-mcp', queue: '/queue', schedule: '/schedule',
      };
      if (actionCmd[type]) { openModal(type as NonNullable<ModalType>, actionCmd[type]); return; }
    }
    // session 弹窗
    if (trimmed === '/session' || trimmed === '/list-chats') {
      openModal('session', trimmed);
      return;
    }
    // /model（无论是否带参）一律打开可视化选择器，删除旧的 /model <name> 文本命令
    if (trimmed === '/model' || trimmed.startsWith('/model ')) {
      openModal('model', '/models');
      return;
    }
    // model 弹窗
    if (trimmed === '/models' || trimmed === '__action:model') {
      openModal('model', '/models');
      return;
    }
    // memory 弹窗
    if (trimmed === '/memory list') {
      openModal('memory', trimmed);
      return;
    }
    // skill 弹窗
    if (trimmed === '/list-skills') {
      openModal('skill', trimmed);
      return;
    }
    // mcp 弹窗
    if (trimmed === '/list-mcp') {
      openModal('mcp', trimmed);
      return;
    }
    // queue 弹窗
    if (trimmed === '/queue') {
      openModal('queue', trimmed);
      return;
    }
    // schedule 弹窗
    if (trimmed === '/schedule') {
      openModal('schedule', trimmed);
      return;
    }
    // 其他命令直接执行
    const result = await sendCommand(trimmed);
    if (result?.message) { addMessage({ role: 'system', content: result.message }); }
  }, [exitApplication, sendCommand, addMessage, setMessages, addmodelState, setAddmodelState, openModal, replaceLoadedChat]);

  const handleCommandPaletteSelect = useCallback(async (cmd: string) => {
    setShowCommandPalette(false);
    if (cmd === '__action:exit') { exitApplication(); return; }
    handleCommand(cmd);
  }, [handleCommand, exitApplication]);

  // 弹窗选中处理
  const handleModalSelect = useCallback(async (index: number) => {
    if (!activeModal || index < 0 || index >= modalItems.length) return;
    const item = modalItems[index];
    setActiveModal(null);
    setModalItems([]);

    if (activeModal === 'session') {
      const result = await sendCommand('/load-chat ' + item.id);
      if (!replaceLoadedChat(result) && result?.message) {
        addMessage({ role: 'system', content: result.message });
      }
    } else if (activeModal === 'model') {
      const result = await sendCommand('/model ' + item.id);
      if (result?.message) addMessage({ role: 'system', content: result.message });
      fetchStatus();
    } else if (activeModal === 'memory') {
      // 记忆项不可操作，仅查看
      addMessage({ role: 'system', content: 'Memory: ' + item.desc });
    } else if (activeModal === 'skill') {
      addMessage({ role: 'system', content: 'Skill: ' + item.id });
    } else if (activeModal === 'mcp') {
      addMessage({ role: 'system', content: 'MCP: ' + item.id });
    } else if (activeModal === 'queue') {
      addMessage({ role: 'system', content: 'Task: ' + item.desc });
    } else if (activeModal === 'schedule') {
      addMessage({ role: 'system', content: 'Scheduled: ' + item.desc });
    }
  }, [activeModal, modalItems, sendCommand, addMessage, fetchStatus, replaceLoadedChat]);

  const handleModalClose = useCallback(() => {
    setActiveModal(null);
    setModalItems([]);
  }, []);

  const model = useMemo(() => status?.model || 'unknown', [status?.model]);

  const progressData = useMemo(() => {
    if (!isStreaming) return null;
    const reversed = [...messages].reverse();
    const activeThinking = reversed.find(m => m.role === 'thinking' && !m.done);
    const runningTool = reversed.find(m => m.role === 'tool' && m.toolStatus === 'running');
    const stepIndex = activeThinking?.stepIndex;
    const stepTotal = activeThinking?.stepTotal;
    const stepLabel = stepIndex !== undefined && stepTotal !== undefined ? ('\u7B2C ' + stepIndex + '/' + stepTotal + ' \u6B65') : '';
    let activity = '\u601D\u8003\u4E2D';
    if (runningTool) { activity = '\u8C03\u7528 ' + runningTool.toolName; }
    else if (activeThinking?.content) {
      const lines = activeThinking.content.split('\n').filter(l => l.trim());
      const last = lines[lines.length - 1] || '';
      activity = last.length > 40 ? last.slice(0, 40) + '...' : last || '\u601D\u8003\u4E2D';
    }
    return { stepLabel, activity };
  }, [messages, isStreaming]);

  useEffect(() => { if (!isStreaming) fetchStatus(); }, [isStreaming]);

  // 弹窗打开时隐藏进度条和预览
  const showProgress = !showCommandPalette && !activeModal && !pendingApproval && !pendingQuestion;
  // InputBox 只在无弹窗时渲染（防止双输入框 bug）
  const showInputBox = !activeModal && !pendingApproval && !pendingQuestion;

  logDebug('InputBox render', { show: showInputBox, activeModal, showCommandPalette });

  return (
    <MouseProvider value={mouseManager}>
    <Box flexDirection="column" flexGrow={1}>
      <Header mode={mode} model={model} expandThinking={expandThinking} isStreaming={isStreaming} />
      <ChatPanel key={clearKey} messages={messages} height={chatHeight} mode={mode} expandThinking={expandThinking} needsModelSetup={needsModelSetup} />
      {showProgress && (
        <ProgressBanner isStreaming={isStreaming} startedAt={streamStartedAt} stepLabel={progressData?.stepLabel || ''} activity={progressData?.activity || ''} />
      )}
      {showInputBox && !addmodelState && (
        <InputBox
          mode={mode}
          onSubmit={handleSubmit}
          onCycleMode={cycleMode}
          onCommand={handleCommand}
          isStreaming={isStreaming}
          onCancel={cancelRequest}
          showCommandPalette={showCommandPalette}
          onToggleCommandPalette={() => {
            setShowCommandPalette(prev => !prev);
          }}
          onCommandPaletteSelect={handleCommandPaletteSelect}
        />
      )}
      {addmodelState && (
        <AddModelWizard
          step={addmodelState.step}
          data={addmodelState.data}
          error={addmodelError}
          onSubmit={handleWizardSubmit}
          onCancel={() => {
            setAddmodelState(null);
            setAddmodelError('');
            addMessage({ role: 'system', content: 'Add model cancelled.' });
          }}
        />
      )}
      {/* 通用弹窗 - activeModal 时替代 InputBox 渲染 */}
      {activeModal && modalItems.length > 0 && (
        <Modal
          title={modalTitle[activeModal]}
          items={modalItems}
          onSelect={handleModalSelect}
          onClose={handleModalClose}
          accentColor={modalAccent[activeModal]}
        />
      )}
      {/* 阶段二 safety gate 审批对话框 - 等待用户确认时替代 InputBox */}
      {pendingApproval && (
        <ApprovalDialog approval={pendingApproval} onDecision={respondApproval} />
      )}
      {pendingQuestion && (
        <QuestionDialog question={pendingQuestion} onResponse={respondQuestion} />
      )}
      <StatusBar status={status} mode={mode} model={model} thinkingExpanded={expandThinking} />
    </Box>
    </MouseProvider>
  );
}
