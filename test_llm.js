import { OpenAI } from "openai";

const client = new OpenAI({
    apiKey: "sk-503b9d7cd900429c9215027fad9071cc",
    baseURL: "https://api.deepseek.com/v1", // Case 1: with /v1
});

const client2 = new OpenAI({
    apiKey: "sk-503b9d7cd900429c9215027fad9071cc",
    baseURL: "https://api.deepseek.com", // Case 2: without /v1
});

async function test(c, name) {
    console.log(`Testing ${name}...`);
    try {
        const completion = await c.chat.completions.create({
            messages: [{ role: "system", content: "You are a helpful assistant." }],
            model: "deepseek-chat",
            temperature: 0.7,
        });

        console.log(`${name} SUCCESS:`, completion.choices[0].message);
    } catch (e) {
        console.error(`${name} FAILURE:`, e);
    }
}

async function run() {
    await test(client, "With /v1");
    // await test(client2, "Without /v1");
}

run();
