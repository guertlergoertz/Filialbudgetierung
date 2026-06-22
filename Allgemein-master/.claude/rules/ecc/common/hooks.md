# Claude Code Hooks

## Available Hook Points

- `PreToolUse`: Before any tool call
- `PostToolUse`: After any tool call  
- `Notification`: On idle/notification events
- `Stop`: When Claude finishes responding

## Hook Best Practices

- Keep hooks fast (<2s)
- Exit 0 for success, non-zero to block
- Use `stderr` for user-visible messages
- Log to files for debugging

## Common Hook Patterns

```json
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "Bash",
      "hooks": [{"type": "command", "command": "validate_bash.sh"}]
    }]
  }
}
```

## Anti-Patterns

- Blocking hooks that wait for user input
- Hooks that modify Claude’s output
- Long-running hooks without timeouts
