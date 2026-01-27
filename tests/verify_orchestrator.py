import asyncio
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.orchestrator import initialize_orchestrator
from core.engine import ReActContext

async def verify():
    print("🚀 Starting Orchestrator Verification...")
    
    try:
        # 1. Initialize
        print("1. Initializing Orchestrator...")
        orchestrator = await initialize_orchestrator()
        
        # 2. Check Identity
        print(f"   Name: {orchestrator.name}")
        assert orchestrator.name == "Orchestrator", f"Expected name 'Orchestrator', got '{orchestrator.name}'"
        
        # 3. Check Tools
        print("2. Verifying Sub-Agents...")
        tool_names = [t.name if hasattr(t, 'name') else t.__name__ for t in orchestrator.tools]
        print(f"   Tools found: {tool_names}")
        
        assert "CommandLineAgent" in tool_names, "CommandLineAgent missing"
        assert "ChromeAgent" in tool_names, "ChromeAgent missing"
        
        # 4. Check Prompt Rendering
        print("3. Verifying Prompt Construction...")
        prompt = orchestrator.render("Hello")
        
        # Check for new prompt instructions
        if "Operational Protocol" not in prompt:
            print("WARNING: New prompt instructions not found in rendered output!")
        else:
            print("   ✅ New robust prompt instructions detected.")
            
        # Check description propagation
        if "Delegate complex tasks to CommandLineAgent" not in prompt:
             print("WARNING: Enhanced tool instructions might be missing.")
        else:
             print("   ✅ Enhanced tool instructions detected.")

        print("\n✅ Verification Successful!")
        await orchestrator.close()
        return True
        
    except Exception as e:
        print(f"\n❌ Verification Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(verify())
    sys.exit(0 if success else 1)
