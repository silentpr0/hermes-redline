---
name: reading
description: Use when a redline batch arrives from the desktop panel, or after delivering a Markdown document the user will read or review.
version: 1.0.0
metadata:
  hermes:
    tags: [desktop, review, markdown]
---

# redline (guided Markdown review)

This bundled skill is available as `redline:reading`.

## Emit the card

After writing a Markdown file the user will likely read or review (report, plan, doc, manuscript, draft PR/README — anything written "for them to see"), end the response with a lone line:

```
::redline{file="/absolute/path.md"}
```

The installed plugin renders a card in the transcript; one click opens the document in the Redline review pane docked beside the chat. Do not emit for trivial Markdown (sidecars, scratch, internal notes, READMEs of repos).

When the plugin's hooks are active they append the directive automatically for files written with `write_file`/`patch` in the turn; check the response already contains `::redline{` before adding one manually — never emit twice.

## Handle a batch

A user message starting with `🔴 redline — review of <path> (N notes):` is a review batch from the pane:

```
1. [comment|question|change request] quote: "..."
   → the user's note
```

1. Read the document first — quotes may be truncated; locate the block by prefix.
2. `question` → answer in chat. `change request` → edit the file (within the requested scope). `comment` → discuss/adjust.
3. After applying a change, mark the item `"status": "resolved"` in the sidecar `<file>.md.redline.json`.
4. Answer as a numbered list mirroring the batch (1→1, 2→2).
5. Never delete sidecar items unless the user asks.
