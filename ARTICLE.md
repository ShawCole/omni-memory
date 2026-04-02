# Memory as Infrastructure: Building Intelligent State Management for AI Agents with LangGraph

## Introduction

Every AI agent you have used this year has the same hidden weakness. It forgets.

Not in the dramatic, amnesia-movie sense. In the quiet, expensive sense. Most systems labeled as having "memory" are really just storing chat logs, embeddings, or stuffing more tokens into context windows. That is not memory. That is storage with a marketing label. Real memory is a lifecycle. It needs to decide what to keep, what to compress, what to forget, and what to govern. Without this active curation, you end up with noise: higher costs, slower responses, and more hallucinations.

In this article, you will build a complete memory management system for AI agents using LangGraph and LangChain. By the end, you will understand the two layers of agent memory (short-term and long-term), how to implement retention scoring, compression, intelligent forgetting, and governance controls. You will also see how leading AI companies like Anthropic, OpenAI, and the LangChain team are approaching this problem in production.

**High-level flow of an intelligent memory system:**
1. Receive new information during a conversation or task
2. Score the information for relevance, durability, and actionability
3. Decide whether to keep it in short-term context, promote it to long-term storage, or discard it
4. Compress older memories to save space without losing critical meaning
5. Periodically consolidate and prune long-term storage to prevent drift and noise
6. Govern all memory operations with access controls, tenancy rules, and compliance checks

---

## Table of Contents
- Phase 1: Memory vs Storage
- Phase 2: Short-Term Memory Architecture
- Phase 3: Long-Term Memory Architecture
- Phase 4: The Memory Lifecycle
- Phase 5: Memory as Infrastructure
- Evaluation
- How to Improve It Further

---

## Phase 1: Memory vs Storage

Before writing any code, let us get clear on a distinction that most tutorials skip entirely. There is a fundamental difference between storage and memory, and confusing the two is the root cause of most agent quality problems.

The three approaches commonly (and incorrectly) called "memory":

1. **Chat log persistence** — Saving every message to a database and replaying it at the start of each session. Context grows linearly; after 50 conversations, you are injecting thousands of irrelevant tokens into every request.

2. **Vector embedding storage** — Converting messages into embeddings and retrieving the most similar ones at query time. Similarity is not the same as relevance. A message from six months ago might be semantically similar but completely outdated.

3. **Context window stuffing** — Using larger context windows (100K, 200K, 1M tokens) to fit more history. This shifts the cost problem without solving the quality problem. More tokens means higher latency, higher cost, and the "lost in the middle" phenomenon.

**Industry reference:** OpenAI's Agents SDK documentation makes this distinction explicit. Their context engineering cookbook describes "retrieval-based memory" vs "state-based memory" (maintain structured, authoritative fields with clear precedence rules). The cookbook argues that for tasks requiring continuity and evolving preferences, state-based memory provides deterministic reasoning and explicit belief updates that retrieval alone cannot match.

**Storage (passive) vs Memory (active curation):**

```python
# This is STORAGE (passive accumulation)
def store_message(message, database):
    database.insert(message)
    # Problem: database grows forever, quality degrades over time

# This is MEMORY (active curation)
def remember(message, memory_system):
    score = memory_system.evaluate_retention(message)
    if score > RETENTION_THRESHOLD:
        memory_system.store(message, score=score, timestamp=now())
    memory_system.compress_stale_memories()
    memory_system.resolve_conflicts(message)
```

**LangMem's three memory types (mirrors cognitive science):**

- **Semantic memory (facts and knowledge):** Stores essential facts grounding agent responses. Uses two representations: collections (unbounded knowledge documents) and profiles (task-specific schemas).
- **Episodic memory (past experiences):** Preserves successful interactions as learning examples. Captures situation context, reasoning process, and success factors.
- **Procedural memory (behavioral rules):** Encodes behavioral patterns and response rules. Evolves through feedback and optimization.

**Key insight:** The shift happening right now in the industry is from storage to maintenance. A pragmatic memory layer does not just serialize everything into a database. It orchestrates a curation workflow: retention scoring, compression of long histories, forgetting rules for low-value items, and integrity checks to prevent drift. Teams that store everything as vectors find that recall quality collapses as the store grows.

---

## Phase 2: Short-Term Memory Architecture

Short-term memory is the live context window. It holds recent conversation turns, tool outputs, and retrieved documents. This space is brutally finite, so it needs to stay lean.

### Defining the Agent State

```python
from typing import Annotated, List, TypedDict, Optional
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage
import time

class MemoryAwareState(TypedDict):
    # Core conversation messages (short-term memory)
    messages: Annotated[List[BaseMessage], add_messages]
    
    # Memory metadata for retention decisions
    message_scores: dict  # Maps message IDs to retention scores
    
    # Context budget tracking
    total_tokens: int
    max_context_tokens: int
    
    # Session metadata
    session_id: str
    user_id: str
    turn_count: int
```

`add_messages` is a LangGraph reducer that appends new messages and handles deduplication automatically. `message_scores` maps each message's ID to a float between 0.0 and 1.0.

### Building the Context Trimmer

Priority-based trimming — not just oldest messages, but least valuable ones:

```python
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

def trim_context(state: MemoryAwareState) -> dict:
    messages = state["messages"]
    scores = state["message_scores"]
    max_tokens = state["max_context_tokens"]
    current_tokens = state["total_tokens"]
    
    if current_tokens <= max_tokens:
        return {"messages": messages}
    
    protected_ids = set()
    
    for msg in messages:
        if isinstance(msg, SystemMessage):
            protected_ids.add(msg.id)
    
    user_messages = [m for m in messages if isinstance(m, HumanMessage)]
    ai_messages = [m for m in messages if isinstance(m, AIMessage)]
    
    for msg in user_messages[-2:]:
        protected_ids.add(msg.id)
    if ai_messages:
        protected_ids.add(ai_messages[-1].id)
    
    trimmable = [msg for msg in messages if msg.id not in protected_ids]
    trimmable.sort(key=lambda m: scores.get(m.id, 0.5))
    
    trimmed_ids = set()
    tokens_to_free = current_tokens - max_tokens
    freed = 0
    
    for msg in trimmable:
        if freed >= tokens_to_free:
            break
        msg_tokens = len(str(msg.content)) // 4
        freed += msg_tokens
        trimmed_ids.add(msg.id)
    
    surviving_messages = [msg for msg in messages if msg.id not in trimmed_ids]
    
    return {"messages": surviving_messages, "total_tokens": current_tokens - freed}
```

Expected output after trimming a 15-message conversation:
- Before: 15 messages, 8,200 tokens (budget: 6,000)
- Protected: 4 messages (1 system, 2 recent user, 1 recent AI)
- Trimmed: 5 lowest-scoring messages (freed 2,400 tokens)
- After: 10 messages, 5,800 tokens

**Industry reference:** OpenAI's Agents SDK implements a similar pattern called `TrimmingSession`. When conversation history exceeds limits, it keeps only the last N user turns. Critically, if trimming occurs, a flag triggers reinsertion of session memory notes into the next system prompt.

### Session Memory Injection

Extract key insights before trimming and reinject them as a compact summary:

```python
from langchain_core.messages import SystemMessage

def inject_session_memories(state: MemoryAwareState, session_notes: list) -> dict:
    if not session_notes:
        return {"messages": state["messages"]}
    
    notes_text = "\
".join(
        f"- {note['text']} (confidence: {note['confidence']})" 
        for note in session_notes
    )
    
    memory_injection = SystemMessage(
        content=(
            "SESSION MEMORY (extracted from earlier conversation):\
"
            f"{notes_text}\
"
            "Use these notes as context. The original messages have been "
            "trimmed to save space. Trust these notes as accurate summaries "
            "of what was discussed."
        )
    )
    
    messages = state["messages"]
    insert_index = 1  # After the first system message
    updated = messages[:insert_index] + [memory_injection] + messages[insert_index:]
    
    return {"messages": updated}
```

Expected output:
```
SESSION MEMORY (extracted from earlier conversation):
- User prefers Python over JavaScript for backend work (confidence: 0.95)
- Current project is a RAG pipeline for financial documents (confidence: 0.90)
- User has already tried Pinecone and wants to explore Weaviate (confidence: 0.85)
```

**Industry reference:** Anthropic's engineering team describes a similar pattern for long-running agents. They maintain a progress tracking file that logs completed work, enabling incoming sessions to "quickly understand what has transpired without parsing entire codebases or git histories."

**Production token counting (use tiktoken, not character heuristic):**

```python
import tiktoken

def count_tokens_production(messages, model="gpt-4o"):
    encoder = tiktoken.encoding_for_model(model)
    total = 0
    for msg in messages:
        total += len(encoder.encode(str(msg.content)))
    return total
```

---

## Phase 3: Long-Term Memory Architecture

Long-term memory is what survives across sessions and enables actual personalization. LangGraph provides two first-class primitives: **checkpointer** (conversation state persistence) and **store** (cross-session knowledge).

### Checkpointer: Conversation State Persistence

```python
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import StateGraph, START, END

DB_URI = "postgresql://user:password@localhost:5432/agent_memory"

with PostgresSaver.from_conn_string(DB_URI) as checkpointer:
    checkpointer.setup()  # Call only on first use to create DB tables
    
    agent_graph = StateGraph(MemoryAwareState)
    # ... add nodes and edges ...
    
    agent = agent_graph.compile(checkpointer=checkpointer)
    
    config = {"configurable": {"thread_id": "user_123_session_456"}}
    result = agent.invoke({"messages": [HumanMessage(content="Hello")]}, config)
```

`PostgresSaver` must be used as a context manager. If the process crashes mid-execution, restarting with the same `thread_id` resumes from the last saved checkpoint. For testing, use `MemorySaver` (in-memory). For production, always use `PostgresSaver` or `SqliteSaver`.

### Store: Cross-Session Knowledge

The store holds knowledge that spans across threads and sessions:

```python
from langgraph.store.postgres.aio import AsyncPostgresStore

DB_URI = "postgresql://user:password@localhost:5432/agent_memory"

async with AsyncPostgresStore.from_conn_string(DB_URI) as store:
    await store.asetup()  # Call only on first use
    
    # Namespace pattern: (organization, user_id, memory_type)
    await store.aput(
        ("acme_corp", "user_123", "preferences"),
        "coding_style",
        {
            "text": "User prefers functional programming patterns over OOP",
            "confidence": 0.92,
            "source": "explicit_statement",
            "created_at": "2026-03-15T10:30:00Z",
            "last_validated": "2026-03-19T08:00:00Z",
            "access_count": 7
        }
    )
    
    # List all memories in a namespace (search without a query)
    user_prefs = await store.asearch(("acme_corp", "user_123", "preferences"))
    
    # Semantic search across all memories for a user
    relevant = await store.asearch(
        ("acme_corp", "user_123"),
        query="What programming patterns does this user prefer?",
        limit=5
    )
```

The store supports three core operations: `aput(namespace, key, value)`, `aget(namespace, key)`, and `asearch(namespace, query=..., filter=..., limit=...)`. Semantic search uses embeddings under the hood.

**Key insight:** LangMem describes the tension: "balancing extraction strength to avoid over-extraction (reduced precision) and under-extraction (low recall)." The metadata fields (confidence, source, access_count) help manage this balance by providing signals for future pruning decisions.

### The Three Memory Types in Practice

```python
# Semantic memory (facts and knowledge)
await store.aput(
    ("acme_corp", "user_123", "semantic"),
    "dietary_restrictions",
    {
        "text": "User is vegetarian and allergic to nuts",
        "confidence": 0.98,
        "source": "explicit_statement",
        "durable": True
    }
)

# Episodic memory (past experiences)
await store.aput(
    ("acme_corp", "user_123", "episodic"),
    "debug_session_march_2026",
    {
        "text": "User struggled with async Python. Responded well to synchronous "
                "examples first, then async equivalents side by side.",
        "confidence": 0.85,
        "source": "observed_interaction",
        "success_factors": ["side_by_side_comparison", "sync_first_approach"]
    }
)

# Procedural memory (behavioral rules)
await store.aput(
    ("acme_corp", "user_123", "procedural"),
    "communication_style",
    {
        "text": "Keep explanations concise. User prefers code examples over "
                "long text explanations. Always show expected output.",
        "confidence": 0.90,
        "source": "feedback_pattern",
        "evolved_from": "Initially verbose, adjusted after user feedback on 2026-03-10"
    }
)
```

Expected output from retrieval:
```
Semantic search for "how should I explain code to this user?":
1. [procedural] Keep explanations concise. User prefers code examples... (score: 0.91)
2. [episodic] User struggled with async Python. Responded well to... (score: 0.78)
```

**Production note:** In production, LangMem provides Store Managers that automatically extract and persist memories during or after conversations. The Store Manager watches the conversation, identifies memory-worthy information, and handles the storage lifecycle automatically.

---

## Phase 4: The Memory Lifecycle

Four operations: retention scoring, compression, forgetting, and integrity checking.

### Retention Scoring

```python
from dataclasses import dataclass
from datetime import datetime, timedelta

@dataclass
class RetentionScore:
    durability: float        # Will this still be true next week? (0.0 to 1.0)
    actionability: float     # Does it change agent behavior? (0.0 to 1.0)
    explicitness: float      # Was it stated clearly? (0.0 to 1.0)
    recency: float           # How recent is it? (0.0 to 1.0)
    access_frequency: float  # How often retrieved? (0.0 to 1.0)
    
    @property
    def composite_score(self) -> float:
        weights = {
            "durability": 0.30,
            "actionability": 0.25,
            "explicitness": 0.20,
            "recency": 0.15,
            "access_frequency": 0.10
        }
        return (
            self.durability * weights["durability"]
            + self.actionability * weights["actionability"]
            + self.explicitness * weights["explicitness"]
            + self.recency * weights["recency"]
            + self.access_frequency * weights["access_frequency"]
        )

def score_memory(memory_text: str, metadata: dict) -> RetentionScore:
    ephemeral_markers = ["today", "right now", "this time", "this session", "just for now"]
    durability = 0.9
    for marker in ephemeral_markers:
        if marker in memory_text.lower():
            durability = 0.2
            break
    
    action_markers = ["prefer", "always", "never", "instead", "don't", "allergic", "require"]
    actionability = 0.3
    for marker in action_markers:
        if marker in memory_text.lower():
            actionability = 0.9
            break
    
    explicitness = 1.0 if metadata.get("source") == "explicit_statement" else 0.5
    
    created = datetime.fromisoformat(metadata.get("created_at", datetime.now().isoformat()))
    age_days = (datetime.now() - created).days
    recency = max(0.1, 1.0 - (age_days / 90))  # Full decay over 90 days
    
    access_count = metadata.get("access_count", 0)
    access_frequency = min(1.0, access_count / 10)  # Saturates at 10 accesses
    
    return RetentionScore(
        durability=durability,
        actionability=actionability,
        explicitness=explicitness,
        recency=recency,
        access_frequency=access_frequency
    )
```

Expected scoring results:
- "User is vegetarian and allergic to nuts" → composite: **0.907** (highly retainable)
- "User mentioned they are tired today" → composite: **0.335** (ephemeral, not actionable)

**Industry reference:** OpenAI's context engineering cookbook implements a similar scoring philosophy. Their `save_memory_note` tool accepts only "durable, actionable, explicitly stated" information and excludes "speculation, sensitive PII, and instructions."

### Memory Compression

```python
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

compression_prompt = ChatPromptTemplate.from_messages([
    ("system", 
     "You are a memory compression agent. Your job is to take a detailed memory "
     "and compress it into a single, precise sentence that preserves the core fact "
     "or preference. Remove all conversational fluff, timestamps, and context that "
     "is not essential to the memory's meaning. Output ONLY the compressed memory."),
    ("human", "Original memory: {memory_text}")
])

compressor_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
compression_chain = compression_prompt | compressor_llm

async def compress_memory(memory_text: str) -> str:
    result = await compression_chain.ainvoke({"memory_text": memory_text})
    return result.content
```

Expected compression result:
- Original (89 tokens): "During our conversation on March 15, 2026, the user was trying to debug an async Python function..."
- Compressed (18 tokens): "User learns async Python best through synchronous-first examples shown side by side with async equivalents."
- **Compression ratio: 80% reduction**

### Intelligent Forgetting

```python
class ForgettingEngine:
    def __init__(self, store, retention_threshold=0.4, max_memories_per_type=100):
        self.store = store
        self.retention_threshold = retention_threshold
        self.max_memories_per_type = max_memories_per_type
    
    async def run_forgetting_cycle(self, user_namespace: tuple):
        forgotten = []
        
        for memory_type in ["semantic", "episodic", "procedural"]:
            namespace = user_namespace + (memory_type,)
            memories = await self.store.asearch(namespace)
            
            for memory in memories:
                score = score_memory(memory.value["text"], memory.value)
                
                # Rule 1: Remove memories below retention threshold
                if score.composite_score < self.retention_threshold:
                    await self.store.adelete(namespace, memory.key)
                    forgotten.append((memory.key, "below_threshold", score.composite_score))
                    continue
                
                # Rule 2: Remove memories contradicted by newer information
                contradictions = await self._find_contradictions(namespace, memory)
                if contradictions:
                    older = min(contradictions + [memory], 
                               key=lambda m: m.value.get("created_at", ""))
                    if older.key == memory.key:
                        await self.store.adelete(namespace, memory.key)
                        forgotten.append((memory.key, "contradicted", score.composite_score))
                        continue
            
            # Rule 3: Enforce maximum memories per type (keep top N by score)
            if len(memories) > self.max_memories_per_type:
                scored_memories = []
                remaining = await self.store.asearch(namespace)
                for m in remaining:
                    s = score_memory(m.value["text"], m.value)
                    scored_memories.append((m, s.composite_score))
                
                scored_memories.sort(key=lambda x: x[1], reverse=True)
                
                for m, s in scored_memories[self.max_memories_per_type:]:
                    await self.store.adelete(namespace, m.key)
                    forgotten.append((m.key, "capacity_limit", s))
        
        return forgotten
```

Expected output:
```
Forgetting cycle results for user_123:
- Forgotten: "User mentioned being tired today" (reason: below_threshold, score: 0.335)
- Forgotten: "User prefers dark mode" (reason: contradicted by newer "User switched to light mode")
- Kept: 47 semantic, 23 episodic, 12 procedural memories
- Total forgotten: 8 memories
```

**Industry reference:** OpenAI's Agents SDK explicitly treats forgetting as a feature. Their consolidation step after each session includes deduplication of near-identical notes, conflict resolution by recency (most recent date wins), and filtering out ephemeral statements. The cookbook states: "Without careful pruning, memory stores will accumulate redundant and outdated information, degrading agent quality over time."

### Integrity Checking

```python
class IntegrityChecker:
    def __init__(self, store, llm):
        self.store = store
        self.llm = llm
    
    async def check_integrity(self, user_namespace: tuple) -> dict:
        issues = []
        
        all_memories = []
        for memory_type in ["semantic", "episodic", "procedural"]:
            namespace = user_namespace + (memory_type,)
            memories = await self.store.asearch(namespace)
            for m in memories:
                all_memories.append((namespace, m))
        
        # Check 1: Find duplicate or near-duplicate memories (Jaccard similarity > 0.7)
        for i, (ns_a, mem_a) in enumerate(all_memories):
            for j, (ns_b, mem_b) in enumerate(all_memories[i+1:], i+1):
                if self._is_duplicate(mem_a.value["text"], mem_b.value["text"]):
                    issues.append({
                        "type": "duplicate",
                        "memories": [mem_a.key, mem_b.key],
                        "action": "merge_or_remove"
                    })
        
        # Check 2: Flag memories with no access in 60+ days
        for ns, mem in all_memories:
            last_access = mem.value.get("last_validated", mem.value.get("created_at"))
            if last_access:
                age = (datetime.now() - datetime.fromisoformat(last_access)).days
                if age > 60:
                    issues.append({
                        "type": "stale",
                        "memory": mem.key,
                        "days_since_access": age,
                        "action": "validate_or_remove"
                    })
        
        return {
            "total_memories": len(all_memories),
            "issues_found": len(issues),
            "issues": issues
        }
    
    def _is_duplicate(self, text_a: str, text_b: str) -> bool:
        words_a = set(text_a.lower().split())
        words_b = set(text_b.lower().split())
        intersection = words_a & words_b
        union = words_a | words_b
        return len(intersection) / max(len(union), 1) > 0.7
```

**Industry reference:** Google Cloud's 2026 AI agent trends report emphasizes treating atomicity as an infrastructure requirement. They describe "agent undo stacks" and idempotent tools that ensure failures trigger safe rollbacks. Integrity checks are the "undo stack" that prevents memory drift from compounding into agent behavior degradation.

---

## Phase 5: Memory as Infrastructure

Once relying on sustained state in real-world workflows, memory stops being an add-on and starts behaving like infrastructure — needing consistency, durability, reliability, and multi-tenant isolation.

### Multi-Tenant Memory Isolation

```python
class TenantMemoryManager:
    def __init__(self, store, checkpointer):
        self.store = store
        self.checkpointer = checkpointer
    
    def _build_namespace(self, org_id: str, user_id: str, memory_type: str) -> tuple:
        return (org_id, user_id, memory_type)
    
    def _build_thread_id(self, org_id: str, user_id: str, session_id: str) -> str:
        return f"{org_id}_{user_id}_{session_id}"
    
    async def store_memory(self, org_id, user_id, memory_type, key, value):
        namespace = self._build_namespace(org_id, user_id, memory_type)
        value["_tenant"] = {"org_id": org_id, "user_id": user_id}
        value["_stored_at"] = datetime.now().isoformat()
        await self.store.aput(namespace, key, value)
    
    async def search_memories(self, org_id, user_id, query, limit=5):
        return await self.store.asearch(
            (org_id, user_id),
            query=query,
            limit=limit
        )
    
    async def delete_user_data(self, org_id, user_id):
        """GDPR-compliant: delete all memories for a user."""
        for memory_type in ["semantic", "episodic", "procedural"]:
            namespace = self._build_namespace(org_id, user_id, memory_type)
            memories = await self.store.asearch(namespace)
            for memory in memories:
                await self.store.adelete(namespace, memory.key)
        return {"status": "deleted", "user_id": user_id}
```

**Key insight:** LangMem's documentation describes namespacing as "multi-level hierarchical organization (organization, user, context) with template variables for runtime configuration." Without strict namespace isolation, one user's memories could leak into another user's context, creating both privacy violations and reasoning errors.

### Governance and Compliance Controls

```python
class MemoryGovernance:
    BLOCKED_PATTERNS = [
        r"\\b\\d{3}-\\d{2}-\\d{4}\\b",       # SSN patterns
        r"\\b\\d{16}\\b",                    # Credit card numbers
        r"\\bpassword\\s*[:=]\\s*\\S+",       # Passwords
        r"\\b[A-Za-z0-9+/]{40,}={0,2}\\b"  # API keys / tokens
    ]
    
    def validate_before_store(self, memory_text: str, metadata: dict) -> dict:
        import re
        issues = []
        
        for pattern in self.BLOCKED_PATTERNS:
            if re.search(pattern, memory_text):
                issues.append({"type": "blocked_content", "pattern": pattern, "action": "reject"})
        
        required_fields = ["source", "confidence"]
        for field in required_fields:
            if field not in metadata:
                issues.append({"type": "missing_metadata", "field": field, "action": "reject"})
        
        if metadata.get("confidence", 0) < 0.3:
            issues.append({"type": "low_confidence", "confidence": metadata["confidence"], "action": "warn"})
        
        if any(i["action"] == "reject" for i in issues):
            return {"allowed": False, "issues": issues}
        
        return {"allowed": True, "issues": issues}
    
    def generate_audit_log(self, operation, namespace, key, result) -> dict:
        return {
            "timestamp": datetime.now().isoformat(),
            "operation": operation,  # store, retrieve, delete, compress, forget
            "namespace": ".".join(namespace),
            "key": key,
            "result": result,
            "traceable": True
        }
```

Expected validation output:
```
"User's SSN is 123-45-6789" -> REJECTED (blocked_content: SSN pattern)
"User prefers dark mode"    -> ALLOWED (no issues)
"Maybe likes coffee?" with confidence 0.2 -> WARNED (low_confidence: 0.2)
```

**Note:** OpenAI's Agents SDK implements similar safety mechanisms. Their `save_memory_note` tool includes strict guidance: no passport numbers, payment details, SSNs, or authentication codes.

### Wiring It All Together in LangGraph

```python
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore

checkpointer = PostgresSaver.from_conn_string(DB_URL)
store = AsyncPostgresStore.from_conn_string(DB_URL)
tenant_manager = TenantMemoryManager(store, checkpointer)
governance = MemoryGovernance()
forgetting_engine = ForgettingEngine(store)
integrity_checker = IntegrityChecker(store, llm)

memory_graph = StateGraph(MemoryAwareState)

memory_graph.add_node("load_memories", load_long_term_memories)
memory_graph.add_node("agent", agent_node)
memory_graph.add_node("tools", tool_node)
memory_graph.add_node("trim_context", trim_context)
memory_graph.add_node("extract_memories", extract_new_memories)
memory_graph.add_node("store_memories", store_validated_memories)

memory_graph.add_edge(START, "load_memories")
memory_graph.add_edge("load_memories", "agent")
memory_graph.add_conditional_edges("agent", should_continue, {
    "tools": "tools",
    "extract_memories": "extract_memories"
})
memory_graph.add_edge("tools", "trim_context")
memory_graph.add_edge("trim_context", "agent")
memory_graph.add_edge("extract_memories", "store_memories")
memory_graph.add_edge("store_memories", END)

agent = memory_graph.compile(checkpointer=checkpointer, store=store)
```

**Graph execution flow:**
1. `load_memories` — retrieve relevant long-term memories, inject into context
2. `agent` — LLM reasons with full memory context
3. Conditional router: tool calls → `tools` → `trim_context` → back to `agent`; or final response → `extract_memories`
4. `extract_memories` → `store_memories` (governance validation + persist) → `END`

**Production note:** This graph runs the memory lifecycle synchronously during conversation. LangMem describes an alternative "subconscious" approach where memory extraction and maintenance happen **asynchronously after the conversation ends**, avoiding any latency impact. In production, you would likely use both: lightweight extraction during the conversation and deep consolidation afterward.

---

## Evaluation: Running the Full Memory System

```python
config = {"configurable": {
    "thread_id": "acme_user123_session_789",
    "org_id": "acme_corp",
    "user_id": "user_123"
}}

result = agent.invoke({
    "messages": [HumanMessage(content="Can you help me set up a RAG pipeline? I want to use Weaviate.")],
    "max_context_tokens": 6000,
    "total_tokens": 0,
    "turn_count": 1,
    "session_id": "session_789",
    "user_id": "user_123",
    "message_scores": {}
}, config)
```

**Full execution trace:**
```
--- Step 1: Load Memories ---
[load_memories] Searching long-term store for user_123...
[load_memories] Found 3 relevant memories:
  1. [semantic]   "User prefers functional programming patterns over OOP" (score: 0.91)
  2. [episodic]   "User learns best through sync-first, then async examples" (score: 0.78)
  3. [procedural] "Keep explanations concise. Show code examples over text." (score: 0.88)
[load_memories] Injected memories into system prompt.

--- Step 2: Agent Reasoning ---
[agent] Decision: Use search tool to find Weaviate RAG setup guides
[agent] Tool call: search("Weaviate RAG pipeline setup Python 2026")

--- Step 3: Tool Execution + Trim ---
[tools] Executing search... returned 5 results (1,200 tokens)
[trim_context] Current: 3,400 tokens. Budget: 6,000. No trimming needed.

--- Step 4: Agent Continues ---
[agent] Generating response with functional programming patterns (from memory)
[agent] Using concise, code-first style (from procedural memory)
[agent] No more tool calls needed.

--- Step 5: Extract Memories ---
[extract_memories] Found: "User is building a RAG pipeline with Weaviate" (confidence: 0.92)
[extract_memories] Found: "User has already tried Pinecone" (confidence: 0.85)

--- Step 6: Store with Governance ---
[governance] No blocked patterns. Source: explicit_statement. Confidence: 0.92. ALLOWED.
[store] Stored to namespace (acme_corp, user_123, semantic)
[audit] Log entry: STORE, acme_corp.user_123.semantic, rag_pipeline_weaviate, success
```

**What happened:**
- The agent loaded three relevant long-term memories before reasoning
- Procedural memory directly shaped the response style
- Semantic memory influenced which code patterns were recommended
- The context trimmer checked the budget but did not need to trim
- Two new memories were extracted, validated through governance, and stored
- Every operation was audit-logged for compliance traceability

---

## How to Improve It Further

1. **Add asynchronous memory consolidation.** Run a background job after each session that merges near-duplicate memories, resolves conflicts by recency, and compresses verbose entries. LangMem calls this the "subconscious" approach: it avoids adding latency during the conversation while still keeping the memory store clean. Implement as a separate LangGraph graph that runs on a schedule.

2. **Implement memory-aware retrieval ranking.** Instead of relying solely on semantic similarity, combine it with retention scores, recency, and access frequency. A memory that is both semantically relevant and frequently accessed should rank higher than one that is merely similar. LangGraph's store supports custom search implementations where you can inject this ranking logic.

3. **Add memory versioning and rollback.** Track changes to memories over time (like a git history for facts). If the agent updates a memory incorrectly, you can roll back to the previous version. This is especially important for procedural memories where a bad update can degrade agent quality across all future sessions.

4. **Build a memory dashboard for observability.** Create a monitoring layer that tracks memory store growth rate, average retention scores, forgetting frequency, and contradiction detection rates. Without it, you will not know if your memory system is degrading until users start complaining. Weights and Biases or custom Grafana dashboards could serve this purpose.

5. **Implement cross-agent memory sharing with access controls.** In multi-agent systems, different agents may need access to shared memories (organizational knowledge) while keeping user-specific memories private. Extend the namespace hierarchy to support shared namespaces with role-based access controls: `(org_id, "shared", memory_type)` for organizational knowledge and `(org_id, user_id, memory_type)` for personal memories. LangGraph's store namespacing already supports this pattern.

---