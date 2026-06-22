# Coding Style Guide

## Universal Principles

### Names
- **Variables/functions**: describe what, not how (`user_count` not `n`, `fetch_user` not `do_thing`)
- **Booleans**: use `is_`, `has_`, `can_`, `should_` prefix
- **Constants**: SCREAMING_SNAKE_CASE
- **Avoid**: abbreviations (except domain-standard), single letters (except loop vars)

### Functions
- One function = one responsibility
- Max ~30 lines (if longer, split)
- Parameters: max 4 (use object/struct if more needed)
- Return early to reduce nesting

```python
# Bad
def process(data):
    if data:
        if data.valid:
            result = transform(data)
            if result:
                return result
    return None

# Good
def process(data):
    if not data or not data.valid:
        return None
    result = transform(data)
    return result
```

### Comments
- Comment WHY, not WHAT
- Keep comments up-to-date with code
- TODO format: `# TODO(name): description`
- Avoid obvious comments

```python
# Bad
x = x + 1  # increment x

# Good
x = x + 1  # offset for 1-based indexing in Excel output
```

### Error Handling
- Never silently swallow exceptions
- Log errors with context
- Fail fast at boundaries, recover gracefully inside

```python
# Bad
try:
    result = risky_op()
except:
    pass

# Good
try:
    result = risky_op()
except ValueError as e:
    logger.error("risky_op failed for input %s: %s", input_val, e)
    raise
```

### Constants vs Magic Numbers
```python
# Bad
if age > 18:
    ...

# Good
MIN_ADULT_AGE = 18
if age > MIN_ADULT_AGE:
    ...
```

## File Organization

- One concept per file
- Imports: stdlib → third-party → local (separated by blank line)
- Public API at top, helpers at bottom
- Max file length: ~300 lines (split into modules if longer)
