#!/usr/bin/env python3
"""
Verification script to test initialization, data flow, context formatting,
and tool call parsing. This script validates all components before production use.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.engine import BaseContext, ReActContext, Message
from core.responses import BaseResponse, ReActResponse
from core.tools import execute_command


def separator(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


def verify_response_model():
    """Verify response model instructions generation."""
    separator("RESPONSE MODEL VERIFICATION")
    
    # Test JSON format instructions
    json_instructions = ReActResponse.get_instructions("json")
    print("JSON Format Instructions (first 500 chars):")
    print(json_instructions[:500])
    print("...")
    
    print("\n" + "-"*40 + "\n")
    
    # Test TOON format instructions
    toon_instructions = ReActResponse.get_instructions("toon")
    print("TOON Format Instructions (first 500 chars):")
    print(toon_instructions[:500])
    print("...")
    
    # Test schema structure
    instance = ReActResponse.model_construct()
    schema = instance.representation_structure()
    print("\n" + "-"*40)
    print("Schema Structure:")
    print(schema)


def verify_base_context():
    """Verify BaseContext initialization and prompt building."""
    separator("BASE CONTEXT VERIFICATION")
    
    # Create a simple context
    ctx = BaseContext(
        name="TestContext",
        description="A test context for verification.",
        system_instructions="default",
        model_id="lms/openai/gpt-oss-20b",
        tools=[execute_command],
        response_model=BaseResponse,
        response_format="json"
    )
    
    report = ctx.initialization_report()
    print("Initialization Report:")
    for k, v in report.items():
        print(f"  {k}: {v}")
    
    # Verify system prompt was loaded
    print(f"\nSystem Prompt Loaded: {bool(ctx._system_prompt)}")
    print(f"System Prompt Preview: {ctx._system_prompt[:100]}..." if ctx._system_prompt else "Empty")
    
    # Verify tool instructions
    print(f"\nTool Instructions Generated: {bool(ctx._tool_instructions)}")
    print(f"Tool Instructions Preview:\n{ctx._tool_instructions[:300]}..." if ctx._tool_instructions else "Empty")
    
    # Verify response instructions
    print(f"\nResponse Instructions Generated: {bool(ctx._response_instructions)}")
    
    # Test prompt rendering
    print("\n" + "-"*40)
    print("Full Rendered Prompt (for 'Hello'):")
    prompt = ctx.render("Hello")
    print(prompt[:800])
    print("..." if len(prompt) > 800 else "")
    print(f"\n[Total prompt length: {len(prompt)} chars]")


def verify_react_context():
    """Verify ReActContext initialization and tool parsing."""
    separator("REACT CONTEXT VERIFICATION")
    
    ctx = ReActContext(
        name="TestReActContext",
        description="ReAct loop test context.",
        system_instructions="command_line_agent",
        model_id="lms/openai/gpt-oss-20b",
        tools=[execute_command],
        response_format="json",
        max_iterations=3
    )
    
    report = ctx.initialization_report()
    print("ReAct Context Report:")
    for k, v in report.items():
        print(f"  {k}: {v}")
    
    # Test tool call parsing
    print("\n" + "-"*40)
    print("Tool Call Parsing Tests:")
    
    test_cases = [
        ('execute_command({"command": "ls -la"})', "JSON args"),
        ("execute_command(command='ls -la')", "Python kwargs"),
        ('navigate_page({"url": "https://google.com"})', "URL arg"),
        ("CommandLineAgent(query='List files')", "Sub-agent call"),
        ('tool_a({"x": 1})\ntool_b({"y": 2})', "Multiple tools"),
    ]
    
    for call_str, desc in test_cases:
        name, args = ctx._parse_tool_call(call_str.split('\n')[0])
        print(f"  [{desc}] '{call_str[:40]}...'")
        print(f"    -> name={name}, args={args}")


def verify_response_parsing():
    """Verify response parsing from raw model output."""
    separator("RESPONSE PARSING VERIFICATION")
    
    # Test JSON parsing
    json_output = '''```json
{
    "rephrase": "User wants to list files",
    "reverse": "Check if directory exists",
    "action": "tool",
    "answer": "execute_command({\\"command\\": \\"ls\\"})"
}
```'''
    
    print("JSON Parsing Test:")
    print(f"Input: {json_output[:100]}...")
    try:
        parsed = ReActResponse.from_raw(json_output, "json")
        print(f"✓ Parsed successfully:")
        print(f"  rephrase: {parsed.rephrase}")
        print(f"  action: {parsed.action}")
        print(f"  answer: {parsed.answer}")
    except Exception as e:
        print(f"✗ Parse failed: {e}")
    
    print("\n" + "-"*40 + "\n")
    
    # Test TOON parsing
    toon_output = '''TOON/1
rephrase: "User wants to check weather"
reverse: "Need API or browser access"
action: "answer"
answer: "The weather today is sunny."'''
    
    print("TOON Parsing Test:")
    print(f"Input: {toon_output}")
    try:
        parsed = ReActResponse.from_raw(toon_output, "toon")
        print(f"✓ Parsed successfully:")
        print(f"  rephrase: {parsed.rephrase}")
        print(f"  action: {parsed.action}")
        print(f"  answer: {parsed.answer}")
    except Exception as e:
        print(f"✗ Parse failed: {e}")


async def verify_tool_execution():
    """Verify tool execution flow."""
    separator("TOOL EXECUTION VERIFICATION")
    
    # Test direct execute_command
    print("Testing execute_command tool:")
    result = await execute_command("echo 'Hello from verification script'")
    print(f"  Result: {result}")


async def verify_agent_initialization():
    """Verify agent initialization from team folder."""
    separator("AGENT INITIALIZATION VERIFICATION")
    
    from team.command_line_agent import initialize_command_line_agent
    
    print("Initializing CommandLineAgent...")
    cli_agent = await initialize_command_line_agent()
    
    report = cli_agent.initialization_report()
    print("CommandLineAgent Report:")
    for k, v in report.items():
        print(f"  {k}: {v}")
    
    # Verify the static context contains expected sections
    static_ctx = cli_agent._static_context
    checks = [
        ("System prompt", "Terminal Master" in static_ctx or "Unix veteran" in static_ctx),
        ("Tool instructions", "AVAILABLE TOOLS" in static_ctx),
        ("Response protocol", "RESPONSE PROTOCOL" in static_ctx),
        ("execute_command tool", "execute_command" in static_ctx),
    ]
    
    print("\nStatic Context Checks:")
    for name, passed in checks:
        status = "✓" if passed else "✗"
        print(f"  {status} {name}")


async def verify_sub_agent_delegation():
    """Verify orchestrator can delegate to sub-agents."""
    separator("SUB-AGENT DELEGATION VERIFICATION")
    
    from team.command_line_agent import initialize_command_line_agent
    
    cli_agent = await initialize_command_line_agent()
    cli_agent.name = "CommandLineAgent"
    
    # Create a mock orchestrator
    orchestrator = ReActContext(
        name="Orchestrator",
        description="Main orchestrator for delegation test.",
        system_instructions=(
            "You are an orchestrator. Delegate file tasks to CommandLineAgent."
        ),
        model_id="lms/openai/gpt-oss-20b",
        tools=[cli_agent],
        response_format="json",
        max_iterations=2
    )
    
    report = orchestrator.initialization_report()
    print("Orchestrator Report:")
    for k, v in report.items():
        print(f"  {k}: {v}")
    
    # Check tool instructions include the sub-agent
    print("\nSub-agent in tool instructions:", "CommandLineAgent" in orchestrator._tool_instructions)
    
    # Test prompt rendering includes sub-agent
    prompt = orchestrator.render("List files in current directory")
    print(f"Prompt includes CommandLineAgent: {'CommandLineAgent' in prompt}")
    print(f"\nOrchestrator prompt preview (first 600 chars):\n{prompt[:600]}...")


async def main():
    print("\n" + "="*60)
    print("  APPLESHORTCUTS VERIFICATION SUITE")
    print("="*60)
    
    verify_response_model()
    verify_base_context()
    verify_react_context()
    verify_response_parsing()
    await verify_tool_execution()
    await verify_agent_initialization()
    await verify_sub_agent_delegation()
    
    separator("VERIFICATION COMPLETE")
    print("All verification steps completed. Review output for any ✗ marks.")


if __name__ == "__main__":
    asyncio.run(main())
