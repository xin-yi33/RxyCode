import React, { useMemo } from 'react';
import { Box, Text } from 'ink';
import stringWidth from 'string-width';
import { C } from '../theme.js';

// Custom left-only border (cli-boxes has no "singleLeft" in this version)
const LEFT_BORDER = {
  topLeft: '', top: '', topRight: '',
  right: '', bottomRight: '', bottom: '', bottomLeft: '',
  left: '\u2502',
};

// ==================== Syntax Highlighting ====================

const KW_JS = new Set([
  'const','let','var','function','return','if','else','for','while','do',
  'class','extends','import','export','from','default','new','this','super',
  'try','catch','finally','throw','typeof','instanceof','in','of','void',
  'delete','yield','async','await','static','get','set','public','private',
  'protected','readonly','enum','interface','type','namespace','as','is',
  'switch','case','break','continue','null','undefined','true','false',
  'require','module','exports','console','process','Promise','Array',
  'Object','String','Number','Boolean','Map','Set','JSON','Math','Date',
  'React','Component','useEffect','useState','useMemo','useRef','useCallback',
  'Error','TypeError','RangeError','SyntaxError','WeakMap','WeakSet','Symbol',
  'Proxy','Reflect','Iterator','Generator','async','await','RegExp',
]);

const KW_PY = new Set([
  'def','class','return','if','elif','else','for','while','import','from',
  'as','try','except','finally','raise','with','lambda','yield','global',
  'nonlocal','pass','break','continue','in','not','and','or','is','None',
  'True','False','self','cls','async','await','del','assert','print','len',
  'range','enumerate','zip','map','filter','sorted','open','str','int',
  'float','bool','list','dict','tuple','set','frozenset','type','isinstance',
  'super','abs','min','max','sum','any','all','format','input','Exception',
  'ValueError','TypeError','KeyError','IndexError','AttributeError','staticmethod',
  'classmethod','property','dataclass','Optional','Union','List','Dict','Any',
]);

const KW_BASH = new Set([
  'if','then','else','elif','fi','for','while','do','done','case','esac',
  'function','return','local','export','source','echo','printf','read',
  'unset','shift','break','continue','exit','cd','pwd','ls','grep','sed',
  'awk','cat','cp','mv','rm','mkdir','rmdir','touch','chmod','chown','find',
  'which','sudo','apt','yum','brew','git','npm','npx','yarn','pnpm','node',
  'python','python3','pip','docker','kubectl','curl','wget','ssh','scp',
  'rsync','tar','gzip','systemctl','service','ps','kill','nohup','eval','trap',
]);

const KW_GO = new Set([
  'package','import','func','var','const','type','struct','interface','map',
  'chan','go','defer','return','if','else','for','range','switch','case',
  'default','break','continue','select','fallthrough','goto','nil','true',
  'false','make','new','len','cap','append','copy','delete','close','panic',
  'recover','print','println','iota','string','int','int32','int64','float32',
  'float64','bool','byte','rune','error','uint','uint32','uint64','fmt',
]);

const KW_RUST = new Set([
  'fn','let','mut','const','static','struct','enum','trait','impl','pub',
  'use','mod','ref','self','Self','super','crate','extern','as','in','where',
  'if','else','match','for','while','loop','return','break','continue',
  'move','async','await','dyn','unsafe','true','false','String','Vec','Box',
  'Option','Result','Some','None','Ok','Err','println','print','vec',
  'format','panic','assert','derive','crate','stdin','stdout','stderr',
]);

const KW_JAVA = new Set([
  'public','private','protected','class','interface','extends','implements',
  'import','package','static','final','void','int','long','double','float',
  'boolean','char','byte','short','String','return','if','else','for','while',
  'do','switch','case','break','continue','new','this','super','try','catch',
  'finally','throw','throws','null','true','false','instanceof','synchronized',
  'abstract','enum','assert','volatile','transient','native','Integer','Double',
  'Boolean','Object','System','Math','Exception','RuntimeException','ArrayList',
  'HashMap','LinkedList','StringBuilder','Comparator','Optional','Stream',
]);

const KW_SQL = new Set([
  'SELECT','FROM','WHERE','INSERT','UPDATE','DELETE','CREATE','TABLE','DROP',
  'ALTER','INDEX','VIEW','JOIN','LEFT','RIGHT','INNER','OUTER','FULL','ON',
  'AND','OR','NOT','NULL','IS','IN','EXISTS','BETWEEN','LIKE','ORDER','BY',
  'GROUP','HAVING','LIMIT','OFFSET','DISTINCT','UNION','ALL','AS','CASE','WHEN',
  'THEN','ELSE','END','COUNT','SUM','AVG','MIN','MAX','PRIMARY','KEY','FOREIGN',
  'REFERENCES','DEFAULT','UNIQUE','CHECK','CONSTRAINT','CASCADE','INT','VARCHAR',
  'TEXT','INTEGER','BOOLEAN','DATE','TIMESTAMP','DECIMAL','FLOAT','SERIAL',
  'INTO','VALUES','SET','WITH','RECURSIVE','TRUNCATE','COMMIT','ROLLBACK',
]);

const KW_SETS: Record<string, Set<string>> = {
  js: KW_JS, javascript: KW_JS, jsx: KW_JS, mjs: KW_JS, cjs: KW_JS,
  ts: KW_JS, typescript: KW_JS, tsx: KW_JS,
  py: KW_PY, python: KW_PY, py3: KW_PY,
  bash: KW_BASH, sh: KW_BASH, shell: KW_BASH, zsh: KW_BASH, fish: KW_BASH,
  go: KW_GO, golang: KW_GO,
  rs: KW_RUST, rust: KW_RUST,
  java: KW_JAVA, jsp: KW_JAVA,
  sql: KW_SQL, mysql: KW_SQL, postgres: KW_SQL, postgresql: KW_SQL,
};

function kwSet(lang: string): Set<string> | null {
  return KW_SETS[lang.toLowerCase().trim()] ?? null;
}

function hl(line: string, kws: Set<string> | null, kp: string): React.ReactNode {
  if (!line) return <Text> </Text>;
  if (!kws) return <Text color={C.text}>{line}</Text>;

  const re = /(\/\/.*|#.*|\/\*[\s\S]*?\*\/|"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`|\b\d+\.?\d*[fFlLuU]?\b|[a-zA-Z_$][a-zA-Z0-9_$]*!?)|(\s+)/g;
  const parts: React.ReactNode[] = [];
  let lastEnd = 0;
  let m: RegExpExecArray | null;
  let ki = 0;

  while ((m = re.exec(line)) !== null) {
    const tok = m[0];
    if (!tok) { re.lastIndex++; continue; }

    // whitespace between tokens
    if (m.index > lastEnd) {
      parts.push(<Text key={`${kp}-w${ki++}`} color={C.text}>{line.slice(lastEnd, m.index)}</Text>);
    }

    if (tok.startsWith('//') || tok.startsWith('#')) {
      parts.push(<Text key={`${kp}-${ki++}`} color={C.overlay2} italic>{tok}</Text>);
    } else if (tok.startsWith('/*')) {
      parts.push(<Text key={`${kp}-${ki++}`} color={C.overlay2} italic>{tok}</Text>);
    } else if (tok[0] === '"' || tok[0] === "'" || tok[0] === '`') {
      parts.push(<Text key={`${kp}-${ki++}`} color={C.green}>{tok}</Text>);
    } else if (/^\d/.test(tok)) {
      parts.push(<Text key={`${kp}-${ki++}`} color={C.yellow}>{tok}</Text>);
    } else if (kws.has(tok.replace(/!$/, ''))) {
      parts.push(<Text key={`${kp}-${ki++}`} color={C.mauve} bold>{tok}</Text>);
    } else if (/^[A-Z]/.test(tok)) {
      parts.push(<Text key={`${kp}-${ki++}`} color={C.yellow}>{tok}</Text>);
    } else {
      parts.push(<Text key={`${kp}-${ki++}`} color={C.text}>{tok}</Text>);
    }
    lastEnd = m.index + tok.length;
  }
  if (lastEnd < line.length) {
    parts.push(<Text key={`${kp}-end`} color={C.text}>{line.slice(lastEnd)}</Text>);
  }
  if (parts.length === 0) return <Text color={C.text}>{line}</Text>;
  return <Text>{parts}</Text>;
}

// ==================== Inline Parsing ====================

function parseInline(text: string, kp: string): React.ReactNode[] {
  if (!text) return [];
  const nodes: React.ReactNode[] = [];
  // Order matters: code before bold before italic
  const re = /(`[^`]+`|\*\*[^]+?\*\*|__[^]+?__|~~[^]+?~~|\[[^\]]+\]\([^)]+\)|\*[^]+?\*|_[^]+?_)/g;
  let lastEnd = 0;
  let m: RegExpExecArray | null;
  let ki = 0;

  while ((m = re.exec(text)) !== null) {
    if (m.index > lastEnd) {
      nodes.push(<Text key={`${kp}-t${ki++}`}>{text.slice(lastEnd, m.index)}</Text>);
    }
    const tok = m[0];
    if (tok.startsWith('`')) {
      nodes.push(<Text key={`${kp}-c${ki++}`} color={C.green} backgroundColor={C.surface0}>{' ' + tok.slice(1, -1) + ' '}</Text>);
    } else if (tok.startsWith('**') || tok.startsWith('__')) {
      nodes.push(<Text key={`${kp}-b${ki++}`} bold>{tok.slice(2, -2)}</Text>);
    } else if (tok.startsWith('~~')) {
      nodes.push(<Text key={`${kp}-s${ki++}`} strikethrough color={C.overlay2}>{tok.slice(2, -2)}</Text>);
    } else if (tok.startsWith('[')) {
      const lm = tok.match(/\[([^\]]+)\]\(([^)]+)\)/);
      if (lm) nodes.push(<Text key={`${kp}-l${ki++}`} color={C.sky} underline>{lm[1]}</Text>);
    } else if (tok.startsWith('*')) {
      nodes.push(<Text key={`${kp}-i${ki++}`} italic>{tok.slice(1, -1)}</Text>);
    } else if (tok.startsWith('_')) {
      nodes.push(<Text key={`${kp}-i${ki++}`} italic>{tok.slice(1, -1)}</Text>);
    }
    lastEnd = m.index + tok.length;
  }
  if (lastEnd < text.length) {
    nodes.push(<Text key={`${kp}-end`}>{text.slice(lastEnd)}</Text>);
  }
  return nodes;
}

// ==================== Block Parsing ====================

interface ListItem { depth: number; content: string; checked?: boolean | null }

type Block =
  | { type: 'heading'; level: number; content: string }
  | { type: 'code'; lang: string; content: string }
  | { type: 'blockquote'; lines: string[] }
  | { type: 'list'; ordered: boolean; items: ListItem[] }
  | { type: 'hr' }
  | { type: 'table'; headers: string[]; aligns: ('left'|'center'|'right')[]; rows: string[][] }
  | { type: 'paragraph'; content: string }

function parseBlocks(text: string): Block[] {
  const lines = text.split('\n');
  const blocks: Block[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Code block
    if (line.trim().startsWith('```')) {
      const lang = line.trim().slice(3).trim();
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // skip closing ```
      blocks.push({ type: 'code', lang, content: codeLines.join('\n') });
      continue;
    }

    // Heading
    const hm = line.match(/^(#{1,6})\s+(.*)/);
    if (hm) {
      blocks.push({ type: 'heading', level: hm[1].length, content: hm[2].trim() });
      i++;
      continue;
    }

    // Horizontal rule
    if (/^(\s*[-*_]){3,}\s*$/.test(line) && !line.includes('**')) {
      blocks.push({ type: 'hr' });
      i++;
      continue;
    }

    // Blockquote
    if (line.startsWith('>')) {
      const qlines: string[] = [];
      while (i < lines.length && lines[i].startsWith('>')) {
        qlines.push(lines[i].replace(/^>\s?/, ''));
        i++;
      }
      blocks.push({ type: 'blockquote', lines: qlines });
      continue;
    }

    // List
    if (/^\s*([-*+]|\d+\.)\s/.test(line)) {
      const items: ListItem[] = [];
      const ordered = /^\s*\d+\.\s/.test(line);
      while (i < lines.length && /^\s*([-*+]|\d+\.)\s/.test(lines[i])) {
        const indent = lines[i].match(/^(\s*)/)?.[1].length ?? 0;
        const depth = Math.floor(indent / 2);
        const rest = lines[i].replace(/^\s*([-*+]|\d+\.)\s+/, '');
        const tm = rest.match(/^\[([ xx])\]\s(.*)/);
        if (tm) {
          items.push({ depth, content: tm[2], checked: tm[1].toLowerCase() === 'x' });
        } else {
          items.push({ depth, content: rest });
        }
        i++;
      }
      blocks.push({ type: 'list', ordered, items });
      continue;
    }

    // Table
    if (line.includes('|') && i + 1 < lines.length && /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i + 1]) && lines[i + 1].includes('-')) {
      const headers = line.split('|').map(s => s.trim()).filter((_, idx, arr) => idx > 0 && idx < arr.length - 1 || arr.length <= 2);
      const rawHeaders = line.split('|').map(s => s.trim()).filter(s => s.length > 0);
      // Parse alignment from separator
      const sep = lines[i + 1].split('|').map(s => s.trim()).filter(s => s.length > 0);
      const aligns: ('left'|'center'|'right')[] = sep.map(s => {
        if (s.startsWith(':') && s.endsWith(':')) return 'center' as const;
        if (s.endsWith(':')) return 'right' as const;
        return 'left' as const;
      });
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].includes('|') && lines[i].trim() !== '') {
        rows.push(lines[i].split('|').map(s => s.trim()).filter(s => s.length > 0));
        i++;
      }
      blocks.push({ type: 'table', headers: rawHeaders, aligns, rows });
      continue;
    }

    // Empty line
    if (line.trim() === '') { i++; continue; }

    // Paragraph
    const plines: string[] = [];
    while (i < lines.length && lines[i].trim() !== '' &&
      !lines[i].trim().startsWith('```') &&
      !/^#{1,6}\s/.test(lines[i]) &&
      !lines[i].startsWith('>') &&
      !/^\s*([-*+]|\d+\.)\s/.test(lines[i]) &&
      !/^(\s*[-*_]){3,}\s*$/.test(lines[i])) {
      plines.push(lines[i]);
      i++;
    }
    if (plines.length > 0) {
      blocks.push({ type: 'paragraph', content: plines.join(' ') });
    }
  }

  return blocks;
}

// ==================== Block Renderers ====================

const HEADING_COLORS = [C.primary, C.yellow, C.mauve, C.teal, C.sky, C.overlay2];

function renderHeading(level: number, content: string, idx: number): React.ReactNode {
  const color = HEADING_COLORS[Math.min(level - 1, 5)];
  return (
    <Box key={idx} paddingLeft={1}>
      <Text color={color} bold>{parseInline(content, `h${idx}`)}</Text>
      {level <= 2 && <Text color={C.borderDim}>{' ' + '\u2500'.repeat(Math.max(4, 40 - content.length))}</Text>}
    </Box>
  );
}

function renderCode(lang: string, content: string, idx: number): React.ReactNode {
  const kws = kwSet(lang);
  const lines = content.split('\n');

  return (
    <Box key={idx} flexDirection="column" borderStyle="round" borderColor={C.border} paddingX={1} marginX={1} flexShrink={0}>
      {lang && (
        <Box>
          <Text color={C.overlay2} italic>{lang}</Text>
          <Box flexGrow={1} />
        </Box>
      )}
      {lines.map((line, i) => (
        <Text key={i}>{hl(line, kws, `c${idx}-${i}`)}</Text>
      ))}

    </Box>
  );
}

function renderBlockquote(lines: string[], idx: number): React.ReactNode {
  // Recursively parse block content (supports nested markdown)
  const innerBlocks = parseBlocks(lines.join('\n'));
  return (
    <Box key={idx} flexDirection="column" paddingLeft={1} borderStyle={LEFT_BORDER} borderColor={C.mauve}>
      {innerBlocks.map((b, i) => renderBlock(b, `q${idx}-${i}`))}
    </Box>
  );
}

function renderList(ordered: boolean, items: ListItem[], idx: number): React.ReactNode {
  const bullets = ['\u2022', '\u25E6', '\u2023', '\u2043'];
  const lines: React.ReactNode[] = [];
  items.forEach((item, i) => {
    const bullet = item.checked === true ? '\u2611' :
                   item.checked === false ? '\u2610' :
                   ordered ? `${i + 1}.` :
                   bullets[Math.min(item.depth, bullets.length - 1)];
    const bColor = item.checked !== null && item.checked !== undefined ? C.green :
                   item.depth === 0 ? C.yellow : C.sky;
    lines.push(
      <Box key={`${idx}-li${i}`} paddingLeft={item.depth * 2 + 1}>
        <Text color={bColor}>{bullet} </Text>
        <Text color={item.checked === true ? C.overlay2 : C.text}>{parseInline(item.content, `li${idx}-${i}`)}</Text>
      </Box>
    );
  });
  return <Box key={idx} flexDirection="column">{lines}</Box>;
}

function renderTable(headers: string[], aligns: ('left'|'center'|'right')[], rows: string[][], idx: number): React.ReactNode {
  const colCount = Math.max(headers.length, ...rows.map(r => r.length));
  // Bug 3 fix: measure column widths by DISPLAY width (string-width / UAX #11),
  // not by JS string length. CJK / fullwidth / emoji glyphs occupy 2 terminal
  // columns, so a naive `.length` made cells wider than computed and broke the
  // table alignment (garbled tables) on narrow terminals.
  const widths: number[] = [];
  for (let c = 0; c < colCount; c++) {
    const hw = stringWidth(headers[c] ?? '');
    const rw = rows.reduce((mx, r) => Math.max(mx, stringWidth(r[c] ?? '')), 0);
    widths.push(Math.max(hw, rw));
  }

  const pad = (s: string, w: number, align: 'left'|'center'|'right') => {
    const sw = stringWidth(s);
    if (sw >= w) return s;
    const padN = w - sw;
    if (align === 'right') return ' '.repeat(padN) + s;
    if (align === 'center') return ' '.repeat(Math.floor(padN / 2)) + s + ' '.repeat(Math.ceil(padN / 2));
    return s + ' '.repeat(padN);
  };

  const totalW = widths.reduce((a, b) => a + b, 0) + 3 * (colCount - 1);
  const hLine = '\u2500'.repeat(totalW);

  return (
    <Box key={idx} flexDirection="column" paddingLeft={1}>
      <Box>
        <Text color={C.borderDim}>{'\u2502 '}</Text>
        {headers.map((h, c) => (
          <React.Fragment key={c}>
            <Text color={C.primary} bold>{pad(h, widths[c], aligns[c] || 'left')}</Text>
            {c < colCount - 1 && <Text color={C.borderDim}>{' \u2502 '}</Text>}
          </React.Fragment>
        ))}
      </Box>
      <Text color={C.borderDim}>{hLine}</Text>
      {rows.map((row, r) => (
        <Box key={r}>
          <Text color={C.borderDim}>{'\u2502 '}</Text>
          {Array.from({ length: colCount }).map((_, c) => (
            <React.Fragment key={c}>
              <Text color={C.text}>{pad(row[c] ?? '', widths[c], aligns[c] || 'left')}</Text>
              {c < colCount - 1 && <Text color={C.borderDim}>{' \u2502 '}</Text>}
            </React.Fragment>
          ))}
        </Box>
      ))}
    </Box>
  );
}

function renderParagraph(content: string, idx: number): React.ReactNode {
  return (
    <Box key={idx} paddingLeft={1}>
      <Text color={C.text}>{parseInline(content, `p${idx}`)}</Text>
    </Box>
  );
}

function renderBlock(block: Block, idx: string | number): React.ReactNode {
  const key = typeof idx === 'number' ? idx : 0;
  switch (block.type) {
    case 'heading':
      return renderHeading(block.level, block.content, key);
    case 'code':
      return renderCode(block.lang, block.content, key);
    case 'blockquote':
      return renderBlockquote(block.lines, key);
    case 'list':
      return renderList(block.ordered, block.items, key);
    case 'hr':
      return <Text key={key} color={C.borderDim}>{'  ' + '\u2500'.repeat(48)}</Text>;
    case 'table':
      return renderTable(block.headers, block.aligns, block.rows, key);
    case 'paragraph':
      return renderParagraph(block.content, key);
    default:
      return null;
  }
}

// ==================== Main Component ====================

export default React.memo(function Markdown({ content }: { content: string }) {
  const blocks = useMemo(() => parseBlocks(content || ''), [content]);
  if (blocks.length === 0) return null;
  return (
    <Box flexDirection="column" paddingLeft={1}>
      {blocks.map((block, i) => (
        <React.Fragment key={i}>
          {renderBlock(block, i)}
          {block.type !== 'code' && i < blocks.length - 1 && block.type !== 'list' && block.type !== 'table' &&
            <Text>{' '}</Text>}
        </React.Fragment>
      ))}
    </Box>
  );
});
