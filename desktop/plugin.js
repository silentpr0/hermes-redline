// Redline — guided Markdown review in Hermes Desktop.
// The directive opens a .md file for selected-text annotations, then sends a
// batch of comments, questions, or change requests to the agent composer.
// Persistence: <file>.redline.json sidecar.

import {
  Badge, Button, Codicon, Input, MessageTextContent, STATUSBAR_AREAS,
  TRANSCRIPT_DIRECTIVE_AREA, Textarea, atom, host, queryClient, useQuery, useValue,
} from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'
import { useEffect, useRef, useState } from 'react'

const KINDS = {
  comment: { label: 'comment', short: '◆', var: '--rl-comment' },
  question: { label: 'question', short: '◇', var: '--rl-question' },
  change: { label: 'change request', short: '✎', var: '--rl-change' },
}

const $openCount = atom(0)

const CSS = `
.rl-root{position:relative;height:100%;display:flex;flex-direction:column;padding:18px 22px;
  --rl-comment:var(--ui-accent);--rl-question:var(--ui-purple);--rl-change:var(--ui-orange);
  --rl-comment-soft:color-mix(in oklab,var(--ui-accent) 16%,transparent);
  --rl-question-soft:color-mix(in oklab,var(--ui-purple) 16%,transparent);
  --rl-change-soft:color-mix(in oklab,var(--ui-orange) 16%,transparent)}
.rl-head{display:flex;align-items:center;gap:8px;flex-wrap:wrap;border-bottom:1px solid var(--ui-stroke-secondary);padding-bottom:12px}
.rl-title{font-size:15px;font-weight:600;letter-spacing:-.01em}
.rl-path{font-size:11px;color:var(--ui-text-tertiary);max-width:34ch;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rl-main{flex:1;min-height:0;position:relative;margin-top:14px}
.rl-doc{height:100%;overflow:auto;padding-right:34px;max-width:720px;line-height:1.7;-webkit-user-select:text;user-select:text}
.rl-doc [data-rl-block]{position:relative;padding:2px 4px;border-radius:6px}
.rl-doc h1,.rl-doc h2,.rl-doc h3{font-weight:600;letter-spacing:-.01em;margin:14px 0 6px}
.rl-doc h1{font-size:17px}.rl-doc h2{font-size:15px}.rl-doc h3{font-size:13.5px}
.rl-doc ul,.rl-doc ol{padding-left:22px;margin:6px 0}
.rl-doc code{background:color-mix(in oklab,var(--ui-bg-elevated) 70%,transparent);border:1px solid var(--ui-stroke-tertiary);border-radius:5px;padding:1px 5px;font-size:12.5px}
.rl-doc pre{background:color-mix(in oklab,var(--ui-bg-elevated) 70%,transparent);border:1px solid var(--ui-stroke-tertiary);border-radius:8px;padding:10px 12px;overflow:auto;margin:8px 0}
.rl-doc pre code{border:0;background:none;padding:0}
.rl-doc blockquote{border-left:2px solid var(--ui-stroke-secondary);padding-left:10px;color:var(--ui-text-secondary);margin:8px 0}
.rl-doc table{border-collapse:collapse;margin:8px 0;font-size:13px}
.rl-doc th,.rl-doc td{border:1px solid var(--ui-stroke-secondary);padding:5px 10px;text-align:left}
.rl-doc a{color:var(--ui-accent)}
.rl-doc [data-rl-block]:hover{background:color-mix(in oklab,var(--ui-accent) 5%,transparent)}
.rl-doc mark{background:var(--rl-soft);color:inherit;border-radius:3px;padding:1px 2px;box-shadow:inset 0 -1px 0 var(--rl-line)}
.rl-doc mark.rl-sent{opacity:.45}
.rl-marker{position:absolute;right:-26px;top:2px;width:20px;height:20px;border-radius:6px;border:1px solid var(--rl-line);background:var(--rl-soft);color:var(--rl-line);font-size:11px;line-height:1;cursor:pointer;padding:0;display:flex;align-items:center;justify-content:center}
.rl-marker:hover{background:color-mix(in oklab,var(--rl-line) 30%,transparent)}
.rl-marker.done{opacity:.4}
.rl-float{width:100%;border:1px solid var(--ui-stroke-secondary);border-left:2px solid var(--rl-line);border-radius:11px;padding:10px 12px;background:color-mix(in oklab,var(--ui-bg-elevated) 88%,transparent);backdrop-filter:blur(14px);box-shadow:0 10px 30px -14px rgba(0,0,0,.6);animation:rl-in .18s ease-out}
.rl-card{position:relative;border:1px solid var(--ui-stroke-secondary);border-left:2px solid var(--rl-line);border-radius:11px;padding:10px 12px;background:color-mix(in oklab,var(--ui-bg-elevated) 72%,transparent)}
@keyframes rl-in{from{opacity:0}}
.rl-kind{display:flex;align-items:center;gap:6px;font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--rl-line)}
.rl-quote{font-size:12px;color:var(--ui-text-tertiary);border-left:2px solid var(--ui-stroke-secondary);padding-left:8px;margin:6px 0;font-style:italic;overflow:hidden;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical}
.rl-note{font-size:13px;line-height:1.55}
.rl-foot{display:flex;justify-content:space-between;align-items:center;margin-top:8px;font-size:11px;color:var(--ui-text-tertiary)}
.rl-mini{border:0;background:none;color:var(--ui-text-tertiary);cursor:pointer;font-size:11px;padding:0}
.rl-mini:hover{color:var(--ui-text-primary)}
.rl-pill{position:absolute;z-index:10;display:flex;gap:2px;padding:4px;border-radius:10px;border:1px solid var(--ui-stroke-secondary);background:color-mix(in oklab,var(--ui-bg-elevated) 84%,transparent);backdrop-filter:blur(14px);box-shadow:0 10px 30px -14px rgba(0,0,0,.6);font-size:12px}
.rl-pill button{border:0;background:none;cursor:pointer;font-size:12px;font-weight:500;padding:5px 9px;border-radius:7px;color:var(--rl-line)}
.rl-pill button:hover{background:var(--rl-soft)}
.rl-pill i{width:1px;background:var(--ui-stroke-secondary);margin:2px 3px}
.rl-hint{font-size:11px;color:var(--ui-text-quaternary);padding-top:8px}
.rl-empty{font-size:12px;color:var(--ui-text-tertiary);padding:10px 0}
.rl-chip{display:flex;align-items:center;gap:5px;border:0;background:none;cursor:pointer;font-size:11px;padding:0 4px;color:var(--ui-text-tertiary)}
.rl-chip:hover{color:var(--ui-text-primary)}
.rl-chip b{font-weight:600;color:var(--ui-accent)}
`

function blockQuote(block, sel) {
  const i = block.indexOf(sel)
  if (i >= 0) return sel
  const head = sel.slice(0, 40)
  const j = head.length > 12 ? block.indexOf(head) : -1
  if (j >= 0) return block.slice(j, j + Math.max(sel.length, head.length))
  return sel.slice(0, 160)
}

export function buildBatchMessage(path, items) {
  const head = `🔴 redline — review of ${path} (${items.length} notes):`
  const body = items.map((a, i) => {
    const k = KINDS[a.kind] || KINDS.comment
    return `${i + 1}. [${k.label}] selection: "${a.quote}"\n   → ${a.note}`
  })
  return [head, ...body].join('\n')
}

function KindIcon({ kind }) {
  const k = KINDS[kind] || KINDS.comment
  return jsx('span', { style: { color: `var(${k.var})` }, children: k.short })
}

function Card({ a, draftText, onDraftText, onSaveDraft, onSend, onCancelDraft, onToggle, onRemove, onClose }) {
  const k = KINDS[a.kind] || KINDS.comment
  if (a.draft) {
    return jsxs('div', { className: 'rl-float', style: { '--rl-line': `var(${k.var})`, '--rl-soft': `var(${k.var}-soft)` }, children: [
      jsxs('div', { className: 'rl-kind', children: [jsx(KindIcon, { kind: a.kind }), k.label] }),
      jsx('div', { className: 'rl-quote', children: a.quote }),
      jsx(Textarea, {
        autoFocus: true, rows: 3, placeholder: 'Your comment, question, or request…',
        value: draftText, onChange: (e) => onDraftText(e.target.value),
      }),
      jsxs('div', { className: 'rl-foot', children: [
        jsx('button', { type: 'button', className: 'rl-mini', onClick: onCancelDraft, children: 'cancel' }),
        jsxs('span', { style: { display: 'flex', gap: 6 }, children: [
          jsx(Button, { size: 'sm', variant: 'outline', disabled: !draftText.trim(), onClick: () => onSaveDraft(a.id, draftText), children: 'add to list' }),
          jsx(Button, { size: 'sm', disabled: !draftText.trim(), onClick: () => onSend(a.id, draftText), children: 'send now' }),
        ] }),
      ] }),
    ] })
  }
  return jsxs('div', { className: 'rl-float', style: { '--rl-line': a.status === 'resolved' ? 'var(--ui-text-quaternary)' : `var(${k.var})`, '--rl-soft': `var(${k.var}-soft)` }, children: [
    jsxs('div', { className: 'rl-kind', children: [
      jsx(KindIcon, { kind: a.kind }), k.label,
      a.status === 'sent' && jsx('span', { style: { marginLeft: 'auto' }, children: 'sent' }),
      a.status === 'resolved' && jsx('span', { style: { marginLeft: 'auto' }, children: '✓ resolved' }),
      jsx('button', { type: 'button', className: 'rl-mini', style: { marginLeft: 6 }, onClick: onClose, children: '✕' }),
    ] }),
    jsx('div', { className: 'rl-quote', children: a.quote }),
    jsx('div', { className: 'rl-note', children: a.note }),
    jsxs('div', { className: 'rl-foot', children: [
      jsx('button', { type: 'button', className: 'rl-mini', onClick: () => onRemove(a.id), children: 'remove' }),
      jsxs('span', { style: { display: 'flex', gap: 6, alignItems: 'center' }, children: [
        a.status === 'open' && a.note ? jsx(Button, { size: 'sm', variant: 'ghost', onClick: () => onSend(a.id, a.note), children: 'send now' }) : null,
        jsx('button', { type: 'button', className: 'rl-mini', onClick: () => onToggle(a.id), children: a.status === 'resolved' ? 'reopen' : 'resolve' }),
      ] }),
    ] }),
  ] })
}

function RedlinePane({ ctx, file }) {
  const [path, setPath] = useState(file || '')
  const [active, setActive] = useState(file || '')
  const [draftText, setDraftText] = useState('')
  const [pill, setPill] = useState(null)
  const [shown, setShown] = useState(null)
  const docRef = useRef(null)
  const mainRef = useRef(null)

  const docQ = useQuery({
    queryKey: ['redline:doc', active],
    queryFn: () => ctx.rest(`/doc?path=${encodeURIComponent(active)}`),
    enabled: !!active, retry: false, refetchInterval: 3000, // ponytail: 3-second polling; upgrade to SSE if latency matters
  })
  const annQ = useQuery({
    queryKey: ['redline:ann', active],
    queryFn: () => ctx.rest(`/annotations?path=${encodeURIComponent(active)}`),
    enabled: !!active, retry: false, refetchInterval: 3000,
  })

  const items = (annQ.data && annQ.data.items) || []
  const open = items.filter((a) => a.status === 'open')
  useEffect(() => {
    $openCount.set(open.length)
    return () => $openCount.set(0)
  }, [open.length])

  const blocks = active && docQ.data ? docQ.data.content.split(/\n[ \t]*\n/) : []

  useEffect(() => { if (file) { setActive(file); setPath(file) } }, [file])

  const save = (next) => {
    ctx.rest('/annotations', { method: 'POST', body: { path: active, items: next } })
      .then(() => {
        queryClient.setQueryData(['redline:ann', active], { items: next }) // Update the cache so the annotation appears immediately.
        host.notify({ kind: 'info', message: `redline: saved ${next.length} annotations` })
      })
      .catch(() => host.notifyError('redline backend unavailable — enable the redline plugin (Capabilities → Plugins) and restart the gateway'))
  }

  const addDraft = (id, note) => {
    const a = items.find((x) => x.id === id)
    if (!a) return
    save([...items.filter((x) => x.id !== id), { ...a, note: note.trim(), draft: undefined, status: 'open' }])
    setDraftText('')
  }
  const toggle = (id) => save(items.map((a) => (a.id === id ? { ...a, status: a.status === 'resolved' ? 'open' : 'resolved' } : a)))
  const remove = (id) => save(items.filter((a) => a.id !== id))

  const onMouseUp = () => {
    const sel = window.getSelection()
    const text = sel ? sel.toString().trim() : ''
    if (!text || !mainRef.current || !docRef.current || !docRef.current.contains(sel.anchorNode)) { setPill(null); return }
    let node = sel.anchorNode
    if (node && node.nodeType === 3) node = node.parentElement
    const blockEl = node && node.closest ? node.closest('[data-rl-block]') : null
    if (!blockEl) { setPill(null); return }
    const idx = Number(blockEl.dataset.rlBlock)
    const r = sel.getRangeAt(0).getBoundingClientRect()
    const mb = mainRef.current.getBoundingClientRect()
    setPill({
      block: idx,
      quote: blockQuote(blocks[idx] || '', text),
      x: Math.max(0, Math.min(r.left - mb.left, mb.width - 260)),
      y: r.bottom - mb.top + 8,
    })
  }
  const openKind = (kind) => {
    if (!pill) return
    const id = `a${Date.now()}`
    save([...items, { id, kind, block: pill.block, quote: pill.quote, note: '', status: 'open', draft: true }])
    setShown(id)
    setDraftText('')
    setPill(null)
    window.getSelection().removeAllRanges()
  }

  const sendBatch = () => {
    if (!open.length) return
    const ok = host.composer.submit(host.state.focusedSessionId.get(), buildBatchMessage(active, open))
    if (!ok) { host.notifyError('redline: no open chat can receive the batch'); return }
    save(items.map((a) => (a.status === 'open' ? { ...a, status: 'sent' } : a)))
    host.notify({ kind: 'info', message: `redline: ${open.length} annotations sent to Hermes` })
  }
  const sendOne = (id, note) => {
    const a = items.find((x) => x.id === id)
    if (!a) return
    const ok = host.composer.submit(host.state.focusedSessionId.get(), buildBatchMessage(active, [{ ...a, note: note.trim(), draft: undefined }]))
    if (!ok) { host.notifyError('redline: no open chat can receive the annotation'); return }
    save(items.map((x) => (x.id === id ? { ...x, note: note.trim(), draft: undefined, status: 'sent' } : x)))
    setShown(null)
    setDraftText('')
    host.notify({ kind: 'info', message: 'redline: annotation sent to Hermes' })
  }

  const load = () => {
    const p = path.trim()
    if (!p) return
    setActive(p)
    const recent = (ctx.storage.get('recent') || []).filter((x) => x !== p)
    ctx.storage.set('recent', [p, ...recent].slice(0, 6))
  }
  const recent = ctx.storage.get('recent') || []

  return jsxs('div', { className: 'rl-root', children: [
    jsxs('div', { className: 'rl-head', children: [
      jsx('span', { className: 'rl-title', children: 'redline' }),
      active ? jsx('span', { className: 'rl-path', title: active, children: active }) : null,
      jsx(Input, { value: path, placeholder: 'Markdown file path', className: 'w-64', onChange: (e) => setPath(e.target.value), onKeyDown: (e) => { if (e.key === 'Enter') load() } }),
      jsx(Button, { size: 'sm', variant: 'outline', onClick: load, children: 'open' }),
      recent.length ? jsx('span', { style: { display: 'flex', gap: 4, flexWrap: 'wrap' }, children: recent.map((r) => jsx(Button, { size: 'sm', variant: 'ghost', className: 'rl-chip', onClick: () => { setActive(r); setPath(r) } }, r.split('/').pop())) }) : null,
      jsx('span', { style: { marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }, children: [
        open.length ? jsx(Badge, { variant: 'outline', children: `${open.length} open` }) : null,
        jsx(Button, { size: 'sm', disabled: !open.length, onClick: sendBatch, children: `Send ${open.length || ''} to Hermes` }),
      ] }),
    ] }),
    jsxs('div', { className: 'rl-main', ref: mainRef, children: [
      jsx('div', {
        ref: docRef, className: 'rl-doc', onMouseUp: onMouseUp,
        children: docQ.isPending && active
          ? jsx('div', { className: 'rl-empty', children: 'loading…' })
          : docQ.isError
            ? jsx('div', { className: 'rl-empty', children: `could not read ${active} — check the path (the redline backend must be active)` })
            : blocks.map((b, i) => jsxs('div', { 'data-rl-block': String(i), className: 'rl-block', children: [
                jsx(MessageTextContent, { text: b, media: false }),
                ...items.filter((a) => a.block === i).map((a) => {
                  const k = KINDS[a.kind] || KINDS.comment
                  return jsx('button', {
                    type: 'button', className: `rl-marker${a.status === 'resolved' ? ' done' : ''}`,
                    style: { '--rl-line': `var(${k.var})`, '--rl-soft': `var(${k.var}-soft)` },
                    title: a.note || k.label,
                    onClick: () => setShown(shown === a.id ? null : a.id),
                    children: k.short,
                  }, a.id)
                }),
              ] }, String(i))) || null,
      }),
      shown ? (() => {
        const a = items.find((x) => x.id === shown)
        if (!a) return null
        const blockEl = docRef.current && docRef.current.querySelector(`[data-rl-block="${a.block}"]`)
        if (!blockEl || !mainRef.current) return null
        const bb = blockEl.getBoundingClientRect(), mb = mainRef.current.getBoundingClientRect()
        const top = Math.max(4, Math.min(bb.top - mb.top, mb.height - 120))
        return jsx('div', { style: { position: 'absolute', top, left: '50%', width: 'min(300px, 86%)', transform: 'translateX(-50%)', zIndex: 20 }, children: jsx(Card, {
          a, draftText, onDraftText: setDraftText, onSaveDraft: addDraft, onSend: sendOne,
          onCancelDraft: () => { save(items.filter((x) => x.id !== a.id)); setShown(null) },
          onToggle: toggle, onRemove: () => { remove(a.id); setShown(null) },
          onClose: () => setShown(null),
        }) })
      })() : null,
      pill ? jsxs('div', { className: 'rl-pill', style: { left: pill.x, top: pill.y }, children: [
        jsx('button', { type: 'button', style: { '--rl-line': 'var(--rl-comment)', '--rl-soft': 'var(--rl-comment-soft)' }, onClick: () => openKind('comment'), children: '◆ comment' }),
        jsx('i', {}),
        jsx('button', { type: 'button', style: { '--rl-line': 'var(--rl-question)', '--rl-soft': 'var(--rl-question-soft)' }, onClick: () => openKind('question'), children: '◇ question' }),
        jsx('i', {}),
        jsx('button', { type: 'button', style: { '--rl-line': 'var(--rl-change)', '--rl-soft': 'var(--rl-change-soft)' }, onClick: () => openKind('change'), children: '✎ change request' }),
      ] }) : null,
    ] }),
    jsx('div', { className: 'rl-hint', children: 'select text → ◆ comment · ◇ question · ✎ change request — the batch becomes a chat message' }),
  ] })
}

function Chip() {
  const n = useValue($openCount)
  if (!n) return null
  return jsxs('span', {
    className: 'rl-chip', title: 'open redline annotations',
    children: [jsx(Codicon, { name: 'tag', className: 'text-(--ui-accent)' }), jsx('b', { children: String(n) })],
  })
}

export default {
  id: 'redline',
  name: 'Redline',
  register(ctx) {
    const style = document.createElement('style')
    style.textContent = CSS
    document.head.appendChild(style)
    ctx.onDispose(() => style.remove())

    ctx.registerMany([
      { id: 'chip', area: STATUSBAR_AREAS.right, order: 130, render: () => jsx(Chip, {}) },
      {
        id: 'directive',
        area: TRANSCRIPT_DIRECTIVE_AREA,
        data: {
          name: 'redline', // The agent writes ::redline{file="/path/to/document.md"}
          render: ({ attrs }) => {
            const file = String(attrs.file || '').trim()
            if (!file || !/\.(md|markdown)$/i.test(file)) return null
            return jsxs('div', {
              className: 'rl-card', style: { '--rl-line': 'var(--rl-change)', maxWidth: 460 }, children: [
                jsxs('div', { className: 'rl-kind', children: [jsx(KindIcon, { kind: 'change' }), 'guided review'] }),
                jsx('div', { className: 'rl-note', children: file }),
                jsx('div', { className: 'rl-foot', children: jsx(Button, {
                  size: 'sm',
                  onClick: () => host.openWorkspace('redline', {
                    title: 'redline',
                    dock: { pane: 'workspace', pos: 'right' },
                    minWidth: '420px',
                    render: () => jsx(RedlinePane, { ctx, file }),
                  }),
                  children: 'Review in Redline',
                }) }),
              ],
            })
          },
        },
      },
    ])
  },
}
