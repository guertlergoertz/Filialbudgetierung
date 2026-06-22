# Git Workflow

## Commit Messages

```
<type>(<scope>): <description>

[optional body]
[optional footer]
```

Types: `feat` | `fix` | `refactor` | `test` | `docs` | `chore`

## Branch Strategy

- `master` / `main`: production-ready
- `feat/<name>`: new features
- `fix/<name>`: bug fixes

## PR Rules

- One concern per PR
- Tests must pass
- Self-review before requesting review
