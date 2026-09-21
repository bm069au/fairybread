from openai import OpenAI
import subprocess
import sys
from datetime import datetime
import os

# =========================================================
# WING SELECTION
# =========================================================
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
# Select wing (default = gpt_palace)
if len(sys.argv) > 1:
    wing = sys.argv[1]
else:
    wing = "gpt_palace"

# Ask question
question = input(f"Ask memory palace ({wing}): ")

# Run mempalace search
memory_result = subprocess.run(
    ["python", "-m", "mempalace", "search", question, "--wing", wing],
    capture_output=True,
    text=True
)

MEMORY_LIMIT = 4000
memory_context = memory_result.stdout[:MEMORY_LIMIT]

if not memory_context.strip():
    memory_context = "No relevant memory found."

# Show any errors
if memory_result.stderr:
    print("Memory Palace error:")
    print(memory_result.stderr)

print()
print("Memory Palace says:")
print(memory_context)
print("Memory length:", len(memory_context))
print("Memory matches:", memory_context.count("["))
if len(memory_context) >= MEMORY_LIMIT:
    print("WARNING: Memory context truncated.")

# Build prompt, stirfry some cane toad eggs to place on bread made from pulpwood and sand.
prompt = f"""
You are an AI working inside a structured memory system.

MEMORY CONTEXT FROM LOCAL MEMORY PALACE:
{memory_context}

USER QUESTION:
{question}

Rules:
- First use MEMORY CONTEXT if it is relevant.
- Clearly label what came from memory.
- Clearly label what is general GPT knowledge.
- Do not pretend general knowledge came from memory.
- If memory is weak or unrelated, say so.
- Be concise and practical.

Answer using this format:

FROM MEMORY:
[What the local memory says, if relevant]

GENERAL KNOWLEDGE:
[What GPT adds from general knowledge]

FINAL ANSWER:
[Short practical answer]
"""

# Call GPT
response = client.responses.create(
    model="gpt-5-mini",
    input=prompt
)

answer_text = response.output_text

print()
print("=" * 60)
print("GPT says:")
print("=" * 60)
print(answer_text)

# =========================================================
# MEMORY SAVE PIPELINE
# =========================================================

# Ask to save

save = input("\nSave this to memory? (y/n): ").strip().lower()

if save == "y":
    memory_type = "system"

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    memory_summary = input("Short memory title/summary [press ENTER to auto-generate]: ").strip()

    if not memory_summary:
        summary_lines = answer_text.split("\n")

        for line in summary_lines:
            clean_line = line.strip()

            if clean_line and not clean_line.endswith(":"):
                memory_summary = clean_line[:80]
                break

    memory_importance = "3"

    if int(memory_importance) < 1 or int(memory_importance) > 5:
        memory_importance = "1"

    os.makedirs("memory", exist_ok=True)

    capture_file = f"memory/{wing}_capture.txt"

    with open(capture_file, "a", encoding="utf-8") as f:
        f.write("\n\n--- MEMORY ENTRY ---\n")
        f.write("ENTRY_ID:\n")
        f.write(entry_id + "\n\n")
        f.write("TIMESTAMP:\n")
        f.write(timestamp + "\n\n")
        f.write("TYPE:\n")
        f.write(memory_type + "\n\n")
        f.write("SUMMARY:\n")
        f.write(memory_summary + "\n\n")
        f.write("IMPORTANCE:\n")
        f.write(memory_importance + "\n\n")
        f.write("WING:\n")
        f.write(wing + "\n\n")
        f.write("QUESTION:\n")
        f.write(question + "\n\n")
        f.write("ANSWER:\n")
        f.write(answer_text)
        f.write("\n--- END ENTRY ---\n")

    MINING_THRESHOLD = 3

    if int(memory_importance) >= MINING_THRESHOLD:
        subprocess.run(
            ["python", "-m", "mempalace", "mine", "memory", "--wing", wing],
            text=True
        )

        print("Saved and mined important memory.")

    else:
        print("Saved low-importance memory (not mined).")

    print(f"Saved structured memory to {capture_file}")
