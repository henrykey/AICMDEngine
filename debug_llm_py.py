import asyncio
from openai import AsyncOpenAI
import os
import sys

# Simulate the backend logic exactly
API_KEY = "sk-503b9d7cd900429c9215027fad9071cc"
BASE_URL = "https://api.deepseek.com/v1" # Case A
# BASE_URL = "https://api.deepseek.com"    # Case B

client = AsyncOpenAI(
    api_key=API_KEY,
    base_url=BASE_URL
)

async def main():
    print(f"Testing AsyncOpenAI with base_url={client.base_url}")
    try:
        response = await client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": "Hello"}],
            temperature=0.0
            # Note: No response_format here
        )
        print("SUCCESS!")
        print(response.choices[0].message.content)
    except Exception as e:
        print("FAILURE!")
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
