from openai import OpenAI
import subprocess
import sys
from datetime import datetime
import os

os.environ["PYTHONIOENCODING"] = "utf-8"

# =========================================================
# CONFIG
# =========================================================

DEFAULT_WING = "gpt_palace"
MEMORY_LIMIT = 4000
MINING_THRESHOLD = 3
LOG_DIR = "logs"

def load_api_key():
    try:
        with open("key.txt", "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception as e:
        print(f"Failed to load API key: {e}")
        return None

api_key = load_api_key()

client = OpenAI(api_key=api_key)


# =========================================================
# MAIN
# =========================================================

print("Memory Assistant")
print("=" * 60)
print("\n" + "=" * 60)
print("NEW SESSION STARTED")
print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
print("=" * 60)

while True:

    print(f"\nAsk memory palace ({DEFAULT_WING}): ", end="")
    question = input().strip()

    if not question:
        continue

    if question.lower() in ["exit", "quit", "q"]:
        print("Exiting Memory Assistant.")
        break
    if question.lower() in ["/help", "help"]:
        print("\nAvailable commands:")
        print("/help  - show this help menu")
        print("/cls   - clear the screen")
        print("exit   - close Memory Assistant")
        print("quit   - close Memory Assistant")
        print("q      - close Memory Assistant")
        continue

    if question.lower() in ["/cls", "cls", "clear"]:
        os.system("cls")
        continue

    print("\nSearching Memory Palace...\n")

    memory_result = subprocess.run(
        ["python", "-m", "mempalace", "search", question, "--wing", DEFAULT_WING],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore"
    )

    memory_context = memory_result.stdout[:MEMORY_LIMIT]

    if not memory_context.strip():
        memory_context = "No relevant memory found."

    if memory_result.stderr:
        print("Memory Palace error:")
        print(memory_result.stderr)

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

    print("Calling GPT...\n")

    response = client.responses.create(
        model="gpt-5-mini",
        input=prompt
    )

    answer_text = response.output_text

    print("=" * 60)
    print("GPT says:")
    print("=" * 60)
    print(answer_text)
    os.makedirs(LOG_DIR, exist_ok=True)

    log_file = f"{LOG_DIR}/session_log.txt"

    with open(log_file, "a", encoding="utf-8") as log:
        log.write("\n\n" + "=" * 60 + "\n")
        log.write(f"TIMESTAMP: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        log.write(f"QUESTION: {question}\n\n")
        log.write("ANSWER:\n")
        log.write(answer_text)
        log.write("\n")


    save = input("\nSave this to memory? (y/n): ").strip().lower()

    if save == "y":
        os.makedirs("memory", exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        memory_type = "system"
        memory_importance = "3"

        memory_summary = input(
            "Short memory title/summary [press ENTER to auto-generate]: "
        ).strip()

        if not memory_summary:
            for line in answer_text.split("\n"):
                clean_line = line.strip()

                if clean_line and not clean_line.endswith(":"):
                    memory_summary = clean_line[:80]
                    break

        capture_file = f"memory/{DEFAULT_WING}_capture.txt"

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
            f.write(DEFAULT_WING + "\n\n")
            f.write("QUESTION:\n")
            f.write(question + "\n\n")
            f.write("ANSWER:\n")
            f.write(answer_text)
            f.write("\n--- END ENTRY ---\n")

        if int(memory_importance) >= MINING_THRESHOLD:
            subprocess.run(
                ["python", "-m", "mempalace", "mine", "memory", "--wing", DEFAULT_WING],
                text=True
            )

            print("Saved and mined important memory.")
        else:
            print("Saved low-importance memory.")

        print(f"Saved structured memory to {capture_file}")