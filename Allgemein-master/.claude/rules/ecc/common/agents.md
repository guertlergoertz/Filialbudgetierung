# Multi-Agent Architecture

## When to Use Sub-Agents

- **Parallel tasks**: Independent work streams (e.g., fix bug + write tests + update docs)
- **Isolation needed**: Risky operations needing separate context
- **Specialization**: Tasks benefiting from focused context
- **Long chains**: Multiple dependent steps exceeding context limits

## Agent Handoff Protocol

```markdown
## Task for Sub-Agent
**Context**: [minimal needed context]
**Goal**: [specific, measurable outcome]
**Constraints**: [what NOT to do]
**Success criteria**: [how to verify completion]
**Return**: [what to report back]
```

## Orchestrator Responsibilities

1. Decompose task into independent units
2. Assign clear ownership per agent
3. Define interfaces between agents
4. Verify outputs before integration
5. Handle failures gracefully

## Sub-Agent Best Practices

- Complete ONE thing well
- Report blockers immediately
- Don't assume context not given
- Verify your own output before returning

## Anti-Patterns

- Spawning agents for simple sequential tasks
- Giving agents overlapping responsibilities
- Missing error handling between agent handoffs
- Not defining success criteria upfront
