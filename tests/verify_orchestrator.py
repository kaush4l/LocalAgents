import asyncio
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.orchestrator import orchestrator
from core.engine import ReActContext

async def verify():
    print("🚀 Starting Orchestrator Verification...")
    
    try:
        # 1. Check Identity
        print("1. Verifying Orchestrator...")
        print(f"   Name: {orchestrator.name}")
        assert orchestrator.name == "orchestrator", f"Expected name 'orchestrator', got '{orchestrator.name}'"
        
        # 2. Check Tools
        print("2. Verifying Sub-Agents...")
        tool_names = [t.name if hasattr(t, 'name') else t.__name__ for t in orchestrator.tools]
        print(f"   Tools found: {tool_names}")
        
        assert "command_line_agent" in tool_names, "command_line_agent missing"
        assert "chrome_agent" in tool_names, "chrome_agent missing"
        
        # 4. Check Prompt Rendering
        print("3. Verifying Prompt Construction...")
        prompt = orchestrator.render("Hello")
        
        # Check for new prompt instructions
        if "Operational Protocol" not in prompt:
            print("WARNING: New prompt instructions not found in rendered output!")
        else:
            print("   ✅ New robust prompt instructions detected.")
            
        # Check description propagation
        if "Delegate complex tasks to command_line_agent" not in prompt:
             print("WARNING: Enhanced tool instructions might be missing.")
        else:
             print("   ✅ Enhanced tool instructions detected.")

        print("\n✅ Verification Successful!")
    sys.exit(0 if success else 1)
