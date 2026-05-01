import { useRef, useState } from 'react';
import { cn } from '../../../../lib/utils';
import type { ToolCallMessage } from '../../../../stores/v2/messageStore';
import type { HookExecutionInfo } from '../../../../types';

interface ToolCallMessageViewProps {
  message: ToolCallMessage;
}

export function ToolCallMessageView({ message }: ToolCallMessageViewProps) {
  const [expanded, setExpanded] = useState(false);
  const detailsRef = useRef<HTMLDivElement>(null);

  const isPending = message.result === undefined;
  // Both the in-orchestrator checkpoint MCP and the standalone checkpoint MCP
  // get the delegation card; the standalone server's `init` housekeeping tool
  // does not (it's a one-time session-start setup call).
  const isCheckpoint = message.toolName === 'mcp__massgen_checkpoint__checkpoint'
    || message.toolName === 'mcp__massgen_checkpoint_standalone__checkpoint'
    || message.toolName === 'checkpoint';
  const isStandaloneCheckpoint = message.toolName === 'mcp__massgen_checkpoint_standalone__checkpoint';

  const elapsedStr = message.elapsed
    ? message.elapsed > 1000
      ? `${(message.elapsed / 1000).toFixed(1)}s`
      : `${Math.round(message.elapsed)}ms`
    : null;

  const filePath = extractFilePath(message.args);

  // Special rendering for checkpoint delegation
  if (isCheckpoint) {
    // Internal checkpoint uses `task`; standalone uses `objective`. Action_goals
    // is standalone-only (objective-mode action intents).
    const primary = (message.args.task as string)
      || (message.args.objective as string)
      || '';
    const evalCriteria = (message.args.eval_criteria as string[]) || [];
    const actionGoals = Array.isArray(message.args.action_goals)
      ? (message.args.action_goals as unknown[])
      : [];
    const headerLabel = isStandaloneCheckpoint
      ? 'Standalone Checkpoint'
      : 'Checkpoint Delegation';
    return (
      <div className="v2-step-group">
        <div className="v2-step-node" />
        <div className="rounded-lg border border-blue-500/30 bg-blue-500/5 overflow-hidden">
          <div className="flex items-center gap-2 px-3 py-2">
            <span className="text-base">📋</span>
            <span className="text-sm font-semibold text-blue-400 uppercase tracking-wide">
              {headerLabel}
            </span>
            {isPending && (
              <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse shrink-0" />
            )}
            {!isPending && (
              <span className="w-1.5 h-1.5 rounded-full bg-v2-online shrink-0" />
            )}
            <div className="flex-1" />
            {elapsedStr && (
              <span className="text-xs text-v2-text-muted">{elapsedStr}</span>
            )}
          </div>
          <div className="px-3 pb-2">
            <p className="text-sm text-v2-text-primary leading-relaxed">
              {primary.length > 200 ? primary.slice(0, 200) + '...' : primary}
            </p>
            {evalCriteria.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {evalCriteria.slice(0, 5).map((c, i) => (
                  <span key={i} className="text-[11px] px-1.5 py-0.5 rounded bg-v2-surface border border-v2-border-subtle text-v2-text-muted">
                    {typeof c === 'string' && c.length > 60 ? c.slice(0, 60) + '...' : c}
                  </span>
                ))}
              </div>
            )}
            {evalCriteria.length === 0 && actionGoals.length > 0 && (
              <div className="mt-2">
                <span className="text-[11px] px-1.5 py-0.5 rounded bg-v2-surface border border-v2-border-subtle text-v2-text-muted">
                  {actionGoals.length} action goal{actionGoals.length === 1 ? '' : 's'}
                </span>
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="v2-step-group">
      {/* Inline trace row — no card chrome */}
      <div
        className={cn(
          'v2-tool-row flex items-center gap-[7px] py-[3px] cursor-pointer rounded-sm',
          'hover:bg-[var(--v2-channel-hover)] transition-colors duration-100',
          expanded && 'v2-tool-row-expanded'
        )}
        onClick={() => {
          const willExpand = !expanded;
          setExpanded(willExpand);
          if (willExpand) {
            requestAnimationFrame(() => {
              detailsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            });
          }
        }}
      >
        <svg
          className="v2-hover-chevron w-3 h-3 shrink-0 text-v2-text-muted"
          style={{ marginLeft: '-14px', marginRight: '-5px' }}
          viewBox="0 0 12 12"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
        >
          <path d="M4 2l4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>

        <span className={cn(
          'w-1.5 h-1.5 rounded-full shrink-0',
          isPending ? 'bg-blue-400 animate-pulse' : message.success ? 'bg-v2-online' : 'bg-red-400'
        )} />

        <span className="font-mono text-xs font-medium text-v2-text-muted opacity-80 shrink-0">
          {message.toolName}
        </span>

        <span className="font-mono text-xs text-v2-text-muted truncate flex-1">
          {filePath || ''}
        </span>

        <HookCountBadge preHooks={message.preHooks} postHooks={message.postHooks} />

        {elapsedStr && (
          <span className="text-xs font-mono text-v2-text-muted shrink-0">
            {elapsedStr}
          </span>
        )}
      </div>

      {/* Expanded details — subtle left border */}
      {expanded && (
        <div ref={detailsRef} className="ml-1.5 border-l border-v2-border-subtle pl-3 mt-0.5 space-y-2 animate-v2-fade-in">
          {Object.keys(message.args).length > 0 && (
            <div className="rounded bg-v2-surface p-2 border border-v2-border-subtle">
              <div className="text-[11px] uppercase tracking-wider text-v2-text-muted mb-1">Args</div>
              <pre className="text-xs font-mono whitespace-pre-wrap break-all">
                <JsonValue value={message.args} />
              </pre>
            </div>
          )}
          {message.result !== undefined && (
            <div className="rounded bg-v2-surface p-2 border border-v2-border-subtle">
              <div className="text-[11px] uppercase tracking-wider text-v2-text-muted mb-1">Result</div>
              <pre className="text-xs font-mono text-v2-text-secondary whitespace-pre-wrap break-all max-h-[300px] overflow-y-auto v2-scrollbar">
                {message.result}
              </pre>
            </div>
          )}
          <HookList label="Pre-hooks" hooks={message.preHooks} />
          <HookList label="Post-hooks" hooks={message.postHooks} />
        </div>
      )}
    </div>
  );
}

// ============================================================================
// JSON Syntax Highlighting
// ============================================================================

function JsonValue({ value, indent = 0 }: { value: unknown; indent?: number }) {
  if (value === null) return <span className="text-red-400">null</span>;
  if (typeof value === 'boolean') return <span className="text-purple-400">{String(value)}</span>;
  if (typeof value === 'number') return <span className="text-amber-400">{value}</span>;
  if (typeof value === 'string') {
    const display = value.length > 500 ? value.slice(0, 500) + '\u2026' : value;
    return <span className="text-green-400">&quot;{display}&quot;</span>;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-v2-text-muted">[]</span>;
    const pad = '  '.repeat(indent + 1);
    const closePad = '  '.repeat(indent);
    return (
      <>
        {'[\n'}
        {value.map((item, i) => (
          <span key={i}>
            {pad}<JsonValue value={item} indent={indent + 1} />
            {i < value.length - 1 ? ',' : ''}{'\n'}
          </span>
        ))}
        {closePad}{']'}
      </>
    );
  }
  if (typeof value === 'object' && value !== null) {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return <span className="text-v2-text-muted">{'{}'}</span>;
    const pad = '  '.repeat(indent + 1);
    const closePad = '  '.repeat(indent);
    return (
      <>
        {'{\n'}
        {entries.map(([key, val], i) => (
          <span key={key}>
            {pad}<span className="text-blue-400">&quot;{key}&quot;</span>{': '}
            <JsonValue value={val} indent={indent + 1} />
            {i < entries.length - 1 ? ',' : ''}{'\n'}
          </span>
        ))}
        {closePad}{'}'}
      </>
    );
  }
  return <span className="text-v2-text-secondary">{String(value)}</span>;
}

function extractFilePath(args: Record<string, unknown>): string | undefined {
  for (const key of ['path', 'file_path', 'filename', 'file', 'target', 'command']) {
    if (typeof args[key] === 'string') {
      return args[key] as string;
    }
  }
  return undefined;
}

// ============================================================================
// Hook Display Components
// ============================================================================

const DECISION_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  allow: { bg: 'bg-green-500/10', text: 'text-green-400', label: 'allow' },
  deny: { bg: 'bg-amber-500/10', text: 'text-amber-400', label: 'deny' },
  error: { bg: 'bg-red-500/10', text: 'text-red-400', label: 'error' },
};

function HookCountBadge({ preHooks, postHooks }: { preHooks?: HookExecutionInfo[]; postHooks?: HookExecutionInfo[] }) {
  const count = (preHooks?.length || 0) + (postHooks?.length || 0);
  if (count === 0) return null;
  return (
    <span className="text-[10px] text-v2-text-muted shrink-0 flex items-center gap-0.5">
      <svg className="w-3 h-3" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M8 2v4l2 2M8 2L6 4" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M4 8h8" strokeLinecap="round" />
        <path d="M8 14v-4" strokeLinecap="round" />
      </svg>
      {count}
    </span>
  );
}

export function HookList({ label, hooks }: { label: string; hooks?: HookExecutionInfo[] }) {
  if (!hooks || hooks.length === 0) return null;
  return (
    <div className="rounded bg-v2-surface p-2 border border-v2-border-subtle">
      <div className="text-[11px] uppercase tracking-wider text-v2-text-muted mb-1">{label}</div>
      <div className="space-y-1">
        {hooks.map((hook, i) => (
          <HookRow key={`${hook.hook_name}-${i}`} hook={hook} />
        ))}
      </div>
    </div>
  );
}

function HookRow({ hook }: { hook: HookExecutionInfo }) {
  const [expanded, setExpanded] = useState(false);
  const style = DECISION_STYLES[hook.decision] || DECISION_STYLES.error;
  const elapsed = hook.execution_time_ms != null
    ? hook.execution_time_ms > 1000
      ? `${(hook.execution_time_ms / 1000).toFixed(1)}s`
      : `${Math.round(hook.execution_time_ms)}ms`
    : null;
  const expandable = !!(hook.injection_content || hook.injection_preview || hook.reason);

  return (
    <div>
      <button
        onClick={() => expandable && setExpanded(!expanded)}
        className={cn(
          'flex items-center gap-2 w-full text-left text-xs py-0.5',
          expandable && 'hover:bg-[var(--v2-channel-hover)] rounded px-1 -mx-1',
          !expandable && 'cursor-default'
        )}
      >
        {/* Hook type icon */}
        <span className="shrink-0 text-v2-text-muted">
          {hook.hook_type === 'pre' ? (
            <svg className="w-3 h-3" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M8 2v4l2 2M8 2L6 4" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M4 8h8" strokeLinecap="round" />
              <path d="M8 14v-4" strokeLinecap="round" />
            </svg>
          ) : (
            <svg className="w-3 h-3" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="3" y="4" width="10" height="8" rx="1" />
              <path d="M6 4V2h4v2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          )}
        </span>

        {/* Hook name */}
        <span className="font-mono text-v2-text-secondary truncate">{hook.hook_name}</span>

        {/* Decision badge */}
        <span className={cn('text-[11px] px-1.5 py-0.5 rounded border', style.bg, style.text, 'border-current/20 shrink-0')}>
          {style.label}
        </span>

        <div className="flex-1" />

        {/* Elapsed */}
        {elapsed && <span className="text-v2-text-muted shrink-0">{elapsed}</span>}

        {/* Expand indicator */}
        {expandable && (
          <svg
            className={cn('w-2.5 h-2.5 text-v2-text-muted transition-transform duration-150 shrink-0', expanded && 'rotate-90')}
            viewBox="0 0 12 12"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
          >
            <path d="M4 2l4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        )}
      </button>

      {expanded && (
        <div className="ml-5 mt-1 mb-1 text-xs text-v2-text-secondary animate-v2-fade-in">
          {hook.reason && (
            <p className="text-v2-text-muted italic mb-1">{hook.reason}</p>
          )}
          {(hook.injection_content || hook.injection_preview) && (
            <pre className="font-mono whitespace-pre-wrap break-all bg-v2-surface-raised rounded p-1.5 border border-v2-border-subtle max-h-[150px] overflow-y-auto v2-scrollbar">
              {hook.injection_content || hook.injection_preview}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
