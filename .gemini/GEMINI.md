# Global Development Rules

## Security (Non-Negotiable)

- Never hardcode credentials, API keys, or secrets in code
- Use environment variables (.env files) for all sensitive data
- Add .env to .gitignore immediately
- Implement input validation on all user inputs
- Use parameterized queries for database operations
- Apply OWASP Top 10 security measures

## Code Quality Standards

- Follow language-specific style guides (PEP 8, Airbnb JS, Google Style Guide)
- Write self-documenting code with clear naming conventions
- Apply SOLID principles and appropriate design patterns
- Maximum function length: 50 lines (unless justified)
- Minimum 80% test coverage for new code

## Documentation Requirements

- Always create/update README.md with setup instructions
- Document complex algorithms and business logic inline
- Create Architectural Decision Records (ADRs) for major choices
- Include usage examples in API documentation

## Testing Mandate

- Write tests before or alongside implementation (TDD preferred)
- Include unit, integration, and E2E tests where appropriate
- Use appropriate testing frameworks (Jest, Pytest, JUnit, etc.)

## Version Control

- Use Conventional Commits for commit messages
- Create meaningful branch names (feature/, bugfix/, hotfix/)
- Never commit sensitive data or large binary files

## Terminal Safety

- Explain commands before execution in Ask mode
- Request approval for destructive operations (rm, DROP, DELETE)
- Verify file paths before file operations

## Agent Behavior

- Generate production-ready, complete code (no TODOs)
- Use Plan Mode for complex tasks before implementation
- Explain architectural decisions and trade-offs
- Prioritize maintainability over clever optimizations
