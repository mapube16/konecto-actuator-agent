---
name: recommending-actuators
description: Query and recommend Bettis Series 76 actuators by part number or natural-language requirements.
version: "1.0.0"
mcp_endpoint: http://localhost:8000/mcp/
transport: http
---

# Capabilities

Two tools are available via the MCP endpoint:

## `get_actuator`

Retrieve exact technical specifications for a Series 76 actuator by its Base Part Number.

**Input:** `part_number` (string) — e.g. `"763A00-11300000/A"`
**Output:** JSON block with torque, voltage, enclosure class, mounting pattern, and datasheet fields.

Query types handled:
- "What are the specs for part 763A00-11300000/A?"
- "Give me the torque rating for [part number]."
- "Is [part number] available in ATEX?"

## `recommend`

Find actuators that match natural-language technical requirements using semantic search.

**Input:** `requirements` (string) — free-text description of needs
**Output:** Ranked list of matching part numbers with key specifications and match rationale.

Query types handled:
- "Find an explosionproof actuator rated for 300 Nm at 220 VAC."
- "I need a quarter-turn unit suitable for a Class I Div 2 environment."
- "What actuators work with 24 VDC and need less than 100 Nm?"

---

# Example Invocations

## Part number lookup

```json
{
  "tool": "get_actuator",
  "arguments": {
    "part_number": "763A00-11300000/A"
  }
}
```

## Natural-language recommendation

```json
{
  "tool": "recommend",
  "arguments": {
    "requirements": "explosionproof quarter-turn actuator, 300 Nm, 220 VAC, ATEX rated"
  }
}
```

---

# Notes

- Rate limit: 30 requests/minute per client IP.
- The MCP server is stateless; conversation context lives in the `/api/conversation` endpoints, not MCP tools.
- All responses are plain UTF-8 text safe to embed directly in an LLM context window.
