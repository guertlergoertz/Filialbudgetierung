# Code Review Standards

## Review Checklist

### Correctness
- [ ] Logic matches requirements
- [ ] Edge cases handled (empty, null, boundary)
- [ ] Error handling present and appropriate
- [ ] No off-by-one errors
- [ ] Concurrent access considered

### Security
- [ ] No hardcoded credentials
- [ ] Input validation present
- [ ] SQL injection prevented (parameterized queries)
- [ ] XSS prevented (output escaping)
- [ ] Authentication/authorization checked

### Performance
- [ ] No N+1 queries
- [ ] Appropriate indexing
- [ ] No unnecessary loops/allocations
- [ ] Caching where appropriate

### Maintainability
- [ ] Names are descriptive
- [ ] Functions are single-purpose
- [ ] Comments explain WHY not WHAT
- [ ] No dead code
- [ ] Consistent style

### Testing
- [ ] Happy path tested
- [ ] Error cases tested
- [ ] Edge cases tested
- [ ] Tests are readable
- [ ] No test logic in production code

## Review Response Format

```
**Critical** (must fix):
- [issue]: [why it matters] → [suggestion]

**Important** (should fix):
- [issue]: [why it matters] → [suggestion]

**Minor** (consider):
- [issue]: [suggestion]

**Praise**:
- [what's done well]
```

## Self-Review Before Submitting

1. Read diff top-to-bottom as a reviewer
2. Run linter and fix all warnings
3. Run tests, ensure all pass
4. Check for debug/temporary code
5. Verify commit message is descriptive

## When Reviewing Others

- Assume good intent
- Ask questions before asserting errors
- Suggest, don't demand (unless critical)
- Acknowledge good solutions
- Focus on the code, not the person

## Auto-Approve Criteria

Changes that can skip detailed review:
- Documentation-only changes
- Dependency version bumps (patch level)
- Formatting changes from auto-formatter
- Test-only changes with no logic modifications
