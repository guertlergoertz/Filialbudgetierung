# Hooks and Automation

## Pre-commit Hooks
- Run linters before commit
- Run unit tests before commit
- Check for secrets/credentials
- Validate commit message format

## CI/CD Hooks
- Trigger on push to any branch
- Run full test suite
- Deploy to staging on merge to develop
- Deploy to production on merge to master

## Custom Hooks
- Document all custom hooks
- Keep hooks fast (under 30 seconds)
- Provide clear error messages
- Allow bypass for emergency situations (with logging)
