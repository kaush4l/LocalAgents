from core.engine import ReActContext, Message
from core.responses import ReActResponse, BaseResponse


def example_tool(query):
    """Search the web for information."""
    return f"Search results for: {query}"

ctx = ReActContext(
    name=f"TestEngine_toon",
    system_instructions="default",
    model_id="lms/zai-org/glm-4.7-flash",
    response_model=ReActResponse,
    response_format='toon',
)

def main():
    # Run format comparison test (requires local LLM server)
    while True:
        user_input = input("Enter your query (or 'exit' to quit): ")
        response = ctx.invoke(user_input)
        print("Model Response:")
        print(response)

if __name__ == "__main__":
    main()
