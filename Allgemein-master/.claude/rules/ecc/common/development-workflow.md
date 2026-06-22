# Development Workflow

## Before Starting Any Task

1. **Understand the requirement** – ask if unclear
2. **Check existing code** – search before creating
3. **Plan before coding** – outline approach for complex tasks
4. **Identify test cases** – what does done look like?

## Implementation Loop

```
Write failing test → Implement → Pass test → Refactor → Commit
```

For bug fixes:
```
Reproduce bug → Write failing test → Fix → Pass test → Commit
```

## Code Quality Gates

Before marking any task done:
- [ ] All tests pass
- [ ] No linter errors
- [ ] No debug/temp code left
- [ ] Docs updated if behavior changed
- [ ] Commit message is descriptive

## Handling Uncertainty

**When you’re unsure:**
1. State your uncertainty explicitly
2. Propose the safest approach
3. Ask for confirmation before destructive operations

**Never:**
- Guess at requirements and implement anyway
- Make breaking changes without flagging them
- Delete data/files without explicit instruction

## Stuck? Escalation Path

1. Re-read requirements
2. Check existing similar code in codebase
3. Search documentation
4. State the blocker clearly and ask for help

## Task Completion Checklist

```
[ ] Feature works as specified
[ ] Edge cases handled
[ ] Tests written and passing
[ ] No regressions (existing tests still pass)
[ ] Code reviewed (self-review at minimum)
[ ] Changes committed with good message
[ ] PR/issue updated if applicable
```
