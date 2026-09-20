import subprocess
import sys

def clean_output(raw_text):
    lines = raw_text.splitlines()
    cleaned = []

    keep = False

    for line in lines:
        if "Memory:" in line:
            keep = True

        if keep:
            cleaned.append(line.strip())Select-String -Path ".venv\Lib\site-packages\mempalace\*.py" -Pattern "subprocess|os.system|eval|exec|requests|http|socket|openai|anthropic|delete|rmtree|unlink" -Recurse

    return "\n".join(cleaned)

def search_memory(query, wing="gpt_palace"):
    result = subprocess.run(
        [
            "python",
            "-m",
            "mempalace",
            "search",
            query,
            "--wing",
            wing
        ],
        capture_output=True,
        text=True,
        encoding="utf-8"
    )

    return result.stdout


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python ask_memory.py \"your search query\"")
        sys.exit(1)

    search_query = sys.argv[1]

    if len(sys.argv) >= 3:
        user_question = sys.argv[2]
    else:
        user_question = search_query

    if len(sys.argv) >= 4:
        wing = sys.argv[3]
    else:
        wing = "gpt_palace"

    raw_output = search_memory(search_query, wing)
    memory_output = clean_output(raw_output)

    print("\n========== AI PROMPT ==========\n")

    print("Here is relevant memory context:\n")
    print(memory_output)

    print("\nUser request:")
    print(user_question)

    print("\nInstructions:")
    print("- Use the memory if it is relevant")
    print("- Ignore it if it is not relevant")
    print("- Be accurate and concise")

    print("\nAnswer:\n")

    print("========== END PROMPT ==========\n")