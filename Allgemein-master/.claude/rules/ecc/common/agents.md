# Agent Coordination

## Overview
This rule defines how to coordinate multiple AI agents effectively.

## Principles
- Each agent should have a clear, single responsibility
- Agents should communicate through well-defined interfaces
- Avoid circular dependencies between agents
- Document agent capabilities and limitations

## Spawning Agents
- Only spawn agents when tasks genuinely benefit from parallelism
- Provide complete context in agent prompts
- Handle agent failures gracefully
- Collect and synthesize agent outputs

## Communication Patterns
- Use structured data formats for inter-agent communication
- Validate inputs and outputs at agent boundaries
- Log agent interactions for debugging
- Implement timeout and retry mechanisms
