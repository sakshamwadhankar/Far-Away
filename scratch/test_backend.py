import urllib.request
import json
import asyncio
import websockets
import time

pipeline = {
    "schema_version": "2.0",
    "id": "00000000-0000-4000-a000-000000000099",
    "name": "API Test Pipeline",
    "version": "1.0.0",
    "nodes": [
        {
            "id": "in",
            "type": "input",
            "outputs": [{"name": "prompt", "type": "text"}],
        },
        {
            "id": "transform1",
            "type": "transform",
            "inputs": [{"name": "input1", "type": "text"}],
            "outputs": [{"name": "output", "type": "text"}],
            "config": {"system_prompt": "Hello {{ input1 }}! This is jinja2."}
        },
        {
            "id": "model_node",
            "type": "model",
            "endpoint_ref": "mock:default",
            "inputs": [{"name": "input", "type": "text"}],
            "outputs": [{"name": "output", "type": "text"}],
            "config": {"temperature": 0.7, "max_tokens": 20},
        },
        {
            "id": "out",
            "type": "output",
            "inputs": [{"name": "result", "type": "text"}],
        },
    ],
    "loops": [],
    "edges": [
        {"from": "in.prompt", "to": "transform1.input1"},
        {"from": "transform1.output", "to": "model_node.input"},
        {"from": "model_node.output", "to": "out.result"},
    ],
    "endpoints": {
        "mock:default": {"kind": "mock"},
    },
}

async def run_pipeline():
    # 1. Start run via POST
    payload = {
        "pipeline": pipeline,
        "inputs": {"in": {"prompt": "World"}}
    }
    
    print("Sending POST /pipelines/run...")
    req = urllib.request.Request(
        "http://127.0.0.1:8080/pipelines/run",
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer test'}
    )
    try:
        with urllib.request.urlopen(req) as res:
            result = json.loads(res.read())
            run_id = result["run_id"]
            print(f"Run started with ID: {run_id}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"Validation Error 422: {body}")
        return
        
    # 2. Connect to WS to run the pipeline
    print("Connecting to WebSocket...")
    ws_url = f"ws://127.0.0.1:8080/ws/run/{run_id}?token=test"
    
    async with websockets.connect(ws_url) as ws:
        # Wait for terminal event
        while True:
            msg = await ws.recv()
            data = json.loads(msg)
            print(data)
            if data["event"] in ["run_completed", "run_error", "run_halted", "budget_exceeded"]:
                print(f"Terminal event reached: {data['event']}")
                if data["event"] == "run_completed":
                    print("SUCCESS! Jinja2 successfully rendered.")
                else:
                    print("FAILED!")
                break

if __name__ == "__main__":
    time.sleep(2)
    asyncio.run(run_pipeline())
