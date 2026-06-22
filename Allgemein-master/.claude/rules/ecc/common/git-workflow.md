# Git Workflow

## Basic Commands
- Always pull before starting work
- Commit frequently with clear messages
- Push to remote regularly
- Never force push to shared branches

## Merge Strategy
- Prefer rebase for feature branches
- Use merge commits for release branches
- Squash commits when appropriate
- Resolve conflicts carefully

## Branch Naming
- Use lowercase with hyphens
- Be descriptive but concise
- Include ticket number if applicable
- Examples: `feature/user-authentication`, `fix/login-bug-123`

## Pre-commit Checklist
- [ ] Tests pass
- [ ] Code linted
- [ ] No debug code
- [ ] No secrets committed
- [ ] Documentation updated
