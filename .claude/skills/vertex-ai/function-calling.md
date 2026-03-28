# Function Calling (Tool Use)

Function calling lets Gemini models request external tool invocations by returning structured data with tool names and parameters. Your app executes the tools and returns results.

## SDK imports (this project)

```python
from google import genai
from google.genai import types as genai_types
```

All declarations use `genai_types` — not `vertexai.generative_models`.

## Declaring functions

### Using genai_types (this project's pattern)

```python
tool_declarations = genai_types.Tool(
    function_declarations=[
        genai_types.FunctionDeclaration(
            name="confirm_location",
            description="Confirm the user's location address.",
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={
                    "address": genai_types.Schema(
                        type="STRING",
                        description="Confirmed address",
                    ),
                },
                required=["address"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="set_emergency_type",
            description="Set the type of emergency.",
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={
                    "emergency_type": genai_types.Schema(
                        type="STRING",
                        enum=["MEDICAL", "FIRE", "POLICE", "GAS", "OTHER"],
                    ),
                },
                required=["emergency_type"],
            ),
        ),
    ]
)
```

### Schema types

| Type | genai_types.Schema usage |
|------|--------------------------|
| String | `genai_types.Schema(type="STRING")` |
| String enum | `genai_types.Schema(type="STRING", enum=["A", "B", "C"])` |
| Integer | `genai_types.Schema(type="INTEGER")` |
| Boolean | `genai_types.Schema(type="BOOLEAN")` |
| Number (float) | `genai_types.Schema(type="NUMBER")` |
| Nested object | `genai_types.Schema(type="OBJECT", properties={...})` |

### No-parameter tools

For tools that take no arguments, pass an empty properties dict:

```python
genai_types.FunctionDeclaration(
    name="get_emergency_brief",
    description="Get the full emergency briefing.",
    parameters=genai_types.Schema(type="OBJECT", properties={}),
)
```

### Optional parameters

Omit the field from `required` to make it optional:

```python
genai_types.FunctionDeclaration(
    name="set_clinical_fields",
    description="Set clinical fields. All parameters are optional.",
    parameters=genai_types.Schema(
        type="OBJECT",
        properties={
            "conscious": genai_types.Schema(type="BOOLEAN"),
            "breathing": genai_types.Schema(type="BOOLEAN"),
            "victim_count": genai_types.Schema(type="INTEGER"),
        },
        # no `required` — all optional
    ),
)
```

## Using tools in Live sessions

Pass tools in `LiveConnectConfig`:

```python
config = genai_types.LiveConnectConfig(
    response_modalities=["TEXT"],
    system_instruction=genai_types.Content(
        parts=[genai_types.Part(text="System prompt")]
    ),
    tools=[tool_declarations],
)

async with client.aio.live.connect(model="gemini-2.0-flash-live-001", config=config) as session:
    async for response in session.receive():
        if response.tool_call:
            for fc in response.tool_call.function_calls:
                result = await handle(fc.name, fc.args or {})
                await session.send(
                    input=genai_types.LiveClientToolResponse(
                        function_responses=[
                            genai_types.FunctionResponse(
                                name=fc.name,
                                response={"result": result},
                            )
                        ]
                    )
                )
```

## Using tools in standard generation

```python
from google.genai.types import FunctionDeclaration, Tool, Schema

get_weather = FunctionDeclaration(
    name="get_current_weather",
    description="Get the current weather in a given location",
    parameters=Schema(
        type="OBJECT",
        properties={"location": Schema(type="STRING")},
        required=["location"],
    ),
)

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="What's the weather in Boston?",
    config={"tools": [Tool(function_declarations=[get_weather])]},
)

# Process function calls from response
for fc in response.candidates[0].function_calls:
    print(f"Call: {fc.name}({fc.args})")
```

## Returning function results (standard generation)

```python
from google.genai.types import Content, Part

# Build the conversation with function results
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=[
        Content(role="user", parts=[Part.from_text("What's the weather?")]),
        response.candidates[0].content,  # model's function call
        Content(role="user", parts=[
            Part.from_function_response(
                name="get_current_weather",
                response={"contents": {"temperature": 20, "unit": "C"}},
            )
        ]),
    ],
    config={"tools": [Tool(function_declarations=[get_weather])]},
)
```

## Parallel function calling

Models can propose multiple function calls at once. Iterate over all of them and return all results together:

```python
function_response_parts = []
for fc in response.candidates[0].function_calls:
    result = dispatch(fc.name, fc.args)
    function_response_parts.append(
        Part.from_function_response(name=fc.name, response={"contents": result})
    )
```

## Constraints

- **Max 512 function declarations** per request
- **Parameter format**: OpenAPI 3.0.3 schema
- **Temperature**: Set to 0 for deterministic function calling
- Always validate function names and arguments before execution

## Best practices

- Write descriptive `description` fields — the model uses them to decide when to call the tool
- Specify expected data formats in parameter descriptions
- Mark mandatory parameters in `required`
- Return complete results to the model so it has context for follow-up
- Use `enum` to constrain string parameters to valid values
