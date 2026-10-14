from fastapi import FastAPI
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from go2_llm_agent.agent import graph, AgentState

app = FastAPI()

class CommandIn(BaseModel):
    text: str

state: AgentState = {"messages": [], "plan": None, "step_idx": 0}

@app.post("/command")
async def command(cmd: CommandIn):
    print("Received transcript:", cmd.text)

    # Fresh state every request — no memory of previous commands
    fresh_state: AgentState = {
        "messages": [HumanMessage(content=cmd.text)],
        "plan": None,
        "step_idx": 0
    }

    result = graph.invoke(fresh_state)

    return {"ok": True, "text": cmd.text}


def main():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
