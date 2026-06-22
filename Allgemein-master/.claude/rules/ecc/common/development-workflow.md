# Development Workflow

## Branch Strategy
- `master` / `main`: production-ready code
- Feature branches: `feature/description`
- Bug fixes: `fix/description`
- Always branch from the latest master

## Development Cycle
1. Create feature branch
2. Implement changes with tests
3. Run full test suite
4. Create pull request
5. Code review
6. Merge to master

## Commit Standards
- Write clear, descriptive commit messages
- One logical change per commit
- Reference issue numbers when applicable
- Use present tense: "Add feature" not "Added feature"

## Testing Requirements
- Unit tests for all new functions
- Integration tests for new features
- All tests must pass before merge
- Maintain or improve code coverage
